#!/usr/bin/env python3
"""Entry point of the evaluation Kubernetes Job (Assignment 03 F2/F3).

Environment (from the eval Job manifest and the `rahbar-gate` ConfigMap):
  EVAL_TARGET_URL  API Service to test, e.g. http://api:8000 or http://api-candidate:8000
  EVAL_LABEL       baseline | candidate | <name>; result files are named after it
  EVAL_MODE        full      run the Part B suite, then the gate (unless label=baseline)
                   gate-only re-apply the gate to the latest result already on the volume
                             (shows a ConfigMap threshold edit changing the outcome
                             without re-running or rebuilding anything)
  RESULTS_DIR      the results PersistentVolumeClaim mount (default /results)

Exit status: 0 when the suite ran and the gate passed (or label=baseline),
1 when the gate failed, 2 when the suite could not measure. A failed gate
therefore fails the Job, which is what blocks the rollout.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    label = os.environ.get("EVAL_LABEL", "candidate")
    mode = os.environ.get("EVAL_MODE", "full")
    results = Path(os.environ.get("RESULTS_DIR", "/results"))
    py = sys.executable

    print(f"[eval-job] label={label} mode={mode} target={os.environ.get('EVAL_TARGET_URL')} results={results}",
          flush=True)

    if mode != "gate-only":
        rc = subprocess.call([py, str(HERE / "test_three_levels.py"), "--label", label,
                              "--results-dir", str(results)])
        if rc != 0:
            print(f"[eval-job] suite failed with exit code {rc}", flush=True)
            return rc

    if label == "baseline":
        print("[eval-job] baseline recorded; no gate to apply", flush=True)
        return 0

    rc = subprocess.call([py, str(HERE / "release_gate.py"),
                          "--baseline", str(results / "latest_baseline.json"),
                          "--candidate", str(results / f"latest_{label}.json"),
                          "--out-dir", str(results)])
    print(f"[eval-job] gate exit code {rc} -> {'RELEASE' if rc == 0 else 'REJECT'}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
