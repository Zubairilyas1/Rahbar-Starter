# Drift and coverage checking (Assignment 03 Part E)

**E1, live query log.** `eval/live_queries.jsonl` has 40 user-style queries: 28 in the
golden set's domain (grading, attendance, fees, academic rules, entrepreneurship
policy) and 12 on topics the corpus and tests do not cover. Each query has a
`topic` label used for grouping.

**E2, coverage.** `eval/check_coverage.py` embeds every live query and golden question
with the pinned model (`nomic-embed-text`). For each live query it finds the most
similar golden question. A query counts as covered when that cosine is at least
the threshold τ (default 0.75, `--threshold`).

τ is set from the module-level test (Part B). Paraphrase pairs score clearly higher
than unrelated pairs. τ is placed below the mean paraphrase similarity and well above
the highest unrelated-pair similarity, so "covered" means "a paraphrase of something
we test". The report quotes the measured means. The script prints the share of
covered queries and lists the uncovered ones grouped by topic. It exits **1** when the
share is below `--min-coverage` (default 0.85, the paper's 4.2.7 example) and 2 when
it cannot embed.

**E3, data drift.** Ingest Batch B (`k8s/jobs/ingest-batch-b-job.yaml`), then re-run the
baseline evaluation (`k8s/jobs/eval-baseline-job.yaml`) and compare it with the
pre-Batch-B result file. The expected, explainable change: doc11 supersedes the 2022
entrepreneurship policy, so golden question g08's ground-truth document is archived
and excluded by the `superseded=False` filter. Retrieval for g08 now returns doc11,
and its recall and answer change.

**E4, close the gap.** Golden questions added from the uncovered topics are in
`eval/golden.jsonl`. The 26-question set is kept as `eval/golden_baseline.jsonl` for the
"before" run:

```
python eval/check_coverage.py --golden eval/golden_baseline.jsonl    # before
python eval/check_coverage.py --golden eval/golden.jsonl             # after
```

Questions about topics the corpus does not contain are written as `must_abstain`
cases. Covering such a topic in the tests means checking that RAHBAR abstains on it,
not inventing an answer.

The reports are written to `eval/results/coverage_<golden>_<timestamp>.json`.
