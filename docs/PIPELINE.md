# Indexing and Retrieval Pipeline

This document records the design, engineering trade-offs, and empirical measurements of the RAHBAR ingestion pipeline.

---

## 1. Extraction Stage (`indexer/pipeline/extract.py`)

### Document Formats Handled
- **PDF Extraction**: Primary processing via `pypdf` with fallback to `pdfplumber`. Text is extracted page-by-page to retain 1-based page metadata for grounded citations.
- **HTML Parsing**: Custom `SimpleHTMLTextExtractor` based on Python's standard `html.parser`. Translates web markup directly into structured markdown headings and tabular markdown representations.
- **Markdown & Plain Text**: Direct reading with front-matter extraction for evaluation fixtures.

### OCR Detection and Recovery
- **Target Document**: `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (8 pages, version `2022-05`).
- **Detection Mechanism**: Pages yielding fewer than 50 extracted characters are identified as image-only scanned documents lacking an embedded digital font layer (verified with `pdffonts`).
- **OCR Engine**: Tesseract OCR via `pytesseract` and `pdf2image` (`poppler-utils`). Each textless page is rendered to 300 DPI images and transcribed.
- **Metadata Tagging**: All chunks extracted from OCR pages carry `ocr: true` in their chunk metadata.
- **Unrecoverable Artifacts**: Signature stamps, official university seals, and handwritten signatures in low-resolution scans could not be converted to semantic text and were dropped to avoid hallucinated character sequences.

### Table Extraction Example (HTML to Markdown)
*Before (Raw HTML):*
```html
<table>
  <tr><th>Program</th><th>Admission Fee</th><th>Tuition Fee (Per Sem)</th></tr>
  <tr><td>BS (CS/SE/AI)</td><td>PKR 30,000</td><td>PKR 110,000</td></tr>
</table>
```
*After (Normalized Markdown Table):*
```markdown
| Program | Admission Fee | Tuition Fee (Per Sem) |
| --- | --- | --- |
| BS (CS/SE/AI) | PKR 30,000 | PKR 110,000 |
```

---

## 2. Cleaning Stage (`indexer/pipeline/clean.py`)

### Applied Rules
1. **Running Page Headers & Footers**: Computed word histograms for lines appearing in the top 3 and bottom 3 lines across pages. Any exact line recurring on $>33\%$ of pages (e.g. *"FAST National University of Computer & Emerging Sciences"*, *"Annual Report 2023-24"*) is stripped.
2. **Page Number Formats**: Regex patterns matching isolated numbers (`"Page 1 of 58"`, `"- 12 -"`, `"\d+"`) at page boundaries are eliminated to prevent confusing the vector retriever.
3. **Whitespace Normalization**: Multiple consecutive blank lines are collapsed into a canonical double newline (`\n\n`) to preserve paragraph separation while removing empty space.

### Deliberately Preserved Structures
- **Section Headers and Numbered Clauses**: Substrings matching `#{1,6}` or clause patterns like `1.21 Attendance Policy` or `5.4 Academic Warning` are strictly preserved.
- **Table Cell Formatting**: Pipe separators and column boundaries are maintained to prevent cell transposition.

---

## 3. Chunking Configurations & Storage Amplification (`indexer/pipeline/chunk.py`)

The chunker uses a structure-aware recursive algorithm: splitting on section headings, then paragraphs, and finally sentences. Overlapping token windows bridge adjacent chunks to ensure questions spanning boundaries retain full context.

### Measured Configurations Against Recall@5

| Configuration | Chunk Size (tokens) | Overlap (tokens) | Total Chunks Produced | Recall@5 | Latency (ms) | Notes |
|---|---|---|---|---|---|---|
| **Config A (Small)** | 250 | 30 | 1,420 | 0.68 | 42ms | Splits fine-grained definitions prematurely; misses cross-sentence context. |
| **Config B (Production - Shipped)** | **400** | **50** | **945** | **0.82** | **58ms** | **Optimal balance**: Holds complete legal clauses while staying well within the embedding model context. |
| **Config C (Large)** | 600 | 100 | 610 | 0.74 | 86ms | Embeddings become diluted; lower similarity scores for specific numerical questions. |

### Storage Amplification
$$\text{Storage Amplification Ratio} = \frac{\text{Stored Tokens}}{\text{Original Document Tokens}} = \frac{378,000}{328,000} \approx 1.15\times$$
The shipped configuration produces an amplification ratio of approximately **1.15×** (or 115%), attributable to the 50-token window overlap between consecutive chunks.

---

## 4. Embedding & Chroma Storage (`indexer/pipeline/store.py`)

- **Pinned Embedding Model**: `nomic-embed-text` (768 dimensions), executed locally via Ollama `/api/embed` with batching (32 chunks per HTTP request).
- **Collection Metadata**: The collection is created with explicit metadata tags:
  ```json
  {
    "embed_model": "nomic-embed-text",
    "embedding_model": "nomic-embed-text",
    "vector_dim": 768,
    "hnsw:space": "cosine"
  }
  ```
- **Similarity Threshold**: Query similarity is calculated as $1 - \text{cosine distance}$. The relevance floor is set to `0.50` to trigger abstention on out-of-corpus queries.
- **Resource Profiling**: The committed `kubectl top pods` capture was taken after the dummy indexer Job completed, so it does not establish a real-corpus indexer peak. The Job limit is `768Mi`; a measured OCR and embedding peak still requires sampling the Job while it runs on the real corpus (see `docs/evidence/README.md`).
