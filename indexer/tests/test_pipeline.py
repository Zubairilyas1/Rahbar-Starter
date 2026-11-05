"""Unit tests for indexer pipeline stages: extract, clean, chunk."""

import tempfile
from pathlib import Path
from pipeline.models import Document, Page
from pipeline.clean import clean
from pipeline.chunk import chunk
from pipeline.extract import extract


def test_clean_strips_recurring_headers_and_footers():
    pages = [
        Page(source="doc.pdf", page=1, text="Header Title\nPage 1\nSection 1 Intro\nContent 1\nFooter Info"),
        Page(source="doc.pdf", page=2, text="Header Title\nPage 2\nSection 2 Body\nContent 2\nFooter Info"),
        Page(source="doc.pdf", page=3, text="Header Title\nPage 3\nSection 3 Conclusion\nContent 3\nFooter Info"),
    ]
    doc = Document(source="doc.pdf", doc_version="2026", superseded=False, pages=pages)
    cleaned = clean(doc)

    for p in cleaned.pages:
        assert "Footer Info" not in p.text
        assert "Header Title" not in p.text
        assert "Content" in p.text


def test_chunk_preserves_metadata_and_structure():
    pages = [
        Page(
            source="rules.pdf",
            page=5,
            text="# 1.21 Attendance Policy\n\nStudents must maintain at least 80% attendance to sit in final exams.\n\nFailure to meet this results in an F grade.",
            ocr=False,
        )
    ]
    doc = Document(source="rules.pdf", doc_version="2026-06", superseded=False, pages=pages)
    chunks = chunk(doc, size=50, overlap=10)

    assert len(chunks) >= 1
    c = chunks[0]
    assert c.source == "rules.pdf"
    assert c.doc_version == "2026-06"
    assert c.superseded is False
    assert c.page == 5
    assert "Attendance Policy" in c.section
    assert "80%" in c.text

    meta = c.metadata()
    assert meta["source"] == "rules.pdf"
    assert meta["page"] == 5
    assert meta["doc_version"] == "2026-06"
    assert meta["superseded"] is False


def test_extract_html_tables():
    html_content = """
    <html>
      <body>
        <h2>Tuition Fees</h2>
        <table>
          <tr><th>Program</th><th>Fee</th></tr>
          <tr><td>BS CS</td><td>110000</td></tr>
        </table>
      </body>
    </html>
    """
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_content)
        tmp_path = f.name

    try:
        doc = extract(tmp_path, doc_version="2026", superseded=False)
        assert len(doc.pages) == 1
        page_text = doc.pages[0].text
        assert "BS CS" in page_text
        assert "110000" in page_text
        assert "Program" in page_text
    finally:
        Path(tmp_path).unlink(missing_ok=True)
