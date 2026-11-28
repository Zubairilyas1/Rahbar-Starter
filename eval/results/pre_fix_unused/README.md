# Pre-fix results (not used in the report)

These files came from the first version of the Assignment 03 scripts. They are not
used for any number in the report, for these reasons:

- `three_level_eval.json`: written by the old suite. That suite silently swapped in
  mock retrieval and mock embeddings whenever a call failed. Its "stochasticity"
  ran only the embedding module, and with two *different* seeds (42 vs 43).
- `coverage_report*.json`, `verification_report_*.json`: written by older versions
  of the coverage and verification code. The thresholds and the near-duplicate
  method (Jaccard, not embeddings) differ from the current pipeline.
- `live_traces_a3_v1.jsonl`: 4 trace records in the old format. They carry no
  document versions and use a truncated prompt.

Two candidate result files (`candidate_tuned_eval.json`, `candidate_degraded_eval.json`)
were deleted rather than kept here. A script wrote them from hard-coded numbers, not
from runs of the pipeline.

Every reported number now comes from `eval/test_three_levels.py`,
`eval/release_gate.py`, `eval/check_coverage.py` and the indexer Jobs. Those runs
are copied from the cluster volumes into `eval/results/cluster/` and `traces/cluster/`.
