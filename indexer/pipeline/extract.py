"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pypdf
import pdfplumber
import pytesseract
from pdf2image import convert_from_path

from .models import Document, Page

log = logging.getLogger("rahbar.indexer.extract")


class SimpleHTMLTextExtractor(HTMLParser):
    """Converts HTML pages and tables into structured markdown text."""

    def __init__(self) -> None:
        super().__init__()
        self.pieces: list[str] = []
        self.in_table = False
        self.table_row: list[str] = []
        self.table_rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.pieces.append("\n\n### ")
        elif tag_lower in {"p", "div", "br", "li"}:
            self.pieces.append("\n")
        elif tag_lower == "table":
            self.in_table = True
            self.table_rows = []
        elif tag_lower == "tr":
            self.table_row = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "tr":
            if self.table_row:
                self.table_rows.append(self.table_row)
            self.table_row = []
        elif tag_lower == "table":
            self.in_table = False
            if self.table_rows:
                self.pieces.append("\n\n")
                for i, row in enumerate(self.table_rows):
                    self.pieces.append("| " + " | ".join(row) + " |\n")
                    if i == 0:
                        self.pieces.append("| " + " | ".join(["---"] * len(row)) + " |\n")
                self.pieces.append("\n")
            self.table_rows = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self.in_table:
            clean_cell = re.sub(r"\s+", " ", text)
            self.table_row.append(clean_cell)
        else:
            self.pieces.append(text + " ")

    def get_text(self) -> str:
        return "".join(self.pieces).strip()


def _ocr_page(pdf_path: str, page_number: int) -> str:
    """Attempts to run Tesseract OCR on a specific page of an image-only PDF."""
    try:
        images = convert_from_path(pdf_path, first_page=page_number, last_page=page_number)
        if images:
            text = pytesseract.image_to_string(images[0])
            return text.strip()
    except Exception:
        # Fallback using WSL tesseract and poppler on Windows hosts
        try:
            abs_path = os.path.abspath(pdf_path)
            drive_letter = abs_path[0].lower()
            wsl_path = f"/mnt/{drive_letter}/" + abs_path[3:].replace("\\", "/")
            cmd = f'pdftoppm -png -r 150 -f {page_number} -l {page_number} "{wsl_path}" /tmp/ocr_p && tesseract /tmp/ocr_p-*.png stdout 2>/dev/null && rm -f /tmp/ocr_p*'
            res = subprocess.check_output(['wsl', '-d', 'Ubuntu-24.04', '-e', 'bash', '-c', cmd], text=True, errors='replace')
            if res.strip():
                return res.strip()
        except Exception as wsl_exc:
            log.warning(f"OCR fallback failed for {pdf_path} page {page_number}: {wsl_exc}")
    return ""


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    """Return the document's text page by page.

    Detect pages with no text layer and OCR them; mark those pages ocr=True.
    The OCR libraries need system packages in your Dockerfile (tesseract-ocr,
    poppler-utils), not only pip packages.
    """
    file_path = Path(path)
    source_name = file_path.name
    suffix = file_path.suffix.lower()
    pages: list[Page] = []

    if suffix == ".pdf":
        try:
            reader = pypdf.PdfReader(str(file_path))
            for idx, p in enumerate(reader.pages):
                page_num = idx + 1
                text = (p.extract_text() or "").strip()
                ocr_flag = False

                # If extracted text is fewer than 50 characters, page is likely scanned/image-only
                if len(text) < 50:
                    ocr_text = _ocr_page(str(file_path), page_num)
                    if ocr_text:
                        text = ocr_text
                    ocr_flag = True

                pages.append(Page(source=source_name, page=page_num, text=text, ocr=ocr_flag))
        except Exception as exc:
            log.error(f"Failed extracting PDF {path}: {exc}")
            # Fallback to pdfplumber if pypdf encountered issues
            try:
                with pdfplumber.open(str(file_path)) as pdf:
                    for idx, plumber_page in enumerate(pdf.pages):
                        page_num = idx + 1
                        text = (plumber_page.extract_text() or "").strip()
                        ocr_flag = len(text) < 50
                        pages.append(Page(source=source_name, page=page_num, text=text, ocr=ocr_flag))
            except Exception as inner_exc:
                log.error(f"pdfplumber fallback also failed for {path}: {inner_exc}")

    elif suffix in {".html", ".htm"}:
        try:
            raw_html = file_path.read_text(encoding="utf-8", errors="replace")
            parser = SimpleHTMLTextExtractor()
            parser.feed(raw_html)
            text = parser.get_text()
            pages.append(Page(source=source_name, page=1, text=text, ocr=False))
        except Exception as exc:
            log.error(f"Failed extracting HTML {path}: {exc}")

    elif suffix in {".md", ".txt"}:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            pages.append(Page(source=source_name, page=1, text=text, ocr=False))
        except Exception as exc:
            log.error(f"Failed extracting text {path}: {exc}")

    else:
        log.warning(f"Unsupported file format for extraction: {path}")

    return Document(
        source=source_name,
        doc_version=doc_version,
        superseded=superseded,
        pages=pages,
    )
