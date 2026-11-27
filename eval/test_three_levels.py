#!/usr/bin/env python3
"""Assignment 03 Part B: offline testing at three levels (RAGOps paper 4.2.5, Table 1).

One command runs the whole suite against a running RAHBAR API and writes a
timestamped result file plus a Markdown summary table to the results folder:

    python eval/test_three_levels.py --api-url http://localhost:8000 --label baseline

Levels
  1. Module (embedding): mean cosine of 15 paraphrase pairs vs 15 unrelated pairs and
     the gap; embedding time per chunk (real chunks from the index); determinism
     (embed the same text twice, largest absolute difference).
  2. Component (retrieval): recall@3, recall@5, MRR, nDCG@5 against the golden
     ground-truth document; then a noise test (seeded typos in every query) and the
     change in each metric.
  3. End-to-end (answers): faithfulness judged by an LLM against the retrieved context,
     judge/human agreement on hand-labelled answers (eval/human_labels.jsonl),
     abstention correctness on must-abstain questions, citation validity, p50/p95.
  4. Stochasticity: seeds fixed (Python RNG, LLM seed and temperature on the API side);
     the whole suite runs --repeat times (default 2) and every metric's difference
     between run 1 and run 2 is reported.

Nothing is mocked: if the API, Ollama or the judge cannot be reached the suite fails
with exit code 2 instead of inventing numbers. The semantic cache is bypassed
(X-RAGOps-No-Cache) so repeated runs measure the pipeline, not Redis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent

PARAPHRASE_PAIRS = [
    ("What CGPA is required to avoid academic warning?", "What is the minimum CGPA to stay off academic warning?"),
    ("What is the tuition fee per credit hour for BS CS?", "How much does one credit hour cost in BS CS tuition?"),
    ("What attendance percentage is mandatory in each subject?", "What is the minimum attendance requirement per course?"),
    ("How is plagiarism defined in the student handbook?", "What is the definition of plagiarism in the university code of conduct?"),
    ("What is the maximum time allowed to complete a BS degree?", "How many years can a student take to finish a 4-year bachelor degree?"),
    ("What grade points are assigned to letter grade A+?", "How many GPA points does an A plus grade carry?"),
    ("What are the criteria for placement on academic probation?", "When does an undergraduate get placed on probation status?"),
    ("How does an incomplete grade I convert to an F grade?", "What is the deadline to clear an incomplete grade before it becomes an F?"),
    ("What is the normal semester credit hour limit for undergraduates?", "How many maximum credit hours can an undergraduate take in a regular term?"),
    ("What penalty is imposed for examination seating violations?", "What happens if a student refuses to sit in their designated exam seat?"),
    ("What is the undergraduate admission application processing fee?", "How much is the non-refundable admission registration fee?"),
    ("How can a student apply to freeze a semester on medical grounds?", "What is the procedure for semester leave due to medical illness?"),
    ("What equity percentage does the university claim in faculty start-ups?", "How much institutional equity is retained under the entrepreneurship policy?"),
    ("What daily Wi-Fi bandwidth quota is allocated to students?", "How many gigabytes of campus internet can a student use per day?"),
    ("What is the maximum Turnitin similarity allowed for FYP thesis?", "What is the allowed plagiarism percentage threshold for final year projects?"),
]

UNRELATED_PAIRS = [
    ("What CGPA is required to avoid academic warning?", "Where is the university swimming pool filtration plant located?"),
    ("What is the tuition fee per credit hour for BS CS?", "What are the dimensions of the badminton court in the sports complex?"),
    ("What attendance percentage is mandatory in each subject?", "How many commercial food vendors operate in the student cafeteria?"),
    ("How is plagiarism defined in the student handbook?", "What are the bus route numbers covering Rawalpindi?"),
    ("What is the maximum time allowed to complete a BS degree?", "What is the recipe for cafeteria chicken biryani?"),
    ("What grade points are assigned to letter grade A+?", "What is the server operating system used by the registrar portal?"),
    ("What are the criteria for placement on academic probation?", "How many trees were planted during the annual green campus drive?"),
    ("How does an incomplete grade I convert to an F grade?", "What brand of athletic footwear is required in the indoor gymnasium?"),
    ("What is the normal semester credit hour limit for undergraduates?", "What is the secret Wi-Fi password for guest visitors?"),
    ("What penalty is imposed for examination seating violations?", "Who is the head coach of the university cricket team?"),
    ("What is the undergraduate admission application processing fee?", "What is the weather forecast for Islamabad during exam week?"),
    ("How can a student apply to freeze a semester on medical grounds?", "How many parking slots are reserved for electric scooters?"),
    ("What equity percentage does the university claim in faculty start-ups?", "What are the library opening hours during Eid holidays?"),
    ("What daily Wi-Fi bandwidth quota is allocated to students?", "What is the history of the university founding charter?"),
    ("What is the maximum Turnitin similarity allowed for FYP thesis?", "What is the bus schedule on Sunday afternoons?"),
]

JUDGE_SYSTEM = (
    "You are a strict grader of a retrieval-augmented assistant. Decide whether EVERY factual "
    "claim in the ANSWER is directly supported by the CONTEXT passages. Paraphrase is fine; "
    "any number, date, name or rule not present in the CONTEXT makes the answer unsupported. "
    'Reply with JSON only: {"verdict": "supported" | "unsupported", "reason": "<one sentence>"}'
)


class SuiteError(RuntimeError):
    """The suite cannot measure honestly (service down, judge unavailable)."""


# ----------------------------------------------------------------------- helpers
def cosine(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    return dot / (n1 * n2) if n1 and n2 else 0.0


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (no interpolation): p95 of 32 values is the 31st."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def add_typos(query: str, rng: random.Random, n: int = 2) -> str:
    """Swap two adjacent inner letters in `n` different words of length >= 4."""
    words = query.split()
    candidates = [i for i, w in enumerate(words) if len(re.sub(r"\W", "", w)) >= 4]
    for idx in rng.sample(candidates, min(n, len(candidates))):
        w = list(words[idx])
        pos = rng.randint(1, len(w) - 3)
        w[pos], w[pos + 1] = w[pos + 1], w[pos]
        words[idx] = "".join(w)
    return " ".join(words)


def norm_doc(name: str | None) -> str:
    return str(name or "").strip().lower()


class Target:
    """The API under test plus the Ollama endpoint used for embeddings and the judge."""

    def __init__(self, api_url: str, ollama_url: str, embed_model: str, judge_model: str,
                 timeout: float, seed: int) -> None:
        self.api = api_url.rstrip("/")
        self.ollama = ollama_url.rstrip("/")
        self.embed_model = embed_model
        self.judge_model = judge_model
        self.seed = seed
        self.http = httpx.Client(timeout=timeout)
        self.headers = {"X-RAGOps-No-Cache": "1"}

    def info(self) -> dict[str, Any]:
        try:
            r = self.http.get(f"{self.api}/api/info")
            r.raise_for_status()
            return dict(r.json())
        except Exception as exc:
            raise SuiteError(f"API not reachable at {self.api}: {exc}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            r = self.http.post(f"{self.ollama}/api/embed", json={"model": self.embed_model, "input": texts})
            r.raise_for_status()
            vecs = r.json().get("embeddings") or []
        except Exception as exc:
            raise SuiteError(f"embedding call to {self.ollama} failed: {exc}") from exc
        if len(vecs) != len(texts):
            raise SuiteError(f"expected {len(texts)} embeddings, got {len(vecs)}")
        return vecs

    def retrieve(self, question: str, rid: str) -> dict[str, Any]:
        r = self.http.post(f"{self.api}/api/retrieve", json={"question": question},
                           headers={**self.headers, "X-Request-ID": rid})
        r.raise_for_status()
        return dict(r.json())

    def ask(self, question: str, rid: str) -> tuple[dict[str, Any], float]:
        t0 = time.perf_counter()
        r = self.http.post(f"{self.api}/api/ask", json={"question": question},
                           headers={**self.headers, "X-Request-ID": rid})
        elapsed = time.perf_counter() - t0
        r.raise_for_status()
        return dict(r.json()), elapsed

    def judge(self, question: str, answer: str, passages: list[dict[str, Any]]) -> tuple[bool, str]:
        context = "\n\n".join(f"[{i}] ({p['source']} p.{p.get('page')}) {p['text']}" for i, p in enumerate(passages, 1))
        payload = {
            "model": self.judge_model,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0, "seed": self.seed},
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": f"QUESTION: {question}\n\nCONTEXT:\n{context}\n\nANSWER: {answer}"},
            ],
        }
        try:
            r = self.http.post(f"{self.ollama}/api/chat", json=payload)
            r.raise_for_status()
            out = json.loads(r.json()["message"]["content"])
        except Exception as exc:
            raise SuiteError(f"faithfulness judge ({self.judge_model}) failed: {exc}") from exc
        verdict = str(out.get("verdict", "")).strip().lower()
        return verdict == "supported", str(out.get("reason", ""))[:300]


def load_golden(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SuiteError(f"no questions in {path}")
    return rows


def answer_sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def load_human_labels(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Hand labels from eval/label_answers.py, keyed by (question id, answer hash) so a
    label is only compared with the exact answer the human read."""
    if not path.exists():
        return {}
    labels = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[(row["id"], row["answer_sha"])] = row
    return labels


