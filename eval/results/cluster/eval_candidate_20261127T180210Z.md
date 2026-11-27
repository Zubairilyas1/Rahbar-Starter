# RAHBAR evaluation: candidate (2026-11-27T18:17:12Z)

Target: `http://api-candidate:8000`, collection `rahbar_c600` (c600-o100), embed `nomic-embed-text` v1.5, top_k 5, seed 42, golden 32 questions.

| Level | Metric | Run 1 | Run 2 | Delta |
|---|---|---|---|---|
| Module | Mean cosine, paraphrase pairs | 0.7958 | - | - |
| Module | Mean cosine, unrelated pairs | 0.3963 | - | - |
| Module | Gap (paraphrase - unrelated) | 0.3994 | - | - |
| Module | Embedding time per chunk (ms) | 250.6 | - | - |
| Module | Determinism: max |diff| | 0.00e+00 | - | - |
| Component | Recall@3 | 0.9231 | - | - |
| Component | Recall@5 | 0.9231 | - | - |
| Component | MRR | 0.7885 | - | - |
| Component | nDCG@5 | 0.8066 | - | - |
| Component | Recall@5 with typos | 0.8846 | - | - |
| Component |   change | -0.0385 | - | - |
| Component |   MRR change with typos | -0.0481 | - | - |
| End-to-end | Faithfulness (grounding judge) | 1.0000 | - | - |
| End-to-end | Judge/human agreement | 1.0000 | - | - |
| End-to-end | Abstention correctness | 1.0000 | - | - |
| End-to-end | False abstention (answerable) | 0.3846 | - | - |
| End-to-end | Citation validity | 1.0000 | - | - |
| End-to-end | Latency p50 (s) | 25.80 | - | - |
| End-to-end | Latency p95 (s) | 55.19 | - | - |
