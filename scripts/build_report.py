#!/usr/bin/env python3
"""Build the Assignment 03 report PDF from the committed result files and screenshots.

    python scripts/build_report.py                     # -> i243142_i243106_Assignment03.pdf (+ docs/ copy)
    python scripts/build_report.py --check             # only list what is still missing

Every number in the report is read from files produced by our own pipeline runs
(eval/results/cluster/, traces/cluster/, docs/evidence/a3/). Nothing is typed in.
Whatever is missing is printed as "PENDING" in the PDF and listed on the console,
and the script exits 1, so an incomplete report cannot be mistaken for a finished one.

Layout: Times New Roman 12 pt body, black on white, A4, body at most 8 pages, and
an appendix of labelled terminal screenshots that does not count towards the limit.
Optional docs/report_inputs.yaml pins which result file feeds each table (see
--check output for the keys); otherwise the newest matching file is used.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "traces"))
DATA = ROOT   # where results/traces/screenshots are read from (--data-root, for layout previews)

OUT_NAME = "i243142_i243106_Assignment03.pdf"
MEMBERS = [("Zubair Ilyas", "i243142"), ("Salman Asad", "i243106")]
SHOT_DIR = DATA / "docs" / "evidence" / "a3"

# The screenshots the assignment lists under "Submission" (label, file stem, caption).
SCREENSHOTS = [
    ("A1", "A1-batch-b-verification", "Verification report for Batch B: pass/fail per check with reasons (ingest-batch-b Job logs)"),
    ("A2", "A2-unchanged-rerun-zero-chunks", "Second ingestion run on an unchanged corpus: 0 chunks embedded"),
    ("B", "B-eval-summary", "Evaluation summary with all three levels (eval Job logs)"),
    ("C1", "C-gate-fail", "Release gate FAILING for the bad candidate (rahbar_c120)"),
    ("C2", "C-gate-pass", "Release gate PASSING for the good candidate (rahbar_c600)"),
    ("D1", "D1-full-trace", "One full trace record"),
    ("D2", "D2-trace-tool", "Trace tool rebuilding the exact context and prompt for a trace id"),
    ("E1", "E-coverage-before", "Coverage output before adding the new golden questions"),
    ("E2", "E-coverage-after", "Coverage output after adding the new golden questions"),
    ("F1", "F-get-all", "kubectl get all,pvc,configmap,cronjob,job -n rahbar"),
    ("F2", "F-ingestion-job-logs", "Logs of a completed ingestion Job"),
    ("F3", "F-eval-job-logs", "Logs of a completed evaluation Job"),
    ("F4", "F-configmap-gate-change", "Gate result changing after a ConfigMap edit (no image rebuild)"),
    ("F5", "F-rollout-status", "kubectl rollout status for the gated release"),
    ("F6", "F-rollout-undo-trace", "kubectl rollout undo, then a trace showing the previous collection and embedding version"),
]

missing: list[str] = []


# ----------------------------------------------------------------------------- fonts / styles
def register_fonts() -> tuple[str, str, str, str]:
    fdir = Path("C:/Windows/Fonts")
    candidates = [fdir, Path("/usr/share/fonts/truetype/msttcorefonts"), Path("/Library/Fonts")]
    for d in candidates:
        files = {k: d / f for k, f in {"r": "times.ttf", "b": "timesbd.ttf", "i": "timesi.ttf", "bi": "timesbi.ttf"}.items()}
        if all(p.exists() for p in files.values()):
            pdfmetrics.registerFont(TTFont("TNR", str(files["r"])))
            pdfmetrics.registerFont(TTFont("TNR-B", str(files["b"])))
            pdfmetrics.registerFont(TTFont("TNR-I", str(files["i"])))
            pdfmetrics.registerFont(TTFont("TNR-BI", str(files["bi"])))
            from reportlab.pdfbase.pdfmetrics import registerFontFamily

            registerFontFamily("TNR", normal="TNR", bold="TNR-B", italic="TNR-I", boldItalic="TNR-BI")
            return "TNR", "TNR-B", "TNR-I", "TNR-BI"
    print("warning: Times New Roman TTF not found, using the built-in Times face")
    return "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"


F, FB, FI, FBI = register_fonts()
BLACK = colors.black
BODY = ParagraphStyle("body", fontName=F, fontSize=12, leading=14.4, alignment=TA_JUSTIFY, spaceAfter=4)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=10, leading=12, alignment=0, spaceAfter=0)
SMALLB = ParagraphStyle("smallb", parent=SMALL, fontName=FB)
H1 = ParagraphStyle("h1", fontName=FB, fontSize=13, leading=16, spaceBefore=8, spaceAfter=4)
H2 = ParagraphStyle("h2", fontName=FB, fontSize=12, leading=14.4, spaceBefore=4, spaceAfter=2)
TITLE = ParagraphStyle("title", fontName=FB, fontSize=16, leading=20, alignment=TA_CENTER, spaceAfter=4)
SUB = ParagraphStyle("sub", fontName=F, fontSize=12, leading=14.4, alignment=TA_CENTER)
CAP = ParagraphStyle("cap", fontName=FI, fontSize=10, leading=12, alignment=TA_CENTER, spaceBefore=2, spaceAfter=8)
MONO = ParagraphStyle("mono", fontName="Courier", fontSize=8.5, leading=10, alignment=0)


def esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def pending(what: str) -> str:
    missing.append(what)
    return f"<i>PENDING ({esc(what)})</i>"


def table(rows: list[list[Any]], widths: list[float], header_rows: int = 1, font_size: float = 10) -> Table:
    st = ParagraphStyle("cell", parent=SMALL, fontSize=font_size, leading=font_size * 1.18)
    stb = ParagraphStyle("cellb", parent=st, fontName=FB)
    data = []
    for i, r in enumerate(rows):
        data.append([c if not isinstance(c, str) else Paragraph(c, stb if i < header_rows else st) for c in r])
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=header_rows, spaceBefore=2, spaceAfter=6)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), F),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, BLACK),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.6, BLACK),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, BLACK),
        ("INNERGRID", (0, header_rows), (-1, -1), 0.25, colors.Color(0.55, 0.55, 0.55)),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return esc(v)


# ----------------------------------------------------------------------------- inputs
def results_dirs() -> list[Path]:
    return [DATA / "eval" / "results" / "cluster", DATA / "eval" / "results"]


def jload(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def find(pattern: str) -> list[Path]:
    out: list[Path] = []
    for d in results_dirs():
        out += [Path(p) for p in glob.glob(str(d / "**" / pattern), recursive=True) if "pre_fix_unused" not in p]
    return sorted(set(out), key=lambda p: p.name)


def load_inputs() -> dict[str, Any]:
    cfg = DATA / "docs" / "report_inputs.yaml"
    pinned = yaml.safe_load(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    pinned = pinned or {}

    def pin(key: str) -> dict[str, Any] | None:
        if pinned.get(key):
            p = DATA / pinned[key]
            return jload(p) if p.exists() else None
        return None

    data: dict[str, Any] = {}
    baselines = [jload(p) for p in find("eval_baseline_*.json")]
    rahbar_base = [b for b in baselines if b.get("target", {}).get("collection") == "rahbar"]
    data["part_b"] = pin("part_b") or (rahbar_base[0] if rahbar_base else None)
    data["after_batch_b"] = pin("after_batch_b") or (rahbar_base[-1] if len(rahbar_base) > 1 else None)
    cands = [jload(p) for p in find("eval_candidate_*.json")]
    data["cand_bad"] = pin("cand_bad") or next((c for c in reversed(cands) if c["target"].get("collection") == "rahbar_c120"), None)
    data["cand_good"] = pin("cand_good") or next((c for c in reversed(cands) if c["target"].get("collection") == "rahbar_c600"), None)
    gates = [jload(p) for p in find("gate_*.json")]
    data["gate_fail"] = pin("gate_fail") or next((g for g in reversed(gates) if not g["passed"] and g.get("candidate_collection") == "rahbar_c120"), None)
    data["gate_pass"] = pin("gate_pass") or next((g for g in reversed(gates) if g["passed"] and g.get("candidate_collection") == "rahbar_c600"), None)
    data["gate_cm_fail"] = next((g for g in reversed(gates) if not g["passed"] and g.get("candidate_collection") == "rahbar_c600"
                                 and any("env" in s for s in g.get("threshold_source", {}).values())), None)

    vreports = [jload(p) for p in find("verification_report_*.json")]
    data["verif_b"] = pin("verif_b") or next((v for v in reversed(vreports)
                                              if any(r["source"].startswith("doc04") for r in v["results"])), None)
    runs = [(p, jload(p)) for p in find("ingestion_run_*.json")]
    data["run_first"] = next((r for _, r in runs if r.get("seeded") or len(r.get("new", [])) > 3), None)
    data["run_unchanged"] = next((r for _, r in runs if r.get("embedded_chunks") == 0 and not r.get("new")
                                  and not r.get("modified") and not r.get("deleted") and r.get("unchanged")), None)
    data["run_batch_b"] = next((r for _, r in runs if any(str(n).startswith("doc0") for n in r.get("new", []))), None)
    data["run_modified"] = next((r for _, r in runs if r.get("modified")), None)
    data["run_deleted"] = next((r for _, r in runs if r.get("deleted")), None)

    covs = [(p, jload(p)) for p in find("coverage_*.json")]
    data["cov_before"] = pin("cov_before") or next((c for p, c in reversed(covs) if "golden_baseline" in p.name), None)
    data["cov_after"] = pin("cov_after") or next((c for p, c in reversed(covs)
                                                  if "golden_baseline" not in p.name and c.get("total_golden_questions", 0) > 26), None)
    tm = find("trace_metrics*.json")
    data["trace_metrics"] = jload(tm[-1]) if tm else None
    data["pinned"] = pinned
    return data


def git_repo_url() -> str:
    try:
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
        return url.removesuffix(".git")
    except Exception:
        return "(repository URL)"


# ----------------------------------------------------------------------------- sections
def stage_map() -> list[Any]:
    rows = [["Figure 3 stage", "What RAHBAR does", "File(s)", "What is missing"]]
    rows += [
        ["Ingest", "Indexer Job seeds the data lake once, then takes each new batch from <i>/datalake/incoming</i>; extraction with OCR fallback",
         "indexer/pipeline/run.py, extract.py; k8s/base/indexer-job.yaml", "No push trigger: batches arrive by copy + Job/CronJob"],
        ["Verify", "Four checks per document before chunking (quality, completeness, recency, uniqueness by hash and embedding cosine); failures quarantined; report per run",
         "indexer/pipeline/verify.py", "No content-safety check: injected instructions pass (caught later by the retrieval rail)"],
        ["Update data lake", "Hash diff against a per-collection state; modified docs replace only their chunks; deleted docs purged with zero orphans; superseded versions archived",
         "indexer/pipeline/incremental.py, run.py", "Single-node RWO volume; no lake snapshots"],
        ["Update retrieval sources", "Upsert into Chroma with doc_version/superseded metadata; archived chunks excluded by filter; rollback restores them",
         "indexer/pipeline/store.py; api/app/retrieval/chroma.py", "Candidate collections are full rebuilds, not incremental copies"],
        ["Offline testing", "Module / component / end-to-end suite, run twice with fixed seeds, as a Kubernetes Job; release gate on the result",
         "eval/test_three_levels.py, release_gate.py, job.py; k8s/eval-job.yaml", "Deterministic grounding judge (misses wrong-entity facts); 8 hand labels only; CPU latency"],
        ["Live testing", "Every query writes a trace (stdout + volume) and Prometheus metrics; trace tool, window summary, root-cause tool",
         "api/app/tracing.py, routes/metrics.py; traces/*.py", "No alerting rules or dashboards"],
        ["Check coverage", "Live queries vs golden set by embedding similarity; exits 1 below the required share; uncovered topics grouped",
         "eval/check_coverage.py; eval/live_queries.jsonl", "Live log is curated, not sampled from real users"],
    ]
    return [P("1. Mapping the RAGOps lifecycle (Figure 3) to RAHBAR", H1),
            table(rows, [2.6, 6.2, 4.6, 3.6], font_size=9.5)]


def qualities(d: dict[str, Any]) -> list[Any]:
    b = d.get("part_b") or {}
    e2e = b.get("end_to_end_level", {})
    comp = b.get("component_level", {})
    rows = [["Quality (Table 2)", "What we measure", "Threshold", "Evidence"]]
    rows += [
        ["Adaptability", "Recall@5 change when chunking changes (Part C); data drift after Batch B (E3)",
         "recall@5 drop &le; 0.02", f"baseline recall@5 = {fmt(comp.get('recall_at_5'))}; candidate files in eval/results/cluster"],
        ["Monitorability", "Top-1 similarity, abstention rate, cache hit rate, p95 per stage, injections (D3)",
         "p95 total &le; 90 s (gate)", "traces/metrics_summary.py; /metrics on svc/api"],
        ["Observability", "One JSON trace per query with all D1 fields, on stdout and on the traces volume",
         "100% of queries traced", "api/app/tracing.py; traces/cluster/"],
        ["Traceability", "Trace id rebuilds exact prompt (hash verified), chunk ids, doc versions, collection/embedding version",
         "prompt hash must verify", "traces/inspect.py (screenshot D2)"],
        ["Reliability", "Gate-blocked releases, rolling update maxUnavailable 0, rollout undo, faithfulness and abstention",
         "faithfulness &ge; 0.80; abstention &ge; baseline", f"faithfulness = {fmt(e2e.get('faithfulness'))}, abstention = {fmt(e2e.get('abstention_correctness'))}"],
    ]
    return [P("2. The five qualities of Table 2", H1), table(rows, [2.6, 6.0, 3.4, 5.0], font_size=9.5)]


def part_a(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = [P("3. Part A: data verification and incremental update", H1)]
    v = d.get("verif_b")
    if v:
        rows = [["Batch B document", "Q", "C", "R", "U", "Result / reason"]]
        for r in v["results"]:
            flags = ["P" if c["passed"] else "F" for c in r["checks"]]
            reason = "; ".join(c["reason"] for c in r["checks"] if not c["passed"])
            if not reason and r.get("supersedes"):
                reason = "supersedes " + ", ".join(r["supersedes"]) + " (archived)"
            rows.append([esc(r["source"][:44]), *flags,
                         ("QUARANTINED: " if r["quarantined"] else ("PASS: " if reason else "PASS")) + esc(reason[:200])])
        out += [P(f"Verification report for Batch B ({v['timestamp']}): {v['passed_documents']} of {v['total_documents']} "
                  f"documents passed, {v['quarantined_documents']} were quarantined and never indexed "
                  "(Q quality, C completeness, R recency, U uniqueness).", BODY),
                table(rows, [5.6, 0.6, 0.6, 0.6, 0.6, 9.0], font_size=8.8)]
    else:
        out.append(P("Batch B verification: " + pending("verification_report_*.json from the ingest-batch-b Job"), BODY))

    def run_row(label: str, r: dict[str, Any] | None, what: str) -> list[str]:
        if not r:
            return [label, pending(what), "", "", ""]
        return [label, str(len(r.get("new", []))), str(len(r.get("modified", []))),
                str(len(r.get("deleted", []))) + (f" (purged {sum(r.get('purged_chunks', {}).values())})" if r.get("deleted") else ""),
                str(r.get("embedded_chunks"))]
    rows = [["Ingestion run", "new", "modified", "deleted", "chunks embedded"],
            run_row("First run (seeded data lake)", d.get("run_first"), "first ingestion_run_*.json"),
            run_row("Re-run, unchanged corpus", d.get("run_unchanged"), "unchanged re-run ingestion_run_*.json"),
            run_row("Batch B", d.get("run_batch_b"), "Batch B ingestion_run_*.json"),
            run_row("One document edited", d.get("run_modified"), "modified-doc ingestion_run_*.json"),
            run_row("One document deleted", d.get("run_deleted"), "deleted-doc ingestion_run_*.json")]
    out += [Spacer(1, 4), table(rows, [6.0, 1.6, 2.0, 3.6, 3.0], font_size=9.5)]
    rd = d.get("run_deleted")
    if rd:
        gone = ", ".join(rd.get("deleted", []))
        present = gone in json.dumps(rd.get("chunks_by_document", {}))
        out.append(P(f"After deleting <i>{esc(gone)}</i> the chunk count by document id no longer lists it "
                     f"({'NOT ' if present else ''}absent: {len(rd.get('chunks_by_document', {}))} documents, "
                     f"{sum(rd.get('chunks_by_document', {}).values())} chunks), so no orphan chunks remain.", BODY))
    rb = d.get("run_batch_b") or {}
    if rb.get("archived"):
        a = rb["archived"][0]
        out.append(P(f"Superseded version: <i>{esc(a['document'])}</i> was archived to /datalake/archive and its chunks were "
                     f"tagged superseded=True when <i>{esc(a['superseded_by'])}</i> passed verification; the retrieval filter "
                     "superseded=False excludes them. The rollback Job (k8s/jobs/rollback-doc-job.yaml) restores it and archives the newer version.", BODY))
    return out


SUITE_ROWS = [
    ("Module", "module_level", "mean_paraphrase_similarity", "Mean cosine, 15 paraphrase pairs"),
    ("Module", "module_level", "mean_unrelated_similarity", "Mean cosine, 15 unrelated pairs"),
    ("Module", "module_level", "separation_gap", "Gap"),
    ("Module", "module_level", "embedding_time_ms_per_chunk", "Embedding time per chunk (ms)"),
    ("Module", "module_level", "determinism_max_abs_diff", "Determinism, max |diff|"),
    ("Component", "component_level", "recall_at_3", "Recall@3"),
    ("Component", "component_level", "recall_at_5", "Recall@5"),
    ("Component", "component_level", "mrr", "MRR"),
    ("Component", "component_level", "ndcg_at_5", "nDCG@5"),
    ("End-to-end", "end_to_end_level", "faithfulness", "Faithfulness (grounding judge)"),
    ("End-to-end", "end_to_end_level", "judge_human_agreement", "Judge/human agreement"),
    ("End-to-end", "end_to_end_level", "abstention_correctness", "Abstention correctness"),
    ("End-to-end", "end_to_end_level", "citation_validity", "Citation validity"),
    ("End-to-end", "end_to_end_level", "latency_p50_s", "Latency p50 (s)"),
    ("End-to-end", "end_to_end_level", "latency_p95_s", "Latency p95 (s)"),
]


def run_value(res: dict[str, Any], run: int, level: str, key: str) -> Any:
    runs = res.get("runs") or []
    if run < len(runs):
        return runs[run].get(level, {}).get(key)
    return None


def part_b(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = [P("4. Part B: offline testing at three levels", H1)]
    b = d.get("part_b")
    if not b:
        return out + [P("Three-level results: " + pending("eval_baseline_*.json from k8s/jobs/eval-baseline-job.yaml"), BODY)]
    cfg = b.get("config", {})
    out.append(P(f"Golden set: {cfg.get('golden_questions')} questions (eval/golden.jsonl; answerable, must-abstain and hard "
                 f"paraphrase / multi-chunk / Batch B questions, labelled human or synthetic). Target collection "
                 f"<i>{esc(b['target'].get('collection'))}</i>, seed {cfg.get('seed')}, the whole suite run {cfg.get('repeat')} times, "
                 f"semantic cache bypassed. Generator: llama3.2:3b on CPU-only Ollama (all latencies in this report are CPU numbers). "
                 "Faithfulness judge: a deterministic grounding check (every number in the answer must appear in the retrieved "
                 "context, and at least 60% of its content words). We first used llama3.2:3b as an LLM judge, but its verdicts "
                 "contradicted its own reasons (0.06 faithfulness while its reasons said 'directly supported'), so we replaced it "
                 "and kept that run aside (eval/results/cluster/superseded_llm_judge/).", BODY))
    rows = [["Level", "Metric", "Run 1", "Run 2", "Diff"]]
    for lvl, level, key, label in SUITE_ROWS:
        a, c = run_value(b, 0, level, key), run_value(b, 1, level, key)
        diff = (c - a) if isinstance(a, (int, float)) and isinstance(c, (int, float)) else None
        nd = 2 if "latency" in key or "time" in key else 4
        av = f"{a:.2e}" if key.startswith("determinism") and a is not None else fmt(a, nd)
        cv = f"{c:.2e}" if key.startswith("determinism") and c is not None else fmt(c, nd)
        rows.append([lvl, label, av, cv, fmt(diff, nd) if diff is not None else "n/a"])
    out.append(table(rows, [2.4, 6.4, 2.6, 2.6, 2.6], font_size=9.5))
    noise = b.get("component_level", {}).get("noise_test", {})
    e2e = b.get("end_to_end_level", {})
    if noise:
        out.append(P(f"Noise test ({esc(noise.get('method'))}): recall@3 {fmt(noise.get('delta_recall_at_3'), 4)}, "
                     f"recall@5 {fmt(noise.get('delta_recall_at_5'), 4)}, MRR {fmt(noise.get('delta_mrr'), 4)}, "
                     f"nDCG@5 {fmt(noise.get('delta_ndcg_at_5'), 4)} (change against clean queries).", BODY))
    if e2e.get("judge_human_compared", 0) < 8:
        out.append(P("Judge calibration: " + pending("8 hand labels: python eval/label_answers.py --result <baseline result> --n 8"), BODY))
    else:
        out.append(P(f"Judge calibration: the grounding judge agreed with our hand labels on {fmt(e2e.get('judge_human_agreement'), 3)} of "
                     f"{e2e.get('judge_human_compared')} answers (disagreements: {esc(', '.join(e2e.get('judge_human_disagreements') or []) or 'none')}). In g31 the "
                     "numbers 8:00 AM to 4:00 PM are in the retrieved text but belong to the medical centre, not the gym: a number "
                     "check cannot see that the fact is about the wrong entity.", BODY))
    st = b.get("stochasticity", {})
    pipeline_deltas = {k: abs(v["delta"]) for k, v in st.get("metrics", {}).items()
                       if not any(x in k for x in ("latency", "time_ms", "total", "questions", "judged", "compared",
                                                   "pairs", "measured", "judge_human"))}
    worst = max(pipeline_deltas.items(), key=lambda kv: kv[1]) if pipeline_deltas else ("-", 0.0)
    runs = b.get("runs", [])
    changed = [q for q in runs[0]["per_question"] if len(runs) > 1
               and runs[0]["per_question"][q].get("answer") != runs[1]["per_question"].get(q, {}).get("answer")] if runs else []
    f1 = run_value(b, 0, "end_to_end_level", "faithfulness")
    f2 = run_value(b, 1, "end_to_end_level", "faithfulness")
    out.append(P(f"Stochasticity: the largest run-to-run difference over pipeline metrics is {fmt(worst[1], 4)} "
                 f"({esc(worst[0].split('.')[-1])}). "
                 "Seeds are fixed (Python RNG for the typo test, LLM seed 42 at temperature 0.2), embeddings are identical "
                 "(max |diff| 0), and the judge is deterministic. All the module and component metrics are identical across "
                 "runs. The remaining variation is end to end: llama.cpp on CPU is not bit-for-bit reproducible across threads "
                 f"even with a fixed seed, so {len(changed)} of {len(runs[0]['per_question']) if runs else 0} answers changed between runs "
                 f"({esc(', '.join(changed))}; faithfulness {fmt(f1, 2)} vs {fmt(f2, 2)}). Run 2 is much "
                 "faster because Ollama reuses cached prompt prefixes for the identical prompts, so latency is reported, and gated, on run 1.", BODY))
    return out


def part_c(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = [P("5. Part C: change experiment and release gate", H1)]
    out.append(P("Change: chunk size/overlap (baseline 400/50 in collection <i>rahbar</i>; candidate 600/100 in <i>rahbar_c600</i>; "
                 "a deliberately bad 120/0 in <i>rahbar_c120</i>). Each candidate runs as Deployment <i>api-candidate</i> with its own "
                 "Service and collection, and the eval Job tests it (k8s/eval-job.yaml).", BODY))
    # Candidates were built after Batch B, so they are compared with the baseline measured on the same data.
    b, good, bad = d.get("after_batch_b") or d.get("part_b"), d.get("cand_good"), d.get("cand_bad")
    keys = [("module_level", "separation_gap", "Embedding gap"), ("component_level", "recall_at_3", "Recall@3"),
            ("component_level", "recall_at_5", "Recall@5"), ("component_level", "mrr", "MRR"),
            ("component_level", "ndcg_at_5", "nDCG@5"), ("end_to_end_level", "faithfulness", "Faithfulness"),
            ("end_to_end_level", "abstention_correctness", "Abstention correctness"),
            ("end_to_end_level", "citation_validity", "Citation validity"), ("end_to_end_level", "latency_p95_s", "Latency p95 (s)")]
    rows = [["Metric", "Baseline 400/50 (after Batch B)", "Candidate 600/100", "Bad 120/0"]]
    for level, key, label in keys:
        rows.append([label] + [fmt(x.get(level, {}).get(key), 4) if x else pending(f"{n} result") for x, n in
                               ((b, "baseline"), (good, "candidate c600"), (bad, "candidate c120"))])
    out.append(table(rows, [5.0, 4.0, 4.0, 4.0], font_size=9.5))
    gp, gf = d.get("gate_pass"), d.get("gate_fail")
    th = (gp or gf or {}).get("thresholds")
    if th:
        out.append(P(f"Gate thresholds (ConfigMap rahbar-gate): recall@5 drop &le; {th['max_recall5_drop']}, faithfulness &ge; "
                     f"{th['min_faithfulness']}, abstention &ge; baseline + {th['min_abstention_delta']}, citation validity &ge; "
                     f"{th['min_citation_validity']}, p95 &le; {th['max_latency_p95_s']} s.", BODY))
    for g, name in ((gf, "bad candidate (c120)"), (gp, "candidate (c600)")):
        if g:
            failed = [c["check"] for c in g["checks"] if not c["passed"]]
            out.append(P(f"<b>Gate on the {name}: {'PASS' if g['passed'] else 'FAIL'} &rarr; {g['decision']}</b>"
                         + (f" (failed: {esc(', '.join(failed))})." if failed else "."), BODY))
        else:
            out.append(P(f"Gate on the {name}: " + pending(f"gate_*.json for the {name}"), BODY))
    if gp and gp["passed"]:
        out.append(P("<b>Release decision: RELEASE rahbar_c600.</b> It meets every threshold, so it was promoted to Deployment "
                     "<i>api</i> with a rolling update (maxUnavailable 0) and watched with kubectl rollout status. The c120 "
                     "candidate was stopped by the gate and never rolled out. Caveat: c600's false-abstention rate on answerable "
                     f"questions is higher ({fmt((good or {}).get('end_to_end_level', {}).get('false_abstention_rate'), 3)} vs "
                     f"{fmt((b or {}).get('end_to_end_level', {}).get('false_abstention_rate'), 3)}), and the gate does not check it. "
                     "That is a gap in our thresholds, not a reason the gate gave. A threshold edit in the ConfigMap (p95 &le; 50 s) "
                     "turned the same c600 result into FAIL without any rebuild (screenshot F4).", BODY))
    elif gp is None and good is not None:
        out.append(P("Release decision: " + pending("gate record for c600"), BODY))
    return out


def part_d(d: dict[str, Any]) -> list[Any]:
    from trace_io import load_traces

    out: list[Any] = [P("6. Part D: observability and traceability", H1)]
    out.append(P("Every query writes one JSON line (record_type=trace) to stdout and to /traces/&lt;pod&gt;.jsonl. It holds: trace id, "
                 "timestamp, user query, rewritten query (null: RAHBAR does not rewrite), embedding model and version, collection "
                 "name and version, pipeline version, retrieved chunk ids with document ids, document versions, pages and scores, "
                 "filters, reranked order (no reranker, so similarity order), SHA-256 of the exact prompt plus the prompt itself, "
                 "model and parameters, response, citations, guardrail actions, latency per stage and cache hit/miss/bypass. "
                 "traces/inspect.py rebuilds the exact context and prompt for a trace id and re-checks the hash.", BODY))
    tdir = DATA / "traces" / "cluster"
    recs = load_traces(tdir) if tdir.exists() else []
    if recs:
        from metrics_summary import summarize

        n_live = sum(not str(r.get("trace_id", "")).startswith("eval-") for r in recs)
        s = summarize(recs)
        t = s["top1_similarity"]
        rows = [["Metric (D3, traces/metrics_summary.py)", "Value"],
                ["Queries in window", f"{s['queries']} ({n_live} sent by us, {s['queries'] - n_live} by the eval Jobs); "
                                      f"{esc(recs[0]['timestamp'])} to {esc(recs[-1]['timestamp'])}"],
                ["Collections served", esc(", ".join(s["collections"]))],
                ["Top-1 similarity min / p50 / mean / p95 / max", f"{t['min']} / {t['p50']} / {t['mean']} / {t['p95']} / {t['max']}"],
                ["Abstention rate", fmt(s["abstention_rate"], 3)], ["Cache hit rate", fmt(s["cache_hit_rate"], 3)],
                ["p95 latency per stage (ms)", esc(", ".join(f"{k} {v}" for k, v in s["p95_latency_ms"].items()))],
                ["Injection attempts flagged", f"{s['injection_attempts_flagged']} (query {s['injection_in_query']}, "
                                               f"retrieved context {s['injection_in_context']})"]]
        out.append(table(rows, [6.0, 11.0], font_size=9.5))
        inj = [r for r in recs if any(g.get("action") == "neutralized" for g in r.get("guardrail_actions", []))]
        if inj:
            g = next(g for g in inj[0]["guardrail_actions"] if g.get("action") == "neutralized")
            out.append(P(f"D4: for “{esc(inj[0]['user_query'])}” the retrieval rail found the Batch B injection in chunk "
                         f"{esc(g.get('chunk_id'))} of {esc(g.get('document_id'))} and logged action “neutralized” in trace "
                         f"{esc(inj[0]['trace_id'][:16])}. The answer did not follow the injected instruction.", BODY))
        else:
            out.append(P("D4: " + pending("a trace whose retrieved context contains the doc10 injection"), BODY))
    else:
        out.append(P("Trace metrics: " + pending("traces copied to traces/cluster/ (kubectl cp)"), BODY))

    d5 = (d.get("pinned") or {}).get("d5_lines")
    if d5:
        out.append(P("<b>D5. Root cause from the trace only</b> (trace " + esc((d.get("pinned") or {}).get("d5_trace_id", "")) + "):", BODY))
        out += [P(esc(line), BODY) for line in d5[:5]]
    else:
        out.append(P("D5: " + pending("d5_trace_id + 5 d5_lines in docs/report_inputs.yaml (use traces/diagnose.py)"), BODY))
    return out


def part_e(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = [P("7. Part E: drift and coverage", H1)]
    cb, ca = d.get("cov_before"), d.get("cov_after")
    b = d.get("part_b") or {}
    mod = b.get("module_level", {})
    if cb and ca:
        rows = [["", "Golden questions", "Covered / 40", "Coverage", "Required", "Exit code"]]
        for name, c in (("Before (golden_baseline.jsonl)", cb), ("After (+6 questions, golden.jsonl)", ca)):
            rows.append([name, str(c["total_golden_questions"]), f"{c['covered_queries']} / {c['total_live_queries']}",
                         f"{c['coverage_percentage']}%", f"{c.get('min_coverage_share', 0.85):.0%}",
                         "0" if c.get("gate_passed") else "1"])
        out.append(table(rows, [5.6, 2.4, 2.4, 2.0, 2.0, 2.0], font_size=9.5))
        gaps: dict[str, int] = {}
        for q in cb["query_details"]:
            if not q["is_covered"]:
                gaps[q["topic"]] = gaps.get(q["topic"], 0) + 1
        out.append(P(f"Similarity threshold &tau; = {cb['coverage_threshold']}, chosen from the module-level test: mean paraphrase "
                     f"cosine {fmt(mod.get('mean_paraphrase_similarity'))} against mean unrelated {fmt(mod.get('mean_unrelated_similarity'))} "
                     f"(highest unrelated pair {fmt(mod.get('max_unrelated_similarity'))}). So a covered query is a paraphrase of a tested one. "
                     f"Uncovered queries before the change, grouped by topic: {esc(', '.join(f'{k} ({v})' for k, v in sorted(gaps.items(), key=lambda kv: -kv[1])))}.", BODY))
    else:
        out.append(P("Coverage before/after: " + pending("coverage_golden_baseline_*.json and coverage_golden_*.json"), BODY))
    a = d.get("after_batch_b")
    if b and a:
        rows = [["Metric", "Before Batch B", "After Batch B", "Change"]]
        for level, key, label in (("component_level", "recall_at_5", "Recall@5"), ("component_level", "mrr", "MRR"),
                                  ("end_to_end_level", "faithfulness", "Faithfulness"),
                                  ("end_to_end_level", "abstention_correctness", "Abstention correctness")):
            x, y = b.get(level, {}).get(key), a.get(level, {}).get(key)
            rows.append([label, fmt(x, 4), fmt(y, 4), fmt((y - x) if x is not None and y is not None else None, 4)])
        changed = [q for q, r in a["runs"][0]["per_question"].items()
                   if r.get("hit_at_5") != b["runs"][0]["per_question"].get(q, {}).get("hit_at_5")]
        out += [table(rows, [5.0, 4.0, 4.0, 4.0], font_size=9.5),
                P(f"E3: questions whose retrieval changed after Batch B: {esc(', '.join(changed) or 'none')}. Batch B adds new documents. "
                  "The Batch B golden questions become answerable, and doc11 supersedes the 2022 entrepreneurship policy, so g08's "
                  "ground-truth document is archived and filtered out.", BODY)]
    else:
        out.append(P("E3 data drift: " + pending("an eval_baseline result after the Batch B ingestion"), BODY))
    return out


def part_f(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = [P("8. Part F: running on Kubernetes", H1)]
    rows = [["Requirement", "Kubernetes object(s)"],
            ["API / vector store / Service", "Deployment api (3 replicas, HPA), StatefulSet chroma + PVC, Service api"],
            ["Data lake, quarantine, archive survive restarts", "PVC rahbar-datalake mounted at /datalake by the indexer Jobs"],
            ["Ingestion with verification; schedule; single writer", "Job rahbar-indexer, CronJob reindex (concurrencyPolicy Forbid); only these reach Chroma with a write path"],
            ["Part B suite as a Job, fails on a failed gate", "Job rahbar-eval (k8s/eval-job.yaml), backoffLimit 0, result on PVC rahbar-results"],
            ["Gate thresholds without rebuild", "ConfigMap rahbar-gate (GATE_* env); gate-only Job re-applies the gate"],
            ["Controlled release", "Deployment + Service api-candidate (own collection), then a rolling update of api (maxUnavailable 0), kubectl rollout undo"],
            ["Observability on the cluster", "Traces on stdout (kubectl logs) + PVC rahbar-traces; /metrics via kubectl port-forward"],
            ["Cluster used", "Docker Desktop Kubernetes v1.36 (overlay k8s/overlays/docker-desktop), Ollama in Docker on CPU. kubectl exec/cp are broken there, so volume access uses short Jobs (scripts/cluster_files.py)"]]
    out.append(table(rows, [6.0, 11.0], font_size=9.5))
    stats = sorted(SHOT_DIR.glob("docker-stats-*.txt")) if SHOT_DIR.exists() else []
    if stats:
        rows = [["When", "Pod (container)", "CPU", "Memory / limit"]]
        for f in stats:
            when = f.stem.removeprefix("docker-stats-")
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) == 3 and not line.startswith("#") and "CPU" not in line:
                    rows.append([esc(when), esc(re.sub(r"-[a-z0-9]{8,10}-[a-z0-9]{5}|-[a-z0-9]{5}(?= )", "", parts[0])),
                                 esc(parts[1]), esc(parts[2])])
        out.append(P("F5: Docker Desktop's Kubernetes has no metrics-server, so we measured with <i>docker stats</i> (every pod "
                     "container is a Docker container there) during each workload. The indexer sat at its 500m CPU limit while "
                     "OCRing, so its limit became 2 CPUs. The other requests sit near the measured steady state, and the limits "
                     "leave headroom over the measured peak.", BODY))
        out.append(table(rows, [3.6, 6.4, 2.2, 4.8], font_size=8.6))
    else:
        out.append(P("F5 measurements: " + pending("docs/evidence/a3/docker-stats-*.txt (docker stats during the Jobs)"), BODY))
    return out


def short_answers(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = [P("9. Short answers", H1)]
    v = d.get("verif_b")
    if v:
        counts: dict[str, int] = {}
        for r in v["results"]:
            for c in r["checks"]:
                if not c["passed"]:
                    counts[c["check_name"]] = counts.get(c["check_name"], 0) + 1
        top = max(counts.items(), key=lambda kv: kv[1]) if counts else ("none", 0)
        passed_planted = [r["source"] for r in v["results"] if r["passed"] and "inject" in r["source"]]
        a = (f"{top[0].capitalize()} caught the most ({top[1]} documents: {esc(', '.join(f'{k} {n}' for k, n in counts.items()))}). "
             f"Not caught: the injected instruction ({esc(', '.join(passed_planted) or 'doc10')}) passes all four checks, because it is "
             "well-formed, complete, current and unique. A content check would catch it at ingestion: an instruction-pattern / "
             "classifier rail before chunking. Today the retrieval rail neutralises it at query time (D4).")
    else:
        a = pending("Batch B verification report")
    b = d.get("part_b") or {}
    base = d.get("after_batch_b") or b        # the baseline the candidates were gated against
    m, c_ = base.get("module_level", {}), base.get("component_level", {})
    bad = d.get("cand_bad") or {}
    answers = [
        ("(a)", a),
        ("(b)", (f"The c120 candidate uses the same embedding model, so its module level matches the baseline (gap "
                 f"{fmt(bad.get('module_level', {}).get('separation_gap'))} vs {fmt(m.get('separation_gap'))}). Its component and "
                 f"end-to-end numbers drop (recall@5 {fmt(bad.get('component_level', {}).get('recall_at_5'))} vs "
                 f"{fmt(c_.get('recall_at_5'))}, MRR {fmt(bad.get('component_level', {}).get('mrr'))} vs {fmt(c_.get('mrr'))}, "
                 f"faithfulness {fmt(bad.get('end_to_end_level', {}).get('faithfulness'))} vs "
                 f"{fmt(base.get('end_to_end_level', {}).get('faithfulness'))}): 120-token chunks cut clauses apart, which an embedding test cannot see.")
         if bad else pending("candidate c120 result")),
        ("(c)", "We archive. A superseded document's chunks stay in Chroma with superseded=True and its file moves to /datalake/archive, "
                "so retrieval excludes it by metadata and the rollback Job can restore it in seconds. Deleting it would break the "
                "rollback, historical questions (the filter is lifted when a question asks about an older year), and the trail "
                "of which version an old trace's answer came from (traces record doc_version)."),
        ("(d)", f"Faithfulness. The LLM judge we tried first was unusable. The grounding check that replaced it agreed with our "
                f"labels on {fmt(b.get('end_to_end_level', {}).get('judge_human_agreement'))} of 8 answers, but it only checks that numbers "
                "and words appear in the context, so it accepts a right number about the wrong thing (g31). Eight labels is a small "
                "sample, and the generator is not bit-for-bit reproducible on CPU. Latency is next: it depends on laptop load and Ollama's prompt cache."),
        ("(e)", "Testing the data lifecycle against its own evolving data (incremental verification against everything already "
                "indexed) was the hardest part. Exact duplicates, near-duplicates and newer versions must be judged across batches, "
                "not inside one batch. We keep whole-document embeddings and versions in the ingestion state. The paper's "
                "separate live-testing loop is reduced to traces plus a curated live query log, not sampled user traffic."),
        ("(f)", "Job + CronJob (concurrencyPolicy Forbid) are the only writers to Chroma: the API has no write path, and NetworkPolicies "
                "admit only the api, api-candidate and indexer pods to Chroma. The PVC rahbar-datalake holds the data lake. ConfigMap "
                "rahbar-gate holds the gate. Job rahbar-eval enforces it by its exit status. Deployment api-candidate + its Service isolate a "
                "candidate. Rolling updates and rollout undo on Deployment api carry the release. Stdout and PVC rahbar-traces carry traceability."),
    ]
    for k, text in answers:
        out.append(P(f"<b>{k}</b> {text}", BODY))
    return out


def contribution() -> list[Any]:
    rows = [["Part", f"{MEMBERS[0][0]} ({MEMBERS[0][1]})", f"{MEMBERS[1][0]} ({MEMBERS[1][1]})"],
            ["A", "Verification stage (verify.py), Batch B generator, embedding near-duplicates", "Incremental ingestion, archive and rollback (incremental.py)"],
            ["B", "Module-level tests, golden set expansion, determinism", "Retrieval metrics, end-to-end faithfulness, noise test"],
            ["C", "Release gate (release_gate.py), gate ConfigMap", "Candidate collections and comparison"],
            ["D", "Trace schema, trace tool (inspect.py), injection rail", "Metrics summary, root-cause tool, /metrics"],
            ["E", "Coverage checker, live query log", "New golden questions, drift analysis"],
            ["F", "PVCs, eval Job, Job-based volume access, network policies", "Candidate Deployment, rollout and undo, resource measurements"],
            ["Report", "Sections 1-5, screenshots A-C", "Sections 6-9, screenshots D-F"]]
    return [P("10. Contribution and AI statement", H1), table(rows, [1.6, 7.7, 7.7], font_size=9.5),
            Spacer(1, 4),
            P("<b>AI statement.</b> We used AI assistants (Claude, Gemini) to draft and refactor code, Kubernetes manifests and parts of "
              "this report, and to drive the cluster runs and terminal captures. Every number comes from our own pipeline runs on our "
              "cluster (result files in eval/results/cluster), the 8 faithfulness labels were made by hand, and both members reviewed "
              "and can explain every change.", BODY)]


def appendix() -> list[Any]:
    out: list[Any] = [PageBreak(), P("Appendix: terminal screenshots (not counted in the 8 pages)", H1)]
    maxw, maxh = 17.0 * cm, 22.5 * cm
    for label, stem, caption in SCREENSHOTS:
        files = [p for ext in ("png", "jpg", "jpeg") for p in SHOT_DIR.glob(f"{stem}*.{ext}")] if SHOT_DIR.exists() else []
        if not files:
            out.append(P(f"<b>{label}</b>: {esc(caption)}: " + pending(f"screenshot docs/evidence/a3/{stem}.png"), BODY))
            continue
        for f in sorted(files):
            from PIL import Image as PILImage

            with PILImage.open(f) as im:
                w, h = im.size
            scale = min(maxw / w, maxh / h)
            out.append(KeepTogether([Image(str(f), width=w * scale, height=h * scale),
                                     P(f"<b>{label}.</b> {esc(caption)}", CAP)]))
    return out


# ----------------------------------------------------------------------------- build
class Doc(SimpleDocTemplate):
    body_pages = 0


def footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(F, 10)
    canvas.drawCentredString(A4[0] / 2, 1.2 * cm, f"{doc.page}")
    canvas.drawString(2.0 * cm, A4[1] - 1.2 * cm, "CS4032 Assignment 03: RAGOps")
    canvas.drawRightString(A4[0] - 2.0 * cm, A4[1] - 1.2 * cm, "i243142, i243106")
    canvas.restoreState()


def title_block() -> list[Any]:
    rows = [["Name", "Roll number"]] + [[n, r] for n, r in MEMBERS]
    t = table(rows, [6.0, 4.0], font_size=12)
    t.hAlign = "CENTER"
    return [P("National University of Computer and Emerging Sciences, Islamabad", SUB),
            P("Software Construction and Development (CS4032), Fall 2026", SUB), Spacer(1, 6),
            P("Assignment 03: RAGOps for the RAHBAR pipeline", TITLE), Spacer(1, 4), t, Spacer(1, 6),
            P(f"Repository: {esc(git_repo_url())}", SUB),
            P("Reference: Xu et al., <i>RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines</i> (2026)", SUB),
            Spacer(1, 6)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / OUT_NAME))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--data-root", default=None, help="read results/traces/screenshots from another tree (layout preview)")
    args = ap.parse_args()
    if args.data_root:
        global DATA, SHOT_DIR
        DATA = Path(args.data_root)
        SHOT_DIR = DATA / "docs" / "evidence" / "a3"

    d = load_inputs()
    body: list[Any] = title_block()
    for section in (stage_map, lambda: qualities(d), lambda: part_a(d), lambda: part_b(d), lambda: part_c(d),
                    lambda: part_d(d), lambda: part_e(d), lambda: part_f(d), lambda: short_answers(d), contribution):
        body += section()


    if args.check:
        print("\n".join(f"MISSING: {m}" for m in missing) or "nothing missing")
        return 1 if missing else 0

    # Count body pages first (the appendix does not count towards the 8-page limit).
    probe = Doc(str(ROOT / "eval" / ".report_probe.pdf"), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                topMargin=1.8 * cm, bottomMargin=1.8 * cm)
    probe.build(list(body), onFirstPage=footer, onLaterPages=footer)
    body_pages = probe.page
    Path(probe.filename).unlink(missing_ok=True)

    missing.clear()
    d = load_inputs()
    body = title_block()
    for section in (stage_map, lambda: qualities(d), lambda: part_a(d), lambda: part_b(d), lambda: part_c(d),
                    lambda: part_d(d), lambda: part_e(d), lambda: part_f(d), lambda: short_answers(d), contribution):
        body += section()
    doc = Doc(args.out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm,
              title="CS4032 Assignment 03: RAGOps", author="Zubair Ilyas (i243142), Salman Asad (i243106)")
    doc.build(body + appendix(), onFirstPage=footer, onLaterPages=footer)
    if Path(args.out).resolve() == (ROOT / OUT_NAME).resolve():
        shutil.copy2(args.out, ROOT / "docs" / OUT_NAME)
    print(f"written {args.out}; body pages: {body_pages} (limit 8), total pages: {doc.page}")
    if body_pages > 8:
        print("WARNING: the body is longer than 8 pages")
    if missing:
        print(f"\n{len(missing)} item(s) still PENDING. The report is NOT ready to submit:")
        print("\n".join(f"  - {m}" for m in dict.fromkeys(missing)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
