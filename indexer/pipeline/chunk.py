"""Stage 3: Chunk. Structure-aware, with overlap."""

from __future__ import annotations

import re
import hashlib
from .models import Chunk, Document


SECTION_REGEX = re.compile(
    r"^(?:#{1,6}\s+.+|(?:\d+\.)+\d*\s+[A-Z].+|[A-Z\s]{4,}:?)$",
    re.MULTILINE
)


def _approx_token_count(text: str) -> int:
    """Rough estimation of token count (~1 token per 0.75 words / 4 characters)."""
    return len(text.split())


def _split_into_sentences(paragraph: str) -> list[str]:
    """Split a paragraph into sentences preserving sentence endings."""
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    return [s.strip() for s in sentences if s.strip()]


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split on sections, then paragraphs, then sentences, keeping each chunk under
    `size` tokens, with `overlap` tokens shared between neighbours. Every chunk keeps
    the section heading it sits under, its page, doc_version and superseded."""
    chunks: list[Chunk] = []
    current_section = "General"
    pending_heading: str | None = None

    for page in doc.pages:
        text = page.text.strip()
        if not text:
            continue

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        for para in paragraphs:
            lines = para.splitlines()
            first_line = lines[0].strip()

            # Check if this paragraph is purely a section header
            if SECTION_REGEX.match(first_line) and len(lines) == 1 and len(first_line.split()) < 15:
                current_section = first_line.lstrip("#").strip()
                pending_heading = first_line
                continue

            # If there was a pending heading, prepend it to the paragraph for semantic context
            if pending_heading:
                para = f"{pending_heading}\n{para}"
                pending_heading = None

            words = para.split()
            if len(words) <= size:
                para_text = para
                chunk_id = hashlib.sha256(
                    f"{doc.source}:{page.page}:{len(chunks)}:{para_text[:30]}".encode()
                ).hexdigest()[:16]

                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=para_text,
                        source=doc.source,
                        section=current_section,
                        page=page.page,
                        doc_version=doc.doc_version,
                        superseded=doc.superseded,
                    )
                )
            else:
                sentences = _split_into_sentences(para)
                current_words: list[str] = []

                for sentence in sentences:
                    s_words = sentence.split()
                    if len(current_words) + len(s_words) <= size:
                        current_words.extend(s_words)
                    else:
                        if current_words:
                            chunk_text = " ".join(current_words)
                            chunk_id = hashlib.sha256(
                                f"{doc.source}:{page.page}:{len(chunks)}:{chunk_text[:30]}".encode()
                            ).hexdigest()[:16]

                            chunks.append(
                                Chunk(
                                    id=chunk_id,
                                    text=chunk_text,
                                    source=doc.source,
                                    section=current_section,
                                    page=page.page,
                                    doc_version=doc.doc_version,
                                    superseded=doc.superseded,
                                )
                            )

                            overlap_count = min(overlap, len(current_words))
                            current_words = current_words[-overlap_count:] + s_words
                        else:
                            for i in range(0, len(s_words), max(1, size - overlap)):
                                window_words = s_words[i : i + size]
                                chunk_text = " ".join(window_words)
                                chunk_id = hashlib.sha256(
                                    f"{doc.source}:{page.page}:{len(chunks)}:{chunk_text[:30]}".encode()
                                ).hexdigest()[:16]

                                chunks.append(
                                    Chunk(
                                        id=chunk_id,
                                        text=chunk_text,
                                        source=doc.source,
                                        section=current_section,
                                        page=page.page,
                                        doc_version=doc.doc_version,
                                        superseded=doc.superseded,
                                    )
                                )

                if current_words:
                    chunk_text = " ".join(current_words)
                    chunk_id = hashlib.sha256(
                        f"{doc.source}:{page.page}:{len(chunks)}:{chunk_text[:30]}".encode()
                    ).hexdigest()[:16]

                    chunks.append(
                        Chunk(
                            id=chunk_id,
                            text=chunk_text,
                            source=doc.source,
                            section=current_section,
                            page=page.page,
                            doc_version=doc.doc_version,
                            superseded=doc.superseded,
                        )
                    )

    return chunks
