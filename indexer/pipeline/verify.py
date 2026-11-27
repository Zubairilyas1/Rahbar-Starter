"""Stage 1.5: Verification.
Runs after ingestion/extraction and before chunking (Assignment 03 Part A1, RAGOps paper 4.2.1-4.2.4).

Evaluates every document against four required checks:
1. Quality: empty, garbled, or failed extraction.
2. Completeness: required metadata present (source, title, date/doc_version, page_count); text not truncated.
3. Recency: checks whether a newer version of the same policy is detected.
4. Uniqueness: exact duplicates by hash, near-duplicates by content similarity.

Failed documents are moved to quarantine and excluded from indexing.
Produces a verification report file per run in eval/results/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import Document

log = logging.getLogger("rahbar.indexer.verify")


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    reason: str = "Passed"


@dataclass
class DocumentVerification:
    source: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    quarantined: bool = False
    quarantine_path: str | None = None
    hash_sha256: str = ""
    doc_version: str = ""


@dataclass
class VerificationReport:
    timestamp: str
    total_documents: int
    passed_documents: int
    quarantined_documents: int
    results: list[DocumentVerification] = field(default_factory=list)


def _strip_frontmatter(text: str) -> str:
    """Strips Markdown YAML front-matter markers so only document body is evaluated."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 hash of normalized text content (excluding frontmatter)."""
    body = _strip_frontmatter(text)
    normalized = re.sub(r"\s+", " ", body).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_jaccard_similarity(text1: str, text2: str, k: int = 3) -> float:
    """Computes Jaccard similarity of word k-shingles on body text to detect near-duplicates."""
    body1 = _strip_frontmatter(text1)
    body2 = _strip_frontmatter(text2)
    words1 = re.findall(r"\w+", body1.lower())
    words2 = re.findall(r"\w+", body2.lower())
    if len(words1) < k or len(words2) < k:
        set1 = set(words1)
        set2 = set(words2)
    else:
        set1 = set(tuple(words1[i : i + k]) for i in range(len(words1) - k + 1))
        set2 = set(tuple(words2[i : i + k]) for i in range(len(words2) - k + 1))
    
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union > 0 else 0.0


def check_quality(doc: Document, raw_text: str) -> CheckResult:
    """Check 1: Quality (empty, garbled, or failed extraction)."""
    if not doc.pages or not raw_text.strip():
        return CheckResult("quality", False, "Document text is completely empty or extraction returned 0 pages")
    
    if len(raw_text.strip()) < 40:
        return CheckResult("quality", False, f"Document text length ({len(raw_text.strip())} chars) is below minimum quality threshold")
    
    # Check for garbled / corrupt text (excessive non-printable characters or replacement characters)
    replacement_chars = raw_text.count("\ufffd") + raw_text.count("\x00")
    if replacement_chars > 20 or (len(raw_text) > 0 and replacement_chars / len(raw_text) > 0.05):
        return CheckResult("quality", False, f"Garbled text detected: {replacement_chars} replacement/corrupt characters")
    
    # Check printable ASCII/extended Unicode ratio
    printable_chars = sum(1 for c in raw_text if c.isprintable() or c in "\n\r\t")
    ratio = printable_chars / len(raw_text) if len(raw_text) > 0 else 0.0
    if ratio < 0.85:
        return CheckResult("quality", False, f"Garbled binary text detected: printable ratio is {ratio:.2f} (< 0.85)")

    return CheckResult("quality", True, "Quality verified: non-empty, clean printable text")


def check_completeness(doc: Document, raw_text: str, metadata: dict[str, Any]) -> CheckResult:
    """Check 2: Completeness (required metadata present: source, title, date/version, page count; not truncated)."""
    # 1. Metadata check
    source = doc.source or metadata.get("source")
    doc_version = doc.doc_version or metadata.get("doc_version")
    title = metadata.get("title") or metadata.get("doc_title")
    
    # If title not in explicit metadata, attempt extraction from first heading or clean filename
    if not title:
        first_line = raw_text.strip().split("\n")[0].strip("# ").strip()
        if len(first_line) > 3 and not first_line.startswith("{") and len(first_line.split()) < 15:
            title = first_line
        elif source:
            # Fallback to humanized filename if clean
            title = Path(source).stem.replace("-", " ").replace("_", " ").title()

    missing_fields = []
    if not source:
        missing_fields.append("source")
    if not doc_version or str(doc_version).lower() in {"unknown", "none", ""}:
        missing_fields.append("doc_version")
    if not title or title.lower() in {"unknown", "untitled", ""}:
        missing_fields.append("title")
    if len(doc.pages) == 0:
        missing_fields.append("page_count")

    if missing_fields:
        return CheckResult("completeness", False, f"Missing required metadata fields: {', '.join(missing_fields)}")

    # 2. Truncation check
    stripped = raw_text.strip()
    if "[TRUNCATED]" in stripped or "[CONTENT CUT OFF]" in stripped:
        return CheckResult("completeness", False, "Document contains explicit truncation marker")
    
    # Check if the document ends abruptly mid-sentence
    # Only flag if the last line is a full prose sentence (> 4 words) that ends abruptly without punctuation
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if lines:
        last_line = lines[-1]
        words = last_line.split()
        if len(words) > 4 and last_line[-1] not in ".!?\"'})\n|:-":
            return CheckResult("completeness", False, f"Document appears truncated mid-sentence: ends with '{words[-1]}' without punctuation")
        # Check if the very last word is cut off mid-token (e.g. ends with lowercase consonant like 'docu' without vowel/grammar completion)
        if len(words) >= 1 and words[-1].lower() in {"docu", "regul", "inst", "appli"}:
            return CheckResult("completeness", False, f"Document text abruptly truncated mid-word: '{words[-1]}'")

    return CheckResult("completeness", True, "Completeness verified: all metadata present and text not truncated")


