"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

import re
from collections import Counter
from .models import Document, Page


def clean(doc: Document) -> Document:
    """Strip headers and footers that repeat on every page; keep headings and
    section boundaries, because chunking and citations depend on them."""
    if not doc.pages:
        return doc

    # Identify recurring top and bottom lines across pages (running headers/footers)
    first_lines: list[str] = []
    last_lines: list[str] = []
    for p in doc.pages:
        lines = [l.strip() for l in p.text.splitlines() if l.strip()]
        if len(lines) >= 3:
            first_lines.append(lines[0])
            last_lines.append(lines[-1])

    header_candidates = {line for line, count in Counter(first_lines).items() if count >= max(2, len(doc.pages) // 3)}
    footer_candidates = {line for line, count in Counter(last_lines).items() if count >= max(2, len(doc.pages) // 3)}

    # Typical page number patterns: "Page 1 of 58", "Page 12", "- 12 -", "12"
    page_num_regex = re.compile(r"^(?:page\s*\d+(?:\s*(?:of|/)\s*\d+)?|\d+|-\s*\d+\s*-)$", re.IGNORECASE)

    cleaned_pages: list[Page] = []
    for p in doc.pages:
        lines = p.text.splitlines()
        filtered_lines: list[str] = []

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                filtered_lines.append("")
                continue

            # Strip recurring running header if near top
            if idx < 3 and (stripped in header_candidates or page_num_regex.match(stripped)):
                continue

            # Strip recurring running footer if near bottom
            if idx >= len(lines) - 3 and (stripped in footer_candidates or page_num_regex.match(stripped)):
                continue

            filtered_lines.append(line)

        # Reconstruct text and collapse 3+ consecutive newlines into 2
        cleaned_text = "\n".join(filtered_lines)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()

        cleaned_pages.append(
            Page(source=p.source, page=p.page, text=cleaned_text, ocr=p.ocr)
        )

    return Document(
        source=doc.source,
        doc_version=doc.doc_version,
        superseded=doc.superseded,
        pages=cleaned_pages,
    )
