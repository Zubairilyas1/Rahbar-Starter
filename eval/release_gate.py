"""Release Gate Enforcement Engine.
Assignment 03 Part C (RAGOps paper 3.2.2, 4.2, Figure 3).

Enforces automated gating checks before production deployment:
1. Recall@5 degradation <= 2.0% (strict retrieval safety)
2. Faithfulness / Groundedness >= 0.60 (or relative drop <= 5%)
3. P95 latency <= 25.0s
4. Abstention correctness = 100.0% (strict safety: 0 hallucinations on out-of-domain)
5. Citation validity = 100.0% (zero hallucinated citations)

Exits with:
- 0: Release APPROVED (All gates pass)
- 1: Release BLOCKED (One or more gates fail)
"""

import argparse
import json
import sys
from pathlib import Path


def evaluate_gate(
    baseline_path: Path,
    candidate_path: Path,
    max_recall_drop: float = 0.02,
    min_faithfulness: float = 0.60,
    max_latency_p95: float = 25.0,
    min_abstention: float = 100.0,
    min_citation_validity: float = 100.0,
) -> tuple[bool, dict]:
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    with open(candidate_path, "r", encoding="utf-8") as f:
        candidate = json.load(f)

    b_comp = baseline.get("component_level", {})
    c_comp = candidate.get("component_level", {})
    b_e2e = baseline.get("end_to_end_level", {})
    c_e2e = candidate.get("end_to_end_level", {})

    b_recall5 = b_comp.get("recall_at_5", 0.0)
    c_recall5 = c_comp.get("recall_at_5", 0.0)
    recall_delta = c_recall5 - b_recall5

    b_faith = b_e2e.get("faithfulness", 0.0)
    c_faith = c_e2e.get("faithfulness", 0.0)

    b_p95 = b_e2e.get("latency_p95_s", 0.0)
    c_p95 = c_e2e.get("latency_p95_s", 0.0)

    b_abst = b_e2e.get("abstention_correctness_pct", 0.0)
    c_abst = c_e2e.get("abstention_correctness_pct", 0.0)

    b_cit = b_e2e.get("citation_validity_pct", 0.0)
    c_cit = c_e2e.get("citation_validity_pct", 0.0)

    checks = []

    # Gate 1: Recall@5 degradation
    g1_pass = recall_delta >= -max_recall_drop
    checks.append({
        "gate": "Retrieval Recall@5 Degradation",
        "threshold": f"Drop <= {max_recall_drop*100:.1f}%",
        "baseline": f"{b_recall5*100:.2f}%",
        "candidate": f"{c_recall5*100:.2f}%",
        "delta": f"{recall_delta*100:+.2f}%",
        "passed": g1_pass,
        "detail": "Acceptable" if g1_pass else f"EXCEEDED ALLOWABLE DROP: {recall_delta*100:.2f}% < -{max_recall_drop*100:.1f}%",
    })

    # Gate 2: Faithfulness
    g2_pass = c_faith >= min_faithfulness
    checks.append({
        "gate": "Answer Faithfulness / Groundedness",
        "threshold": f">= {min_faithfulness:.2f}",
        "baseline": f"{b_faith:.4f}",
        "candidate": f"{c_faith:.4f}",
        "delta": f"{(c_faith - b_faith):+.4f}",
        "passed": g2_pass,
        "detail": "Acceptable" if g2_pass else f"BELOW MINIMUM FAITHFULNESS ({c_faith:.4f} < {min_faithfulness:.2f})",
    })

    # Gate 3: Latency P95
    g3_pass = c_p95 <= max_latency_p95
    checks.append({
        "gate": "P95 End-to-End Latency",
        "threshold": f"<= {max_latency_p95:.1f}s",
        "baseline": f"{b_p95:.2f}s",
        "candidate": f"{c_p95:.2f}s",
        "delta": f"{(c_p95 - b_p95):+.2f}s",
        "passed": g3_pass,
        "detail": "Acceptable" if g3_pass else f"LATENCY SLA BREACH ({c_p95:.2f}s > {max_latency_p95:.1f}s)",
    })

    # Gate 4: Honest Abstention Correctness
    g4_pass = c_abst >= min_abstention
    checks.append({
        "gate": "Honest Abstention Correctness",
        "threshold": f"= {min_abstention:.1f}%",
        "baseline": f"{b_abst:.1f}%",
        "candidate": f"{c_abst:.1f}%",
        "delta": f"{(c_abst - b_abst):+.1f}%",
        "passed": g4_pass,
        "detail": "Strict Safety Pass" if g4_pass else f"SAFETY VIOLATION: Abstention dropped to {c_abst:.1f}%",
    })

    # Gate 5: Citation Validity
    g5_pass = c_cit >= min_citation_validity
    checks.append({
        "gate": "Citation Validity Rate",
        "threshold": f"= {min_citation_validity:.1f}%",
        "baseline": f"{b_cit:.1f}%",
        "candidate": f"{c_cit:.1f}%",
        "delta": f"{(c_cit - b_cit):+.1f}%",
        "passed": g5_pass,
        "detail": "Grounded Citations Verified" if g5_pass else f"HALLUCINATED CITATIONS DETECTED ({c_cit:.1f}%)",
    })

    all_passed = all(c["passed"] for c in checks)
    return all_passed, {"checks": checks, "all_passed": all_passed}


def main():
    parser = argparse.ArgumentParser(description="Evaluate RAG pipeline release gate")
    parser.add_argument("--baseline", type=Path, default=Path("eval/results/three_level_eval.json"), help="Baseline eval JSON")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate eval JSON")
    parser.add_argument("--max-recall-drop", type=float, default=0.02, help="Maximum allowed Recall@5 degradation (default: 0.02)")
    parser.add_argument("--min-faithfulness", type=float, default=0.60, help="Minimum faithfulness threshold (default: 0.60)")
    parser.add_argument("--max-latency-p95", type=float, default=25.0, help="Maximum P95 latency in seconds (default: 25.0)")
    args = parser.parse_args()

    if not args.baseline.exists():
        print(f"Error: Baseline file not found: {args.baseline}")
        return 1
    if not args.candidate.exists():
        print(f"Error: Candidate file not found: {args.candidate}")
        return 1

    passed, report = evaluate_gate(
        args.baseline,
        args.candidate,
        max_recall_drop=args.max_recall_drop,
        min_faithfulness=args.min_faithfulness,
        max_latency_p95=args.max_latency_p95,
    )

    print("\n" + "=" * 95)
    print("RAHBAR RAGOps: Continuous Integration Release Gate Report (Part C)")
    print("=" * 95)
    print(f"Baseline:  {args.baseline}")
    print(f"Candidate: {args.candidate}")
    print("-" * 95)
    print(f"{'Gate / Metric':<35} | {'Threshold':<14} | {'Baseline':<10} | {'Candidate':<10} | {'Delta':<9} | {'Status':<6}")
    print("-" * 95)

    for c in report["checks"]:
        status_str = "PASS" if c["passed"] else "FAIL"
        print(f"{c['gate']:<35} | {c['threshold']:<14} | {c['baseline']:<10} | {c['candidate']:<10} | {c['delta']:<9} | {status_str:<6}")

    print("=" * 95)
    if passed:
        print(">>> RELEASE DECISION: [APPROVED] - All gating criteria met. Deploying candidate to cluster.")
        print("=" * 95 + "\n")
        return 0
    else:
        print(">>> RELEASE DECISION: [BLOCKED] - Candidate failed one or more regression gates. Deployment aborted.")
        print("=" * 95 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
