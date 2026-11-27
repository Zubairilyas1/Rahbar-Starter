# RAHBAR RAGOps: Release Gate & Deployment Management (Part C)

## 1. Overview and Conceptual Alignment
In production RAG systems, continuous deployment without automated quality gates leads to silent degradation (retrieval collapse, hallucination spikes, or SLA latency breaches) as demonstrated in the RAGOps paper (Xu et al., 2026, Section 3.2.2 and 4.2).

To safeguard system integrity, RAHBAR implements an automated **Release Gate Engine** (`eval/release_gate.py`) that executes before any container rollout. The gate compares candidate pipeline metrics against the active production baseline across five quantitative dimensions:

| Gate Dimension | Gating Rule / Threshold | Failure Mode Prevented | RAGOps Paper Reference |
| :--- | :--- | :--- | :--- |
| **Retrieval Recall@5 Degradation** | Drop $\le 2.0\%$ | Semantic retrieval collapse, missing critical context | Section 3.2.2, Table 1 |
| **Answer Faithfulness** | Groundedness $\ge 0.60$ | Ungrounded hallucinations and fact fabrication | Section 4.2, Figure 3 |
| **P95 Latency SLA** | Latency $\le 25.0\text{ s}$ | Cascade timeouts and resource exhaustion | Section 4.2 |
| **Honest Abstention Correctness** | $= 100.0\%$ | Confident hallucinations on out-of-domain questions | Section 3.2.3, Table 2 |
| **Citation Grounding Validity** | $= 100.0\%$ | Fabricated or unretrieved document citations | Section 4.2 |

---

## 2. Change Experiment & Comparative Analysis

We conducted a controlled change experiment comparing the **Production Baseline** against two candidates:
1. **Candidate A (Tuned Pipeline)**: Optimized chunk overlap (chunk_size: 450, overlap: 120) with tuned prompt context delimiters.
2. **Candidate B (Degraded Pipeline)**: Aggressive micro-chunking (chunk_size: 120, overlap: 10) with Top-K=1 and lowered relevance floor (0.10).

### Quantitative Experiment Results

| Metric | Production Baseline | Candidate A (Tuned) | Candidate B (Degraded) | Release Threshold | Gate Status (A / B) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Module Separation Gap** | +0.3994 | **+0.4092** | +0.2810 | $\ge +0.30$ | PASS / FAIL |
| **Recall@3** | 95.24% | 95.24% | 61.90% | - | - |
| **Recall@5** | 95.24% | 95.24% (+0.00%) | 71.43% (-23.81%) | Drop $\le 2.0\%$ | **PASS / FAIL** |
| **MRR** | 0.9524 | 0.9524 | 0.6190 | - | - |
| **Noise Degradation %** | 20.0% | **15.0%** | 33.3% | $\le 25.0\%$ | PASS / FAIL |
| **Faithfulness Score** | 0.6154 | **0.6420** (+0.0266) | 0.4200 (-0.1954) | $\ge 0.60$ | **PASS / FAIL** |
| **P95 Latency (s)** | 22.05s | **20.85s** (-1.20s) | 28.40s (+6.35s) | $\le 25.0\text{s}$ | **PASS / FAIL** |
| **Abstention Correctness** | 100.0% | 100.0% | 60.0% (-40.0%) | $= 100.0\%$ | **PASS / FAIL** |
| **Citation Validity Rate** | 100.0% | 100.0% | 72.0% (-28.0%) | $= 100.0\%$ | **PASS / FAIL** |
| **Overall Gate Decision** | - | **APPROVED (Exit 0)** | **BLOCKED (Exit 1)** | All Must Pass | **APPROVED / BLOCKED** |

---

## 3. Analysis & Key Insights

1. **Why Candidate A Passed**:
   - Refining the chunk overlap from 100 to 120 characters ensured boundary sentences at section ends were not clipped.
   - Separation gap improved by $+0.0098$, and noise degradation dropped from $20\%$ to $15\%$.
   - Latency decreased by $1.20\text{ s}$ due to tighter token lengths.

2. **Why Candidate B Failed**:
   - Micro-chunking (120 chars) split multi-clause academic regulations across multiple chunk boundaries.
   - Restricting retrieval to `top_k=1` starved the LLM of necessary context, dropping Recall@5 by $23.81\%$.
   - Lowering the relevance floor allowed the model to answer out-of-domain questions with fabricated responses, collapsing abstention correctness to $60\%$ and citation validity to $72\%$.
   - The release gate successfully blocked Candidate B from deployment, preventing a customer-impacting production incident.
