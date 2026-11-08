# AI Usage & Attribution Disclosure

In compliance with the assignment policy on artificial intelligence assistance, this document records the AI tools employed during the design, development, and debugging of RAHBAR, what they generated or shaped, and what we manually verified, refined, and altered.

---

## Tool Disclosure Table

| Tool | What it wrote or shaped | What we changed afterwards, and why |
|---|---|---|
| **Google Antigravity (Gemini 3.8 / Claude Sonnet)** | Assisted with scaffolding boilerplate for HTML table extraction (`SimpleHTMLTextExtractor`), draft Pydantic schema validation patterns, and initial structural drafts for ADRs 0001 through 0004. | **Significant modifications**: <br>1. Refactored `chunk.py`: Initial AI generation created standalone chunks for headers (e.g. `1.21 Attendance Policy` as its own 4-word chunk). We completely rewrote the chunking loop to attach pending headings directly to the following paragraphs so vector embeddings contain both the clause title and its body.<br>2. Implemented strict citation verification in `citations.py` to drop unretrieved citations and prevent hallucination penalties.<br>3. Authored the embedding-model guardrail: a mismatched model logs a critical error and readiness excludes the pod from Service endpoints. |
| **OpenAI ChatGPT (GPT-4o)** | Used to brainstorm initial test question variations for the golden evaluation set (`eval/golden.yaml`) and verify mathematical formulas for Reciprocal Rank Fusion (RRF) and Storage Amplification. | **Significant modifications**: <br>1. Replaced all synthetic/generic questions with exact, verified factual queries based strictly on the downloaded FAST-NUCES documents (e.g., verifying exact CGPA thresholds, fee amounts, and course code `CS4032`).<br>2. Manually verified all 16 ground-truth relevant chunk mappings against the actual output of our indexer. |
| **GitHub Copilot** | Inline code autocompletion for repetitive test assertions and mock dictionaries in `api/tests/test_rag_pipeline.py`. | Kept only assertions that strictly verified system behavior; wrote the custom security injection tests manually to verify defense against prompt injection attacks. |
| **Claude Code** | Drafted the Dockerfiles, Kubernetes manifests, CI/CD workflows, architecture documentation, and the initial cluster deployment and debugging steps. | We reviewed the files, corrected CI failures, verified the CI jobs and live cluster, and documented the remaining limitations. |
| **OpenAI Codex** | Checked the merged repository, CI/CD status, submission checker, and live cluster; captured command evidence and assisted with the remaining demonstrations and documentation. | We must review the evidence, explain the demo results, and complete account-controlled setup and submission ourselves. |

---

## Engineering Ownership Statement

We are responsible for reviewing and understanding the submitted work, including AI-assisted code and documentation. Automated checks and the submission checker cover the behaviors described in their outputs; live demonstrations and published images require separate evidence.
