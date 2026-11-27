# Corpus Specification & Grounding Properties

**Source:** FAST-NUCES Public Website  
**Total Documents:** 9 (7 PDF documents + 2 HTML pages)  
**Total Pages:** 279 PDF pages + 2 Web pages  
**Corpus Manifest:** [`corpus/MANIFEST.md`](../corpus/MANIFEST.md)  
**Fetch Script:** [`corpus/fetch.py`](../corpus/fetch.py)

---

## Required Properties Mapping

| # | Required Property | Document(s) Providing It | Evidence, Clauses & Technical Notes |
|---|---|---|---|
| **1** | **At least 6 documents, 40 pages in total** | All 9 corpus documents: <br>• `undergraduate-academic-rules-aug-2023.pdf` (26 pages)<br>• `academic-rules-handbook-jun-2026.pdf` (58 pages)<br>• `prospectus-2026-academic-rules-and-regulations.pdf` (5 pages)<br>• `student-handbook-jun-2026.pdf` (64 pages)<br>• `annual-report-2019-20.pdf` (33 pages)<br>• `annual-report-2023-24.pdf` (85 pages)<br>• `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (8 pages)<br>• `fee-structure-page.html`<br>• `grading-page.html` | Total volume exceeds 279 PDF pages and 9 distinct documents. Downloaded politely using `corpus/fetch.py` and pinned with SHA-256 checksums in `corpus/MANIFEST.md`. |
| **2** | **Two versions of one policy (Versioning & Superseding)** | `undergraduate-academic-rules-aug-2023.pdf` (version `2023-08`, **superseded: true**) vs `academic-rules-handbook-jun-2026.pdf` (version `2026-06`, **superseded: false**) and `prospectus-2026-academic-rules-and-regulations.pdf` (version `2026`, **superseded: false**) | The 2023 rules explicitly state previous graduation and attendance thresholds, whereas the June 2026 handbook revises clause numbers and academic warning regulations (e.g., attendance rule 1.21 in 2026 handbook vs clause 1 in prospectus). In `corpus/raw/_index.json`, chunks from 2023 carry `superseded: true`, enabling the retriever to filter them out for standard questions while allowing explicit historical queries. |
| **3** | **Scanned, image-only PDF (OCR Requirement)** | `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` (version `2022-05`) | Verified by extracting text with `pypdf` and running `pdffonts`: the 8 pages return 0 font descriptors and 0 extracted characters per page. It is an image-only scanned document without an embedded text layer. Stage 1 (`extract.py`) detects text length < 50 characters, invokes Tesseract OCR (`pytesseract`/`pdf2image`), and marks chunks with metadata `ocr: true`. |
| **4** | **Tables with real structured information** | • `annual-report-2019-20.pdf` (pages 12–15: faculty distribution tables)<br>• `annual-report-2023-24.pdf` (pages 22–27: research publications and student enrollment)<br>• `fee-structure-page.html` (admission and tuition fee tables across degree programs)<br>• `grading-page.html` (letter grades, numerical mark ranges, and grade points) | Multi-column and multi-row tables containing exact semester fee amounts, admission security deposits, and credit hour rates. Table extraction preserves markdown/tabular formatting to prevent cell transposition and column misalignment. |
| **5** | **Long definitions (>500 tokens)** | `student-handbook-jun-2026.pdf` (Section 4: Student Code of Conduct & Plagiarism Policy) | Section 4 provides extensive, multi-paragraph legalistic definitions of academic dishonesty, disciplinary hearings, and appeal procedures spanning multiple pages (>1,200 tokens). This tests chunking logic to ensure sentences and paragraphs are split cleanly across token boundaries without severing clause context. |
| **6** | **Deliberately absent topic (Abstention Testing)** | Transport routes, bus schedules, and on-campus hostel allotment | FAST-NUCES has a document `Transport and Hostel Facilities.pdf` which was intentionally omitted from `corpus/sources.yaml`. When users ask questions like *"What is the monthly hostel fee for undergraduate students?"* or *"What are the bus routes for the Islamabad campus?"*, the retriever finds no chunks exceeding the `relevance_floor` threshold (0.50 cosine similarity). The generation pipeline must abstain and return an explicit `null` answer. |
| **7** | **Exact-term content (Course codes, thresholds, fees)** | • `academic-rules-handbook-jun-2026.pdf`<br>• `grading-page.html`<br>• `fee-structure-page.html` | Contains exact numerical thresholds: minimum CGPA 2.00 for undergraduate degree award, minimum 80% attendance requirement (Clause 1.21), letter grade `A+` (Grade Points 4.00, 90–100 marks), course codes such as `CS4032`, `CL217`, and specific per-semester tuition fees (PKR 110,000+). Tests exact term retrieval without hallucinated figures. |

---

## Corpus Verification

All documents are verified against their SHA-256 hashes recorded in `corpus/MANIFEST.md`:
```bash
python corpus/fetch.py --verify
```
All raw documents reside in `corpus/raw/` (gitignored), ensuring reproducible re-downloads while preserving repository cleanliness.
