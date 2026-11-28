# Change experiment and release gate (Assignment 03 Part C)

## The change (C1)

One change only: **chunk size and overlap**. Each setting gets its own collection,
built by its own indexer Job from the same data lake:

| Pipeline | Collection | Chunk / overlap | Built by | Served by |
|---|---|---|---|---|
| Baseline | `rahbar` | 400 / 50 | `k8s/base/indexer-job.yaml` | Deployment `api` |
| Candidate (good) | `rahbar_c600` | 600 / 100 | `k8s/release/index-candidate-c600-job.yaml` | Deployment `api-candidate` (`k8s/release/api-candidate-c600.yaml`) |
| Candidate (deliberately bad) | `rahbar_c120` | 120 / 0 | `k8s/release/index-candidate-c120-job.yaml` | Deployment `api-candidate` (`k8s/release/api-candidate-c120.yaml`) |

Everything else is identical: embedding model (`nomic-embed-text` v1.5), top_k 5,
relevance floor 0.50, prompt, temperature 0.2, seed 42. The Part B suite
(`eval/test_three_levels.py`) runs on each pipeline, and the comparison covers all
three levels. The module level should not move (same embedding model). Chunking
shows up at the component level (recall, MRR, nDCG) and at the end-to-end level
(faithfulness, abstention, latency).

## The gate (C2)

`eval/release_gate.py` reads the baseline and candidate result files and exits 0
(RELEASE) or 1 (REJECT). Thresholds are read in this order: CLI flag, then
`GATE_*` environment variables (ConfigMap `rahbar-gate` on the cluster), then
`eval/gate_thresholds.yaml`.

| Check | Rule | Why this value |
|---|---|---|
| recall@5 | candidate >= baseline - 0.02 | The assignment's example: a release may not lose more than 2 points of retrieval |
| faithfulness | >= 0.80 | Set after the baseline run: the baseline's judged faithfulness minus a margin for judge noise (see the judge/human agreement). Revisit with the measured value |
| abstention correctness | >= baseline | Answering an unanswerable question is the worst failure for an advisory assistant |
| citation validity | >= 0.95 | Same floor as the Assignment 02 CI gate |
| p95 latency | <= 30 s | Measured p95 on the local cluster (host Ollama on CPU) plus headroom; one generation timeout is 30 s |

Each run writes `gate_<label>_<timestamp>.json` next to the result files. The record
holds the decision, the thresholds and where each threshold came from.

## Where the numbers are

Result files from the cluster runs are copied into `eval/results/cluster/`
(`eval_baseline_*.json`, `eval_candidate_*.json`, `gate_*.json`). The report's Part C
table and the release decision use those files only.
