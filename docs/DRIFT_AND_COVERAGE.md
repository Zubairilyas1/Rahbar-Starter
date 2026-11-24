# RAHBAR RAGOps: Evaluation Dataset Coverage & Drift Analysis (Part E)

## 1. Overview and Problem Formulation
In real-world RAG systems, user query distributions continuously evolve as new semesters begin, new campus facilities open, and institutional policies update (Xu et al., 2026, Section 3.2.3 & 5.1). A static evaluation suite suffers from **Evaluation Drift**: the test set no longer represents the real-world traffic distribution, leading to false confidence in system quality.

To solve this, RAHBAR provides an automated **Coverage & Drift Checking Engine** (`eval/check_coverage.py`) that monitors production query logs against the canonical golden dataset.

---

## 2. Methodology & Similarity Threshold
For each query $q_{live} \in \mathcal{Q}_{live}$, the engine computes its dense vector representation using `nomic-embed-text` and evaluates the maximum cosine similarity across all golden questions $q_{golden} \in \mathcal{Q}_{golden}$:

$$\text{Coverage}(q_{live}) = \max_{g \in \mathcal{Q}_{golden}} \cos(\mathbf{e}(q_{live}), \mathbf{e}(g)) \ge \tau$$

Where $\tau = 0.70$ is the empirical semantic coverage threshold. Queries with $\text{Coverage}(q_{live}) < \tau$ represent **Coverage Gaps** (untested user intents and topics).

---

## 3. Empirical Results: Before vs After Golden Expansion

We evaluated 40 live production queries (`eval/live_queries.jsonl`) against the initial 26-question golden dataset, identified critical topic gaps, and expanded the dataset with 6 targeted test cases (`g27` to `g32`).

### Comparative Metrics

| Metric | Initial Golden Dataset (26 Qs) | Expanded Golden Dataset (32 Qs) | Impact / Recovery |
| :--- | :--- | :--- | :--- |
| **Total Live Queries Evaluated** | 40 | 40 | - |
| **Golden Question Count** | 26 | 32 | +6 questions (+23.1%) |
| **Similarity Threshold ($\tau$)** | 0.70 | 0.70 | Calibrated semantic threshold |
| **Covered Queries** | 18 / 40 | **24 / 40** | **+6 queries (+33.3% relative)** |
| **Coverage Gaps** | 22 | **16** | **-6 gaps eliminated** |
| **Overall Coverage Rate** | 45.0% | **60.0%** | **+15.0% absolute increase** |

### Per-Topic Coverage Resolution

| Topic | Initial Coverage % | Expanded Coverage % | Remediation Question Added |
| :--- | :--- | :--- | :--- |
| `fee_refund` | 0.0% | **100.0%** | `g27` (Fee refund schedule on class withdrawal) |
| `course_drop` | 0.0% | **100.0%** | `g28` (Course drop deadline with W grade) |
| `grading_appeal` | 0.0% | **100.0%** | `g29` (7-day grade appeal procedure) |
| `semester_freeze` | 0.0% | **100.0%** | `g30` (Semester freeze rules & 2-semester limit) |
| `sports_complex` | 33.3% | **66.7%** | `g31` (Sports complex gym hours and access) |
| `parking_regulations` | 0.0% | **100.0%** | `g32` (Student vehicle parking sticker procedure) |
| `hostel_curfew` | 0.0% | 0.0% | Flagged as true out-of-domain knowledge gap |
| `admissions` | 0.0% | 0.0% | Flagged for future admissions cycle expansion |

---

## 4. Key Takeaways & Operational Feedback Loop
1. **Closing the Loop**: The coverage checker transforms evaluation from a one-off pre-deployment benchmark into an active feedback loop where live queries directly inform test suite evolution.
2. **Distinguishing Drift from Out-of-Domain**: Queries regarding hostel curfews or cafeteria subsidies are confirmed out-of-scope and verified against honest abstention criteria (Part D4).
3. **Traceability**: All coverage evaluations are stored in `eval/results/coverage_report_expanded.json` for auditability and compliance reporting.
