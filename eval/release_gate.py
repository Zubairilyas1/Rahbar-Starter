#!/usr/bin/env python3
"""Release gate (Assignment 03 Part C2, RAGOps paper 4.2.5-4.2.6).

Compares a candidate's evaluation result file with the baseline's and exits
0 (RELEASE) or 1 (REJECT). Both files are produced by eval/test_three_levels.py.

    python eval/release_gate.py --baseline eval/results/latest_baseline.json \
                                --candidate eval/results/latest_candidate.json

Threshold precedence: command-line flag > environment variable GATE_<KEY>
(the `rahbar-gate` ConfigMap on the cluster) > eval/gate_thresholds.yaml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
KEYS = ("max_recall5_drop", "min_faithfulness", "min_abstention_delta",
        "min_citation_validity", "max_latency_p95_s")


def load_thresholds(path: Path, overrides: dict[str, float | None]) -> tuple[dict[str, float], dict[str, str]]:
    values: dict[str, float] = {}
    source: dict[str, str] = {}
    if path.exists():
        for k, v in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
            if k in KEYS:
                values[k], source[k] = float(v), path.name
    for k in KEYS:
        env = os.environ.get(f"GATE_{k.upper()}")
        if env not in (None, ""):
            values[k], source[k] = float(env), f"env GATE_{k.upper()}"
        if overrides.get(k) is not None:
            values[k], source[k] = float(overrides[k]), "cli"  # type: ignore[arg-type]
    missing = [k for k in KEYS if k not in values]
    if missing:
        raise SystemExit(f"gate thresholds missing: {missing}")
    return values, source


def _get(result: dict[str, Any], level: str, key: str) -> float | None:
    v = result.get(level, {}).get(key)
    return None if v is None else float(v)


def evaluate(baseline: dict[str, Any], candidate: dict[str, Any], th: dict[str, float]) -> list[dict[str, Any]]:
    b_r5, c_r5 = _get(baseline, "component_level", "recall_at_5"), _get(candidate, "component_level", "recall_at_5")
    c_faith = _get(candidate, "end_to_end_level", "faithfulness")
    b_abs = _get(baseline, "end_to_end_level", "abstention_correctness")
    c_abs = _get(candidate, "end_to_end_level", "abstention_correctness")
    c_cit = _get(candidate, "end_to_end_level", "citation_validity")
    c_p95 = _get(candidate, "end_to_end_level", "latency_p95_s")

    def check(name: str, rule: str, base: Any, cand: Any, ok: bool) -> dict[str, Any]:
        return {"check": name, "rule": rule, "baseline": base, "candidate": cand, "passed": bool(ok)}

    return [
        check("recall@5 drop", f"candidate >= baseline - {th['max_recall5_drop']:.2f}", b_r5, c_r5,
              c_r5 is not None and b_r5 is not None and c_r5 >= b_r5 - th["max_recall5_drop"] - 1e-9),
        check("faithfulness", f">= {th['min_faithfulness']:.2f}",
              _get(baseline, "end_to_end_level", "faithfulness"), c_faith,
              c_faith is not None and c_faith >= th["min_faithfulness"]),
        check("abstention correctness", f">= baseline + {th['min_abstention_delta']:.2f}", b_abs, c_abs,
              c_abs is not None and b_abs is not None and c_abs >= b_abs + th["min_abstention_delta"] - 1e-9),
        check("citation validity", f">= {th['min_citation_validity']:.2f}",
              _get(baseline, "end_to_end_level", "citation_validity"), c_cit,
              c_cit is not None and c_cit >= th["min_citation_validity"]),
        check("latency p95 (s)", f"<= {th['max_latency_p95_s']:.1f}",
              _get(baseline, "end_to_end_level", "latency_p95_s"), c_p95,
              c_p95 is not None and c_p95 <= th["max_latency_p95_s"]),
    ]


def _f(v: Any) -> str:
    return "n/a" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply the release gate to a candidate evaluation result")
    ap.add_argument("--baseline", default=os.environ.get("GATE_BASELINE", str(HERE / "results" / "latest_baseline.json")))
    ap.add_argument("--candidate", default=os.environ.get("GATE_CANDIDATE", str(HERE / "results" / "latest_candidate.json")))
    ap.add_argument("--thresholds", default=os.environ.get("GATE_THRESHOLDS_FILE", str(HERE / "gate_thresholds.yaml")))
    ap.add_argument("--out-dir", default=os.environ.get("RESULTS_DIR", str(HERE / "results")))
    for k in KEYS:
        ap.add_argument(f"--{k.replace('_', '-')}", type=float, default=None)
    args = ap.parse_args()

    th, src = load_thresholds(Path(args.thresholds), {k: getattr(args, k) for k in KEYS})
    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(f"GATE ERROR: {exc}", file=sys.stderr)
        return 2

    checks = evaluate(baseline, candidate, th)
    passed = all(c["passed"] for c in checks)

    bt, ct = baseline.get("target", {}), candidate.get("target", {})
    print("=" * 96)
    print("RAHBAR release gate (Part C2)")
    print(f"baseline : {args.baseline}  [{bt.get('collection')} | {baseline.get('timestamp')}]")
    print(f"candidate: {args.candidate}  [{ct.get('collection')} | {candidate.get('timestamp')}]")
    print("thresholds: " + ", ".join(f"{k}={th[k]} ({src[k]})" for k in KEYS))
    print("-" * 96)
    print(f"{'check':<24} {'rule':<34} {'baseline':>10} {'candidate':>10}  result")
    for c in checks:
        print(f"{c['check']:<24} {c['rule']:<34} {_f(c['baseline']):>10} {_f(c['candidate']):>10}  "
              f"{'PASS' if c['passed'] else 'FAIL'}")
    print("-" * 96)
    decision = "RELEASE" if passed else "REJECT"
    failed = [c["check"] for c in checks if not c["passed"]]
    print(f"GATE RESULT: {'PASS' if passed else 'FAIL'} -> {decision}" + (f"  (failed: {', '.join(failed)})" if failed else ""))
    print("=" * 96)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    record = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "decision": decision,
              "passed": passed, "thresholds": th, "threshold_source": src, "checks": checks,
              "baseline": args.baseline, "candidate": args.candidate,
              "candidate_label": candidate.get("label"), "candidate_collection": ct.get("collection")}
    gate_file = out_dir / f"gate_{candidate.get('label', 'candidate')}_{stamp}.json"
    gate_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"gate record: {gate_file}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