# ----------------------------------------------------------------------- level 1
def module_level(t: Target, chunk_texts: list[str]) -> dict[str, Any]:
    para = [cosine(a, b) for a, b in zip(*[iter(t.embed([x for pair in PARAPHRASE_PAIRS for x in pair]))] * 2)]
    unrel = [cosine(a, b) for a, b in zip(*[iter(t.embed([x for pair in UNRELATED_PAIRS for x in pair]))] * 2)]

    timings = []
    for text in chunk_texts:
        t0 = time.perf_counter()
        t.embed([text])
        timings.append((time.perf_counter() - t0) * 1000.0)

    probe = chunk_texts[0] if chunk_texts else PARAPHRASE_PAIRS[0][0]
    v1, v2 = t.embed([probe])[0], t.embed([probe])[0]
    max_diff = max(abs(a - b) for a, b in zip(v1, v2))

    mean_p, mean_u = statistics.mean(para), statistics.mean(unrel)
    return {
        "paraphrase_pairs": len(para),
        "unrelated_pairs": len(unrel),
        "mean_paraphrase_similarity": round(mean_p, 4),
        "mean_unrelated_similarity": round(mean_u, 4),
        "separation_gap": round(mean_p - mean_u, 4),
        "min_paraphrase_similarity": round(min(para), 4),
        "max_unrelated_similarity": round(max(unrel), 4),
        "embedding_time_ms_per_chunk": round(statistics.mean(timings), 2) if timings else None,
        "embedding_time_chunks_measured": len(timings),
        "determinism_max_abs_diff": max_diff,
    }


