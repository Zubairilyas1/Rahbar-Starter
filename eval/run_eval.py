#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

Given: talking to the API, reading the golden set, writing results.json, the exit
code. Yours: the four functions marked STARTER-TODO. They are the evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None

    top_k = retrieved[:k]
    hits = 0

    for rel in relevant:
        target_source = rel.get("source", "").strip().lower()
        target_section = rel.get("section", "").strip().lower()

        matched = False
        for ret in top_k:
            ret_source = str(ret.get("source", "")).strip().lower()
            ret_section = str(ret.get("section", "")).strip().lower()

            if target_source in ret_source or ret_source in target_source:
                if not target_section or target_section in ret_section or ret_section in target_section:
                    matched = True
                    break

        if matched:
            hits += 1

    return hits / len(relevant)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    citations = response.get("citations", [])
    if not citations:
        return None

    retrieved = response.get("retrieved", [])
    if not retrieved:
        return 0.0

    valid_count = 0
    for cite in citations:
        c_src = str(cite.get("source", "")).strip().lower()
        c_sec = str(cite.get("section", "")).strip().lower()
        c_page = cite.get("page")

        matched = False
        for ret in retrieved:
            r_src = str(ret.get("source", "")).strip().lower()
            r_sec = str(ret.get("section", "")).strip().lower()
            r_page = ret.get("page")

            if c_src in r_src or r_src in c_src:
                sec_match = bool(c_sec and (c_sec in r_sec or r_sec in c_sec))
                page_match = bool(c_page is not None and r_page is not None and c_page == r_page)
                if sec_match or page_match:
                    matched = True
                    break

        if matched:
            valid_count += 1

    return valid_count / len(citations)


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    r3_scores: list[float] = []
    r5_scores: list[float] = []
    r5_by_type: dict[str, list[float]] = {}
    citation_scores: list[float] = []
    abstention_checks: list[bool] = []

    for row in rows:
        resp = row.get("response", {})
        retrieved = resp.get("retrieved", [])
        relevant = row.get("relevant", [])
        q_type = row.get("type", "ordinary")
        must_abstain = row.get("must_abstain", False)

        # Recall computation
        r3 = recall_at_k(relevant, retrieved, 3)
        r5 = recall_at_k(relevant, retrieved, 5)

        if r3 is not None:
            r3_scores.append(r3)
        if r5 is not None:
            r5_scores.append(r5)
            r5_by_type.setdefault(q_type, []).append(r5)

        # Citation validity
        c_valid = citation_validity(resp)
        if c_valid is not None:
            citation_scores.append(c_valid)

        # Abstention correctness
        if must_abstain:
            abstention_checks.append(not resp.get("answered_from_context", True))

    mean_r3 = round(sum(r3_scores) / len(r3_scores), 4) if r3_scores else 0.0
    mean_r5 = round(sum(r5_scores) / len(r5_scores), 4) if r5_scores else 0.0
    mean_cit = round(sum(citation_scores) / len(citation_scores), 4) if citation_scores else 1.0
    mean_abstain = (
        round(sum(1.0 for a in abstention_checks if a) / len(abstention_checks), 4)
        if abstention_checks
        else 1.0
    )

    type_summary = {
        t: round(sum(scores) / len(scores), 4)
        for t, scores in r5_by_type.items()
    }

    return {
        "recall@3": mean_r3,
        "recall@5": mean_r5,
        "recall@5_by_type": type_summary,
        "citation_validity": mean_cit,
        "abstention_correctness": mean_abstain,
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures: list[str] = []

    # Gate 1: Recall regression check against baseline
    current_r5 = results.get("recall@5", 0.0)
    if baseline:
        base_r5 = baseline.get("recall@5", 0.0)
        drop = base_r5 - current_r5
        if drop > MAX_RECALL5_DROP:
            failures.append(
                f"Recall@5 dropped by {drop:.4f} (from {base_r5:.4f} to {current_r5:.4f}), "
                f"exceeding max tolerance of {MAX_RECALL5_DROP}"
            )

    # Gate 2: Citation validity floor
    cit_val = results.get("citation_validity", 1.0)
    if cit_val < MIN_CITATION_VALIDITY:
        failures.append(
            f"Citation validity {cit_val:.4f} is below minimum required {MIN_CITATION_VALIDITY}"
        )

    # Gate 3: Abstention correctness
    abstain_rate = results.get("abstention_correctness", 1.0)
    if abstain_rate < REQUIRED_ABSTENTION:
        failures.append(
            f"Abstention correctness {abstain_rate:.4f} failed required floor of {REQUIRED_ABSTENTION}"
        )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    results = summarise(rows)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else None
    failures = gate(results, baseline)

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
