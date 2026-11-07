# Intentional Failure Mode Analysis & Engineering Recovery

According to Section 5.5 of the specification, four distinct stages of the RAHBAR RAG pipeline were deliberately disrupted, diagnosed using real system signals and metrics, and subsequently restored.

---

## Stage 1: Extraction Failure (`indexer/pipeline/extract.py`)

- **What we broke:** We disabled the OCR fallback conditional block by forcing `ocr_flag = False` and skipping Tesseract invocation when page character count was under 50 characters.
- **Symptom:** The 8-page scanned document `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` produced empty text for every page. Zero semantic chunks were stored in ChromaDB for this document. Queries regarding faculty startup equity and IP ownership failed to retrieve relevant evidence and triggered abstention.
- **Diagnosis:**
  - Indexer log inspect: `python -m pipeline.run` output showed `source=faculty-entrepreneurship...pdf chunks=0`.
  - Chroma inspection: Querying `collection.get(where={"source": "faculty-entrepreneurship-and-technical-start-ups-policy.pdf"})` returned empty ID arrays.
  - Evaluation metric: `recall@5` for entrepreneurship questions dropped to `0.00`.
- **Remedy:** Restored automated page text length threshold checking (`len(text) < 50`) that invokes `pytesseract.image_to_string()` via `pdf2image` and stamps metadata with `ocr: true`.

---

## Stage 2: Chunking Failure (`indexer/pipeline/chunk.py`)

- **What we broke:** We reduced the chunk overlap to 0 tokens (`chunk_overlap = 0`) and disabled structure-aware sentence boundary grouping, relying solely on fixed character splitting.
- **Symptom:** Long legal definitions in Section 4 of the Student Code of Conduct were truncated midway through legal clauses. Questions matching sentences that spanned chunk cutoffs failed retrieval because key contextual nouns and verbs were separated into adjacent vectors.
- **Diagnosis:**
  - Evaluation metric: `recall@5` on long definition queries dropped from `0.85` down to `0.68` (a 17-point regression, failing the `MAX_RECALL5_DROP` evaluation gate).
  - Text inspect: Inspecting generated chunks showed sentences beginning with lower-case mid-sentence tokens lacking paragraph headings.
- **Remedy:** Reinstated structure-aware recursive chunking (Section heading $\to$ Paragraph $\to$ Sentence) and configured a 50-token rolling overlap window (`chunk_overlap=50`).

---

## Stage 3: Retrieval & Versioning Contamination (`api/app/retrieval/chroma.py`)

- **What we broke:** We removed the metadata filter condition `where={"superseded": False}` in the Chroma vector search call.
- **Symptom:** When asking standard questions about undergraduate attendance requirements, the retriever returned obsolete chunks from `undergraduate-academic-rules-aug-2023.pdf` (`superseded=True`) ahead of current June 2026 handbook rules due to slightly higher keyword density. The model cited repealed clause numbers as current university policy.
- **Diagnosis:**
  - Query response inspection: The returned `citations` field contained `undergraduate-academic-rules-aug-2023.pdf` instead of the active 2026 handbook.
  - Evaluation metric: `recall@5_by_type["version"]` failed regression testing, causing contradictory answers on academic warnings.
- **Remedy:** Re-implemented the versioning filter in `ChromaRetriever.retrieve()`: by default, all queries apply `where={"superseded": False}` unless the user query explicitly matches historical keywords (`2023`, `old`, `previous`, `past`).

---

## Stage 4: Generation Failure & Temperature Drift (`api/app/providers/llm/ollama.py`)

- **What we broke:** We increased the LLM temperature parameter from `0.2` to `1.2` and relaxed the system grounding prompt instructions.
- **Symptom:** The language model exhibited severe stochastic hallucination. It fabricated non-existent clause identifiers, invented section titles not found in the evidence passages, and attempted to extrapolate facts beyond the retrieved text.
- **Diagnosis:**
  - Citation verification logs: The service logged repeated warnings: `Dropped hallucinated citation: source='...', section='...' (does not match any retrieved passage)`.
  - Evaluation metric: `citation_validity` plummeted from `0.98` down to `0.42`, instantly failing the CI `MIN_CITATION_VALIDITY` gate (threshold 0.95).
- **Remedy:** Pinned generation temperature to `0.2` for deterministic grounded extraction, maintained strict negative constraints in the system prompt, and enforced post-generation citation validation in `api/app/services/citations.py` to drop unverified citations.
