# Assignment 03 screenshots (report appendix)

Save each terminal screenshot here under the exact file name below (PNG). It must show
the command and its full output, uncropped, from our own cluster. `scripts/build_report.py`
embeds them, labelled, in the appendix and reports any that are missing.

| Label | File | What it must show | Command (see k8s/README.md) |
|---|---|---|---|
| A1 | `A1-batch-b-verification.png` | Verification report for Batch B: pass/fail per check with reasons (ingest-batch-b Job logs) | `kubectl logs job/rahbar-ingest-batch-b -n rahbar` |
| A2 | `A2-unchanged-rerun-zero-chunks.png` | Second ingestion run on an unchanged corpus: 0 chunks embedded | `kubectl logs job/rerun-unchanged -n rahbar` |
| B | `B-eval-summary.png` | Evaluation summary with all three levels (eval Job logs) | `kubectl logs job/rahbar-eval-baseline -n rahbar` |
| C1 | `C-gate-fail.png` | Release gate FAILING for the bad candidate (rahbar_c120) | `kubectl logs job/rahbar-eval -n rahbar  (c120 candidate)` |
| C2 | `C-gate-pass.png` | Release gate PASSING for the good candidate (rahbar_c600) | `kubectl logs job/rahbar-eval -n rahbar  (c600 candidate)` |
| D1 | `D1-full-trace.png` | One full trace record | `python traces/inspect.py <id> --path traces/cluster --json` |
| D2 | `D2-trace-tool.png` | Trace tool rebuilding the exact context and prompt for a trace id | `python traces/inspect.py <id> --path traces/cluster` |
| E1 | `E-coverage-before.png` | Coverage output before adding the new golden questions | `python eval/check_coverage.py --golden eval/golden_baseline.jsonl` |
| E2 | `E-coverage-after.png` | Coverage output after adding the new golden questions | `python eval/check_coverage.py --golden eval/golden.jsonl` |
| F1 | `F-get-all.png` | kubectl get all,pvc,configmap,cronjob,job -n rahbar | `kubectl get all,pvc,configmap,cronjob,job -n rahbar` |
| F2 | `F-ingestion-job-logs.png` | Logs of a completed ingestion Job | `kubectl logs job/rahbar-indexer -n rahbar` |
| F3 | `F-eval-job-logs.png` | Logs of a completed evaluation Job | `kubectl logs job/rahbar-eval -n rahbar` |
| F4 | `F-configmap-gate-change.png` | Gate result changing after a ConfigMap edit (no image rebuild) | `gate-only Job before/after kubectl patch configmap rahbar-gate` |
| F5 | `F-rollout-status.png` | kubectl rollout status for the gated release | `kubectl rollout status deployment/api -n rahbar` |
| F6 | `F-rollout-undo-trace.png` | kubectl rollout undo, then a trace showing the previous collection and embedding version | `kubectl rollout undo deployment/api -n rahbar + new trace` |

Also save `kubectl top pods -n rahbar --containers` output, taken while the eval and indexer
Jobs run, as `kubectl-top-under-eval.txt` and `kubectl-top-indexer.txt` (F5).
