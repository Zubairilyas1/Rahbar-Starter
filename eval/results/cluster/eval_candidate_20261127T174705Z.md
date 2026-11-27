# RAHBAR evaluation: candidate (2026-11-27T18:00:19Z)

Target: `http://api-candidate:8000`, collection `rahbar_c120` (c120-o0), embed `nomic-embed-text` v1.5, top_k 5, seed 42, golden 32 questions.

| Level | Metric | Run 1 | Run 2 | Delta |
|---|---|---|---|---|
| Module | Mean cosine, paraphrase pairs | 0.7958 | - | - |
| Module | Mean cosine, unrelated pairs | 0.3963 | - | - |
| Module | Gap (paraphrase - unrelated) | 0.3994 | - | - |
| Module | Embedding time per chunk (ms) | 127.6 | - | - |
| Module | Determinism: max |diff| | 0.00e+00 | - | - |
| Component | Recall@3 | 0.7308 | - | - |
| Component | Recall@5 | 0.8846 | - | - |
| Component | MRR | 0.6333 | - | - |
| Component | nDCG@5 | 0.6946 | - | - |
| Component | Recall@5 with typos | 0.8846 | - | - |
| Component |   change | +0.0000 | - | - |
| Component |   MRR change with typos | +0.0846 | - | - |
| End-to-end | Faithfulness (grounding judge) | 0.9048 | - | - |
| End-to-end | Judge/human agreement | 1.0000 | - | - |
| End-to-end | Abstention correctness | 1.0000 | - | - |
| End-to-end | False abstention (answerable) | 0.1923 | - | - |
| End-to-end | Citation validity | 1.0000 | - | - |
| End-to-end | Latency p50 (s) | 22.18 | - | - |
| End-to-end | Latency p95 (s) | 46.37 | - | - |
