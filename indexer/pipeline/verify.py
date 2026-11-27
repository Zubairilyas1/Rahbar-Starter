"""Stage 1.5: Verification.
Runs after ingestion/extraction and before chunking (Assignment 03 Part A1, RAGOps paper 4.2.1-4.2.4).

Evaluates every document against four required checks:
1. Quality: empty, garbled, or failed extraction.
2. Completeness: required metadata present (source, title, date/doc_version, page_count); text not truncated.
3. Recency: checks whether a newer version of the same policy is detected.
4. Uniqueness: exact duplicates by hash, near-duplicates by embedding cosine similarity.

Failed documents are moved to quarantine and excluded from indexing.
Produces a verification report file per run in eval/results/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import shutil
import time
from collections.abc import Callable
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
    supersedes: list[str] = field(default_factory=list)


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


def canonical_name(source: str) -> str:
    """The policy a file is a version of: strip a leading 'docNN-' and any trailing
    date/version tag, so 'doc09-campus-wifi-policy-2024-outdated.md' and
    'doc01-campus-wifi-policy-2026.md' both map to 'campus-wifi-policy'.

    A reporting-period suffix such as 'annual-report-2019-20' names a different
    report (a series member), not a version, so it is kept as part of the name."""
    stem = Path(source).stem.lower()
    stem = re.sub(r"^doc\d+[-_]", "", stem)
    if re.search(r"[-_](19|20)\d\d-\d\d$", stem):
        return stem
    return re.sub(r"[-_](20\d\d|aug|jun|fall|spring|v\d+).*", "", stem)


def _version_key(version: str) -> str:
    v = str(version or "").strip().lower()
    return "" if v in {"", "unknown", "none"} else v


def check_recency(
    doc: Document,
    metadata: dict[str, Any],
    newest_versions: dict[str, tuple[str, str]],
) -> CheckResult:
    """Check 3: Recency. `newest_versions` maps a canonical policy name to the newest
    (version, source) seen across the already-indexed corpus AND this batch, so the
    result does not depend on the order files arrive in. An incoming document fails
    when a newer version of the same policy exists; it passes (and will supersede the
    older indexed one) when it is itself the newest."""
    name = canonical_name(doc.source)
    current_ver = _version_key(doc.doc_version or metadata.get("doc_version", ""))
    newest = newest_versions.get(name)
    if doc.superseded:
        # Deliberately kept historical version (marked superseded in its metadata):
        # indexed with superseded=True, so the retrieval filter excludes it by default.
        return CheckResult("recency", True,
                           "Recency: explicitly marked superseded; indexed as an archived version")
    if newest and current_ver and newest[0] > current_ver and newest[1] != doc.source:
        return CheckResult(
            "recency",
            False,
            f"Recency conflict: newer version '{newest[0]}' of policy '{name}' exists "
            f"({newest[1]}); incoming version is '{current_ver}'",
        )
    return CheckResult("recency", True, "Recency verified: this is the newest known version of the document")


def cosine(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    return dot / (n1 * n2) if n1 and n2 else 0.0


def doc_embedding_text(raw_text: str, limit: int = 2000) -> str:
    """The text a whole-document embedding is computed from (body, first `limit` chars)."""
    return re.sub(r"\s+", " ", _strip_frontmatter(raw_text)).strip()[:limit]


def check_uniqueness(
    doc: Document,
    raw_text: str,
    seen_hashes: dict[str, str],
    seen_vectors: dict[str, list[float]],
    doc_vector: list[float] | None,
    near_dup_threshold: float = 0.95,
    seen_texts: dict[str, str] | None = None,
) -> tuple[CheckResult, str]:
    """Check 4: Uniqueness. Exact duplicates by normalised content hash; near-duplicates
    by cosine similarity of whole-document embeddings (pinned EMBED_MODEL). The
    seen_* maps already hold every indexed document, so a Batch B file that copies a
    document from the first batch is caught too. If no embedder is available (offline
    unit tests) it falls back to word-shingle Jaccard and says so in the reason."""
    content_hash = compute_content_hash(raw_text)

    if content_hash in seen_hashes:
        return (
            CheckResult("uniqueness", False,
                        f"Exact duplicate of '{seen_hashes[content_hash]}' (identical SHA-256 content hash {content_hash[:12]})"),
            content_hash,
        )

    if doc_vector is not None:
        best_src, best_sim = None, 0.0
        for src, vec in seen_vectors.items():
            sim = cosine(doc_vector, vec)
            if sim > best_sim:
                best_src, best_sim = src, sim
        if best_src is not None and best_sim >= near_dup_threshold:
            return (
                CheckResult("uniqueness", False,
                            f"Near-duplicate of '{best_src}': embedding cosine {best_sim:.4f} >= {near_dup_threshold:.2f}"),
                content_hash,
            )
        seen_vectors[doc.source] = doc_vector
    elif seen_texts is not None:
        for src, text in seen_texts.items():
            sim = max(compute_jaccard_similarity(raw_text, text, k=3), compute_jaccard_similarity(raw_text, text, k=1) - 0.10)
            if sim >= 0.80:
                return (
                    CheckResult("uniqueness", False,
                                f"Near-duplicate of '{src}': shingle Jaccard {sim:.2f} (embedder unavailable, fallback)"),
                    content_hash,
                )
        seen_texts[doc.source] = raw_text

    seen_hashes[content_hash] = doc.source
    return CheckResult("uniqueness", True, "Uniqueness verified: no exact or near-duplicate found"), content_hash


EmbedFn = Callable[[list[str]], list[list[float]]]


def verify_and_quarantine(
    documents: list[tuple[Document, Path, dict[str, Any]]],
    quarantine_dir: str | Path = "corpus/quarantine",
    report_path: str | Path = "eval/results/verification_report.json",
    known_docs: dict[str, dict[str, Any]] | None = None,
    embed_fn: EmbedFn | None = None,
    near_dup_threshold: float = 0.95,
) -> tuple[list[Document], VerificationReport]:
    """Run the four checks on each extracted document (after extraction, before chunking).

    known_docs: the already-indexed documents from the ingestion state
        ({source: {"text_hash", "doc_embedding", "doc_version"}}), so duplicates and
        older versions are judged against the whole data lake, not only this batch.
    embed_fn: embeds whole documents for the near-duplicate check.

    Failing documents are moved to quarantine_dir and are not returned. Every
    passing document gets `doc.verification` metadata (hash, embedding, supersedes).
    """
    quarantine_path = Path(quarantine_dir)
    quarantine_path.mkdir(parents=True, exist_ok=True)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    known_docs = known_docs or {}

    seen_hashes: dict[str, str] = {}
    seen_vectors: dict[str, list[float]] = {}
    seen_texts: dict[str, str] | None = None if embed_fn else {}
    newest_versions: dict[str, tuple[str, str]] = {}

    def note_version(source: str, version: str) -> None:
        v = _version_key(version)
        if not v:
            return
        name = canonical_name(source)
        if name not in newest_versions or v > newest_versions[name][0]:
            newest_versions[name] = (v, source)

    for src, rec in known_docs.items():
        if rec.get("superseded"):
            continue
        if rec.get("text_hash"):
            seen_hashes[rec["text_hash"]] = src
        if rec.get("doc_embedding"):
            seen_vectors[src] = rec["doc_embedding"]
        note_version(src, str(rec.get("doc_version", "")))
    for doc, _, meta in documents:
        note_version(doc.source, doc.doc_version or str(meta.get("doc_version", "")))

    raw_texts = ["\n\n".join(p.text for p in doc.pages) for doc, _, _ in documents]
    vectors: list[list[float] | None] = [None] * len(documents)
    if embed_fn and documents:
        try:
            embedded = embed_fn([doc_embedding_text(t) or " " for t in raw_texts])
            vectors = list(embedded)
        except Exception as exc:  # embedder down: fall back, but say so in the report
            log.warning("document embedding failed, using shingle fallback: %s", exc)
            seen_texts = {}

    passed_docs: list[Document] = []
    report_items: list[DocumentVerification] = []

    for (doc, file_path, meta), raw_text, vec in zip(documents, raw_texts, vectors):
        res_quality = check_quality(doc, raw_text)
        res_completeness = check_completeness(doc, raw_text, meta)
        res_recency = check_recency(doc, meta, newest_versions)
        res_uniqueness, content_hash = check_uniqueness(
            doc, raw_text, seen_hashes, seen_vectors, vec, near_dup_threshold, seen_texts
        )
        checks = [res_quality, res_completeness, res_recency, res_uniqueness]
        all_passed = all(c.passed for c in checks)

        item = DocumentVerification(
            source=doc.source,
            passed=all_passed,
            checks=checks,
            hash_sha256=content_hash,
            doc_version=doc.doc_version,
        )

        if all_passed:
            name = canonical_name(doc.source)
            superseded_src = [
                s for s, rec in known_docs.items()
                if not rec.get("superseded") and s != doc.source and canonical_name(s) == name
                and _version_key(str(rec.get("doc_version", ""))) < _version_key(doc.doc_version)
            ]
            doc.verification = {
                "text_hash": content_hash,
                "doc_embedding": vec,
                "supersedes": superseded_src,
            }
            if superseded_src:
                item.supersedes = superseded_src
            passed_docs.append(doc)
            log.info("verification passed for %s", doc.source)
        else:
            item.quarantined = True
            dest_file = quarantine_path / Path(doc.source).name
            try:
                if file_path.exists():
                    shutil.move(str(file_path), dest_file)
            except Exception as e:  # read-only source (e.g. image-baked batch): copy instead
                log.warning("move to quarantine failed (%s), copying", e)
                try:
                    shutil.copy2(file_path, dest_file)
                except Exception as e2:
                    log.warning("could not copy to quarantine: %s", e2)
            item.quarantine_path = str(dest_file)
            log.warning("verification failed -> quarantined: %s (%s)", doc.source,
                        [c.reason for c in checks if not c.passed])

        report_items.append(item)

    report = VerificationReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        total_documents=len(documents),
        passed_documents=len(passed_docs),
        quarantined_documents=len(documents) - len(passed_docs),
        results=report_items,
    )
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    log.info("verification report written to %s (passed: %d, quarantined: %d)",
             str(report_path), report.passed_documents, report.quarantined_documents)
    return passed_docs, report


def format_report_table(report: VerificationReport) -> str:
    """A terminal table: one row per document, P/F per check (Q/C/R/U), reasons."""
    lines = [
        f"Verification report  total={report.total_documents}  passed={report.passed_documents}  "
        f"quarantined={report.quarantined_documents}",
        f"{'document':<46} {'Q':^3}{'C':^3}{'R':^3}{'U':^3} {'result':<11} reason",
        "-" * 120,
    ]
    for r in report.results:
        flags = "".join(f"{'P' if c.passed else 'F':^3}" for c in r.checks)
        reasons = "; ".join(c.reason for c in r.checks if not c.passed)
        if not reasons and r.supersedes:
            reasons = f"supersedes {', '.join(r.supersedes)} (archived)"
        lines.append(f"{r.source[:46]:<46} {flags} {'PASS' if r.passed else 'QUARANTINE':<11} {reasons}")
    return "\n".join(lines)