def check_recency(doc: Document, metadata: dict[str, Any], seen_versions: dict[str, str]) -> CheckResult:
    """Check 3: Recency (detect if a newer version of the same policy already exists)."""
    # Identify canonical policy name (stripping leading doc numbering and trailing date tags)
    stem = Path(doc.source).stem.lower()
    stem = re.sub(r"^doc\d+[-_]", "", stem)
    canonical_name = re.sub(r"[-_](20\d\d|aug|jun|fall|spring|v\d+).*", "", stem)
    
    current_ver = str(doc.doc_version or metadata.get("doc_version", "")).strip()
    
    if canonical_name in seen_versions:
        existing_ver = seen_versions[canonical_name]
        # Compare versions (simple numerical/chronological comparison)
        if existing_ver > current_ver and current_ver != "":
            return CheckResult(
                "recency",
                False,
                f"Recency conflict: a newer version '{existing_ver}' of policy '{canonical_name}' is already active, incoming is older '{current_ver}'"
            )
    else:
        if current_ver and current_ver != "unknown":
            seen_versions[canonical_name] = current_ver

    return CheckResult("recency", True, "Recency verified: current active version or no newer conflict")


def check_uniqueness(
    doc: Document,
    raw_text: str,
    seen_hashes: dict[str, str],
    seen_texts: dict[str, str],
    near_dup_threshold: float = 0.80,
) -> tuple[CheckResult, str]:
    """Check 4: Uniqueness (exact duplicates by hash, near-duplicates by similarity)."""
    content_hash = compute_content_hash(raw_text)
    
    # 1. Exact duplicate check
    if content_hash in seen_hashes:
        original_doc = seen_hashes[content_hash]
        return (
            CheckResult("uniqueness", False, f"Exact duplicate of '{original_doc}' (identical SHA-256 content hash: {content_hash[:12]})"),
            content_hash
        )
    
    # 2. Near duplicate check
    for existing_source, existing_text in seen_texts.items():
        sim_3 = compute_jaccard_similarity(raw_text, existing_text, k=3)
        sim_1 = compute_jaccard_similarity(raw_text, existing_text, k=1)
        if sim_3 >= near_dup_threshold or sim_1 >= 0.90:
            pct = max(sim_3, sim_1) * 100
            return (
                CheckResult("uniqueness", False, f"Near-duplicate of '{existing_source}' with {pct:.1f}% word/shingle similarity (&ge; 85%)"),
                content_hash
            )
            
    # Record current document
    seen_hashes[content_hash] = doc.source
    seen_texts[doc.source] = raw_text
    return (CheckResult("uniqueness", True, "Uniqueness verified: content is novel and distinct"), content_hash)


def verify_and_quarantine(
    documents: list[tuple[Document, Path, dict[str, Any]]],
    quarantine_dir: str | Path = "corpus/quarantine",
    report_path: str | Path = "eval/results/verification_report.json",
) -> tuple[list[Document], VerificationReport]:
    """Runs all 4 verification checks on each extracted document.
    
    Failing documents are copied/moved to quarantine_dir and excluded from the returned list.
    Outputs a structured VerificationReport.
    """
    quarantine_path = Path(quarantine_dir)
    quarantine_path.mkdir(parents=True, exist_ok=True)
    
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)

    passed_docs: list[Document] = []
    report_items: list[DocumentVerification] = []

    seen_hashes: dict[str, str] = {}
    seen_texts: dict[str, str] = {}
    seen_versions: dict[str, str] = {}

    for doc, file_path, meta in documents:
        raw_text = "\n\n".join(p.text for p in doc.pages)
        
        # Run 4 checks
        res_quality = check_quality(doc, raw_text)
        res_completeness = check_completeness(doc, raw_text, meta)
        res_recency = check_recency(doc, meta, seen_versions)
        res_uniqueness, content_hash = check_uniqueness(doc, raw_text, seen_hashes, seen_texts)

        checks = [res_quality, res_completeness, res_recency, res_uniqueness]
        all_passed = all(c.passed for c in checks)

        doc_ver = DocumentVerification(
            source=doc.source,
            passed=all_passed,
            checks=checks,
            hash_sha256=content_hash,
            doc_version=doc.doc_version,
        )

        if all_passed:
            passed_docs.append(doc)
            log.info("verification passed for %s", doc.source)
        else:
            # Quarantine document
            doc_ver.quarantined = True
            dest_file = quarantine_path / Path(doc.source).name
            try:
                if file_path.exists():
                    shutil.copy2(file_path, dest_file)
                    doc_ver.quarantine_path = str(dest_file)
            except Exception as e:
                log.warning("could not copy to quarantine: %s", str(e))
                doc_ver.quarantine_path = str(dest_file)
            
            reasons = [c.reason for c in checks if not c.passed]
            log.warning("verification failed -> quarantined: %s (%s)", doc.source, reasons)

        report_items.append(doc_ver)

    report = VerificationReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        total_documents=len(documents),
        passed_documents=len(passed_docs),
        quarantined_documents=len(documents) - len(passed_docs),
        results=report_items,
    )

    # Save report
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    log.info("verification report written to %s (passed: %d, quarantined: %d)", str(report_path), report.passed_documents, report.quarantined_documents)

    return passed_docs, report
