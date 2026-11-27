"""Stage 1.8: Incremental Ingestion & Version Archiving.
Assignment 03 Part A2 (RAGOps paper 4.2.1-4.2.4).

Guarantees:
1. Re-running on unchanged corpus embeds ZERO chunks (reported counts).
2. A changed document replaces only its own chunks in the vector store.
3. A deleted document leaves ZERO orphan chunks in ChromaDB (proven by ID count).
4. A superseded version is archived and excluded from retrieval through metadata,
   with rollback demo capability.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


log = logging.getLogger("rahbar.indexer.incremental")

STATE_FILE_NAME = ".ingestion_state.json"
ARCHIVE_DIR_NAME = "archive"


@dataclass
class DocRecord:
    source: str
    content_hash: str
    chunk_ids: list[str] = field(default_factory=list)
    doc_version: str = "unknown"
    superseded: bool = False
    last_modified: float = 0.0
    chunk_count: int = 0


@dataclass
class IngestionState:
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    archive: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_run_timestamp: str = ""

    @classmethod
    def load(cls, state_path: Path) -> IngestionState:
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                return cls(
                    documents=data.get("documents", {}),
                    archive=data.get("archive", {}),
                    last_run_timestamp=data.get("last_run_timestamp", ""),
                )
            except Exception as e:
                log.warning(f"Could not load state from {state_path}: {e}")
        return cls()

    def save(self, state_path: Path) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_run_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state_path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def compute_file_hash(path: Path) -> str:
    """Computes SHA-256 hash of a file on disk."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def diff_corpus(
    discovered_files: list[tuple[Path, str, bool]],
    state: IngestionState,
) -> tuple[list[tuple[Path, str, bool]], list[tuple[Path, str, bool]], list[str], list[str]]:
    """Compares current disk files against the saved state.
    
    Returns:
        new_docs: [(path, version, superseded), ...]
        modified_docs: [(path, version, superseded), ...]
        unchanged_sources: [source_name, ...]
        deleted_sources: [source_name, ...]
    """
    new_docs = []
    modified_docs = []
    unchanged_sources = []
    
    current_source_names = set()

    for path, version, sup in discovered_files:
        src = path.name
        current_source_names.add(src)
        current_hash = compute_file_hash(path)

        if src not in state.documents:
            new_docs.append((path, version, sup))
        else:
            prev_hash = state.documents[src].get("content_hash", "")
            if current_hash != prev_hash:
                modified_docs.append((path, version, sup))
            else:
                unchanged_sources.append(src)

    # Detect deleted documents
    deleted_sources = [
        src for src in state.documents if src not in current_source_names
    ]

    return new_docs, modified_docs, unchanged_sources, deleted_sources


def purge_document_chunks(
    source_name: str,
    client: Any,
    collection_name: str,
    known_chunk_ids: list[str] | None = None,
) -> int:
    """Purges all chunks for a given document from ChromaDB.
    
    Guarantees 0 orphan chunks remaining.
    """
    try:
        coll = client.get_collection(name=collection_name)
    except Exception as e:
        log.warning(f"Could not get collection {collection_name} to purge chunks: {e}")
        return 0

    # 1. Fetch chunks by source metadata
    deleted_count = 0
    try:
        found = coll.get(where={"source": source_name})
        found_ids = found.get("ids", [])
        if found_ids:
            coll.delete(ids=found_ids)
            deleted_count += len(found_ids)
            log.info(f"Purged {len(found_ids)} chunks by metadata for '{source_name}'")
    except Exception as e:
        log.warning(f"Metadata delete query failed for {source_name}: {e}")

    # 2. Delete by known chunk IDs if any remain
    if known_chunk_ids:
        remaining_ids = [cid for cid in known_chunk_ids if cid not in (found.get("ids") or [])]
        if remaining_ids:
            try:
                coll.delete(ids=remaining_ids)
                deleted_count += len(remaining_ids)
            except Exception:
                pass

    # 3. Verify zero orphan chunks remain
    remaining = coll.get(where={"source": source_name}).get("ids", [])
    if remaining:
        log.error(f"FAILURE: {len(remaining)} orphan chunks remain for deleted document '{source_name}'")
        raise RuntimeError(f"Orphan chunk cleanup failed for {source_name}")
    
    log.info(f"Verified 0 orphan chunks remaining for '{source_name}'")
    return deleted_count


def get_chunks_by_document(client: Any, collection_name: str) -> dict[str, int]:
    """Returns chunk counts grouped by document source to prove zero orphan chunks."""
    try:
        coll = client.get_collection(name=collection_name)
        data = coll.get(include=["metadatas"])
        counts: dict[str, int] = {}
        for meta in data.get("metadatas", []):
            if meta and "source" in meta:
                src = str(meta["source"])
                counts[src] = counts.get(src, 0) + 1
        return counts
    except Exception as e:
        log.warning(f"Could not retrieve chunk counts: {e}")
        return {}


def archive_superseded_document(
    doc_path: Path,
    corpus_dir: Path,
    client: Any,
    collection_name: str,
    superseded_by: str,
    state: IngestionState,
) -> Path:
    """Moves an older document to corpus/archive/ and tags its chunks as superseded."""
    archive_dir = corpus_dir / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    dest_path = archive_dir / doc_path.name
    shutil.copy2(doc_path, dest_path)
    
    # Tag chunks in Chroma as superseded: True
    try:
        coll = client.get_collection(name=collection_name)
        existing = coll.get(where={"source": doc_path.name}, include=["metadatas", "documents"])
        if existing and existing.get("ids"):
            ids = existing["ids"]
            metas = existing["metadatas"]
            for m in metas:
                m["superseded"] = True
            coll.update(ids=ids, metadatas=metas)
            log.info(f"Tagged {len(ids)} chunks for '{doc_path.name}' as superseded: True in Chroma")
    except Exception as e:
        log.warning(f"Could not update superseded metadata in Chroma: {e}")

    state.archive[doc_path.name] = {
        "archived_path": str(dest_path),
        "superseded_by": superseded_by,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    log.info(f"Archived superseded document '{doc_path.name}' to {dest_path}")
    return dest_path


def rollback_archived_document(
    doc_name: str,
    corpus_dir: Path,
    client: Any,
    collection_name: str,
    state: IngestionState,
) -> bool:
    """Restores an archived document back to the active corpus and marks chunks as active."""
    archive_dir = corpus_dir / ARCHIVE_DIR_NAME
    archived_file = archive_dir / doc_name
    if not archived_file.exists():
        log.error(f"Cannot rollback: {archived_file} not found in archive")
        return False

    restore_path = corpus_dir / doc_name
    shutil.copy2(archived_file, restore_path)

    # Revert Chroma chunk metadata: superseded: False
    try:
        coll = client.get_collection(name=collection_name)
        existing = coll.get(where={"source": doc_name}, include=["metadatas"])
        if existing and existing.get("ids"):
            ids = existing["ids"]
            metas = existing["metadatas"]
            for m in metas:
                m["superseded"] = False
            coll.update(ids=ids, metadatas=metas)
            log.info(f"Rollback complete: {len(ids)} chunks for '{doc_name}' restored to active (superseded: False)")
    except Exception as e:
        log.warning(f"Could not revert superseded metadata during rollback: {e}")

    if doc_name in state.archive:
        del state.archive[doc_name]
    return True
