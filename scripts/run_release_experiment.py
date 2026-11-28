#!/usr/bin/env python3
"""Part C1/C2 outside the cluster: evaluate baseline and candidate, then apply the gate.

On the cluster the same steps are the eval Jobs (see README, Part C and F3). This
script is the local equivalent for two port-forwarded Services:

    kubectl port-forward svc/api 8000:8000 -n rahbar
    kubectl port-forward svc/api-candidate 8001:8000 -n rahbar
    python scripts/run_release_experiment.py --baseline-url http://localhost:8000 \
                                             --candidate-url http://localhost:8001

Every number comes from real runs of eval/test_three_levels.py. Nothing is hard-coded.
Exit code: the gate's (0 release, 1 reject, 2 the suite could not measure).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str]) -> int:
    print("\n$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-url", default="http://localhost:8000")
    ap.add_argument("--candidate-url", required=True)
    ap.add_argument("--candidate-label", default="candidate")
    ap.add_argument("--results-dir", default="eval/results")
    ap.add_argument("--skip-baseline", action="store_true", help="reuse results-dir/latest_baseline.json")
    args = ap.parse_args()

    suite = [sys.executable, "eval/test_three_levels.py", "--results-dir", args.results_dir]
    if not args.skip_baseline:
        rc = run(suite + ["--api-url", args.baseline_url, "--label", "baseline"])
        if rc:
            return rc
    rc = run(suite + ["--api-url", args.candidate_url, "--label", args.candidate_label])
    if rc:
        return rc
    return run([sys.executable, "eval/release_gate.py",
                "--baseline", f"{args.results_dir}/latest_baseline.json",
                "--candidate", f"{args.results_dir}/latest_{args.candidate_label}.json",
                "--out-dir", args.results_dir])


if __name__ == "__main__":
    sys.exit(main())