# ----------------------------------------------------------------------- level 2
def _rank_metrics(sources: list[str], gt: str) -> dict[str, float]:
    rel = [1 if norm_doc(s) == gt else 0 for s in sources]
    first = next((i + 1 for i, r in enumerate(rel) if r), 0)
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel[:5]))
    ideal = sorted(rel[:5], reverse=True)
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return {
        "hit3": float(any(rel[:3])),
        "hit5": float(any(rel[:5])),
        "rr": 1.0 / first if first else 0.0,
        "ndcg5": dcg / idcg if idcg else 0.0,
    }


def _aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    n = len(rows) or 1
    return {
        "recall_at_3": round(sum(r["hit3"] for r in rows) / n, 4),
        "recall_at_5": round(sum(r["hit5"] for r in rows) / n, 4),
        "mrr": round(sum(r["rr"] for r in rows) / n, 4),
        "ndcg_at_5": round(sum(r["ndcg5"] for r in rows) / n, 4),
    }


def component_level(t: Target, golden: list[dict[str, Any]], rng: random.Random, run: int,
                    per_q: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    answerable = [g for g in golden if not g.get("must_abstain") and g.get("ground_truth_doc")]
    clean_rows, noisy_rows = [], []
    contexts: dict[str, list[dict[str, Any]]] = {}
    for g in answerable:
        gt = norm_doc(g["ground_truth_doc"])
        res = t.retrieve(g["question"], f"eval-r{run}-ret-{g['id']}")
        passages = res.get("passages", [])
        contexts[g["id"]] = passages
        m = _rank_metrics([p["source"] for p in passages], gt)
        clean_rows.append(m)

        noisy_q = add_typos(g["question"], rng)
        noisy = t.retrieve(noisy_q, f"eval-r{run}-noise-{g['id']}")
        nm = _rank_metrics([p["source"] for p in noisy.get("passages", [])], gt)
        noisy_rows.append(nm)
        per_q.setdefault(g["id"], {}).update({
            "retrieved_top5": [f"{p['source']}#p{p.get('page')}@{p['score']}" for p in passages[:5]],
            "hit_at_5": bool(m["hit5"]),
            "noisy_query": noisy_q,
            "noisy_hit_at_5": bool(nm["hit5"]),
        })

    clean, noisy = _aggregate(clean_rows), _aggregate(noisy_rows)
    return {
        "questions": len(answerable),
        "relevance": "a retrieved chunk is relevant when its document equals the golden ground_truth_doc",
        **clean,
        "noise_test": {
            "method": "2 seeded adjacent-letter swaps per query",
            **{f"noisy_{k}": v for k, v in noisy.items()},
            **{f"delta_{k}": round(noisy[k] - clean[k], 4) for k in clean},
        },
    }, contexts


# ----------------------------------------------------------------------- level 3
def end_to_end_level(t: Target, golden: list[dict[str, Any]], contexts: dict[str, list[dict[str, Any]]],
                     labels: dict[tuple[str, str], dict[str, Any]], run: int,
                     per_q: dict[str, dict[str, Any]]) -> dict[str, Any]:
    latencies: list[float] = []
    abst_total = abst_ok = false_abst = answerable_n = 0
    cit_total = cit_valid = 0
    gt_cited = answered_answerable = 0
    judged = supported = 0
    agree = compared = 0
    disagreements: list[str] = []

    for g in golden:
        resp, elapsed = t.ask(g["question"], f"eval-r{run}-ask-{g['id']}")
        latencies.append(elapsed)
        answered = bool(resp.get("answered_from_context"))
        retrieved = {(norm_doc(r["source"]), r.get("page")) for r in resp.get("retrieved", [])}
        cites = resp.get("citations", [])
        valid = [c for c in cites if (norm_doc(c["source"]), c.get("page")) in retrieved]
        cit_total += len(cites)
        cit_valid += len(valid)

        row = per_q.setdefault(g["id"], {})
        row.update({"question": g["question"], "type": g.get("type"), "must_abstain": bool(g.get("must_abstain")),
                    "answered": answered, "answer": resp.get("answer", ""), "latency_s": round(elapsed, 3),
                    "citations": [f"{c['source']}#p{c.get('page')}" for c in cites],
                    "citations_valid": len(valid) == len(cites)})

        if g.get("must_abstain"):
            abst_total += 1
            abst_ok += not answered
            row["abstention_correct"] = not answered
            continue
        answerable_n += 1
        false_abst += not answered
        if not answered:
            continue
        answered_answerable += 1
        gt_cited += any(norm_doc(c["source"]) == norm_doc(g.get("ground_truth_doc")) for c in cites)

        passages = contexts.get(g["id"]) or t.retrieve(g["question"], f"eval-r{run}-ctx-{g['id']}").get("passages", [])
        ok, reason = t.judge(g["question"], resp.get("answer", ""), passages)
        judged += 1
        supported += ok
        row.update({"judge_supported": ok, "judge_reason": reason})
        lab = labels.get((g["id"], answer_sha(resp.get("answer", ""))))
        if lab is not None:
            compared += 1
            human = bool(lab["faithful"])
            agree += human == ok
            row["human_faithful"] = human
            if human != ok:
                disagreements.append(g["id"])

    return {
        "questions": len(golden),
        "faithfulness": round(supported / judged, 4) if judged else None,
        "faithfulness_judged_answers": judged,
        "judge_model": t.judge_model,
        "judge_human_agreement": round(agree / compared, 4) if compared else None,
        "judge_human_compared": compared,
        "judge_human_disagreements": disagreements,
        "abstention_correctness": round(abst_ok / abst_total, 4) if abst_total else None,
        "abstention_questions": abst_total,
        "false_abstention_rate": round(false_abst / answerable_n, 4) if answerable_n else None,
        "citation_validity": round(cit_valid / cit_total, 4) if cit_total else 1.0,
        "citations_total": cit_total,
        "ground_truth_cited_rate": round(gt_cited / answered_answerable, 4) if answered_answerable else None,
        "latency_p50_s": round(percentile(latencies, 50), 3),
        "latency_p95_s": round(percentile(latencies, 95), 3),
        "latency_mean_s": round(statistics.mean(latencies), 3),
    }


# ----------------------------------------------------------------------- driver
def run_once(t: Target, golden: list[dict[str, Any]], labels: dict[tuple[str, str], dict[str, Any]],
             seed: int, run: int) -> dict[str, Any]:
    random.seed(seed)
    rng = random.Random(seed)
    per_q: dict[str, dict[str, Any]] = {}

    print(f"\n=== run {run}: level 2 (component: retrieval) ===", flush=True)
    comp, contexts = component_level(t, golden, rng, run, per_q)
    chunk_texts = [p["text"] for ps in list(contexts.values())[:4] for p in ps][:20]

    print(f"=== run {run}: level 1 (module: embedding) ===", flush=True)
    mod = module_level(t, chunk_texts)

    print(f"=== run {run}: level 3 (end-to-end: answers) ===", flush=True)
    e2e = end_to_end_level(t, golden, contexts, labels, run, per_q)
    return {"module_level": mod, "component_level": comp, "end_to_end_level": e2e, "per_question": per_q}


def flat_metrics(r: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for level in ("module_level", "component_level", "end_to_end_level"):
        for k, v in r[level].items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                if k == "noise_test":
                    for nk, nv in v.items():
                        if isinstance(nv, (int, float)):
                            out[f"{level}.noise.{nk}"] = nv
                continue
            out[f"{level}.{k}"] = v
    return out


SUMMARY_ROWS = [
    ("Module", "module_level.mean_paraphrase_similarity", "Mean cosine, paraphrase pairs", "{:.4f}"),
    ("Module", "module_level.mean_unrelated_similarity", "Mean cosine, unrelated pairs", "{:.4f}"),
    ("Module", "module_level.separation_gap", "Gap (paraphrase - unrelated)", "{:.4f}"),
    ("Module", "module_level.embedding_time_ms_per_chunk", "Embedding time per chunk (ms)", "{:.1f}"),
    ("Module", "module_level.determinism_max_abs_diff", "Determinism: max |diff|", "{:.2e}"),
    ("Component", "component_level.recall_at_3", "Recall@3", "{:.4f}"),
    ("Component", "component_level.recall_at_5", "Recall@5", "{:.4f}"),
    ("Component", "component_level.mrr", "MRR", "{:.4f}"),
    ("Component", "component_level.ndcg_at_5", "nDCG@5", "{:.4f}"),
    ("Component", "component_level.noise.noisy_recall_at_5", "Recall@5 with typos", "{:.4f}"),
    ("Component", "component_level.noise.delta_recall_at_5", "  change", "{:+.4f}"),
    ("Component", "component_level.noise.delta_mrr", "  MRR change with typos", "{:+.4f}"),
    ("End-to-end", "end_to_end_level.faithfulness", "Faithfulness (LLM judge)", "{:.4f}"),
    ("End-to-end", "end_to_end_level.judge_human_agreement", "Judge/human agreement", "{:.4f}"),
    ("End-to-end", "end_to_end_level.abstention_correctness", "Abstention correctness", "{:.4f}"),
    ("End-to-end", "end_to_end_level.false_abstention_rate", "False abstention (answerable)", "{:.4f}"),
    ("End-to-end", "end_to_end_level.citation_validity", "Citation validity", "{:.4f}"),
    ("End-to-end", "end_to_end_level.latency_p50_s", "Latency p50 (s)", "{:.2f}"),
    ("End-to-end", "end_to_end_level.latency_p95_s", "Latency p95 (s)", "{:.2f}"),
]


def _fmt(fmt: str, v: Any) -> str:
    return "n/a" if v is None else fmt.format(v)


def summary_table(result: dict[str, Any]) -> str:
    runs = result["runs"]
    f1 = flat_metrics(runs[0])
    f2 = flat_metrics(runs[1]) if len(runs) > 1 else {}
    head = "| Level | Metric | Run 1 | Run 2 | Delta |\n|---|---|---|---|---|"
    lines = [head]
    for level, key, label, fmt in SUMMARY_ROWS:
        a, b = f1.get(key), f2.get(key)
        delta = (b - a) if (a is not None and b is not None) else None
        lines.append(f"| {level} | {label} | {_fmt(fmt, a)} | {_fmt(fmt, b) if f2 else '-'} | "
                     f"{_fmt('{:+.4f}', delta) if f2 else '-'} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="RAHBAR three-level offline evaluation suite (Part B)")
    ap.add_argument("--api-url", default=os.environ.get("EVAL_TARGET_URL", "http://localhost:8000"))
    ap.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", os.environ.get("LLM_MODEL", "llama3.2:3b")))
    ap.add_argument("--golden", default=os.environ.get("EVAL_GOLDEN", str(HERE / "golden.jsonl")))
    ap.add_argument("--labels", default=os.environ.get("EVAL_HUMAN_LABELS", str(HERE / "human_labels.jsonl")))
    ap.add_argument("--results-dir", default=os.environ.get("RESULTS_DIR", str(HERE / "results")))
    ap.add_argument("--label", default=os.environ.get("EVAL_LABEL", "baseline"),
                    help="baseline | candidate | any name; used in the result file name")
    ap.add_argument("--seed", type=int, default=int(os.environ.get("EVAL_SEED", 42)))
    ap.add_argument("--repeat", type=int, default=int(os.environ.get("EVAL_REPEAT", 2)))
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("EVAL_TIMEOUT", 120)))
    args = ap.parse_args()

    t = Target(args.api_url, args.ollama_url, args.embed_model, args.judge_model, args.timeout, args.seed)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    started = time.perf_counter()
    try:
        info = t.info()
        golden = load_golden(Path(args.golden))
        labels = load_human_labels(Path(args.labels))
        print(f"RAHBAR three-level suite | label={args.label} | target={args.api_url} | "
              f"collection={info.get('collection')} | golden={len(golden)} | seed={args.seed} | repeat={args.repeat}",
              flush=True)
        runs = [run_once(t, golden, labels, args.seed, i + 1) for i in range(max(1, args.repeat))]
    except (SuiteError, httpx.HTTPError) as exc:
        print(f"\nSUITE ERROR: {exc}\nNo result file written: the suite never reports numbers it did not measure.",
              file=sys.stderr, flush=True)
        return 2

    f1 = flat_metrics(runs[0])
    stoch = {}
    if len(runs) > 1:
        f2 = flat_metrics(runs[1])
        stoch = {k: {"run1": f1[k], "run2": f2.get(k), "delta": round(f2.get(k, 0) - f1[k], 6)}
                 for k in f1 if k in f2}
    golden_sha = hashlib.sha256(Path(args.golden).read_bytes()).hexdigest()[:12]
    result = {
        "label": args.label,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target": {"api_url": args.api_url, **info},
        "config": {"seed": args.seed, "repeat": len(runs), "golden": args.golden, "golden_sha256": golden_sha,
                   "golden_questions": len(golden), "human_labels": len(labels),
                   "embed_model": args.embed_model, "judge_model": args.judge_model, "cache": "bypassed"},
        # Reported metrics are run 1; run 2 exists to measure stochasticity.
        "module_level": runs[0]["module_level"],
        "component_level": runs[0]["component_level"],
        "end_to_end_level": runs[0]["end_to_end_level"],
        "stochasticity": {
            "max_abs_delta": max((abs(v["delta"]) for k, v in stoch.items()
                                  if "latency" not in k and "time_ms" not in k), default=0.0),
            "metrics": stoch,
        },
        "runs": runs,
        "total_runtime_seconds": round(time.perf_counter() - started, 1),
    }

    out_dir = Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"eval_{args.label}_{stamp}.json"
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    shutil.copy2(out_json, out_dir / f"latest_{args.label}.json")
    table = summary_table(result)
    md = (f"# RAHBAR evaluation: {args.label} ({result['timestamp']})\n\n"
          f"Target: `{args.api_url}`, collection `{info.get('collection')}` "
          f"({info.get('collection_version')}), embed `{info.get('embed_model')}` {info.get('embed_version')}, "
          f"top_k {info.get('top_k')}, seed {args.seed}, golden {len(golden)} questions.\n\n{table}\n")
    (out_dir / f"eval_{args.label}_{stamp}.md").write_text(md, encoding="utf-8")

    print("\n" + table)
    print(f"\nStochasticity: max |run2 - run1| over quality metrics = {result['stochasticity']['max_abs_delta']}")
    print(f"Result file:   {out_json}\nSummary table: {out_json.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
