"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy    # week 1: three fake chunks, no model needed
    python -m pipeline.run            # the real pipeline: extract, clean, chunk, embed, store

Exit code 0 means the index was written; anything else fails the Job, and
Kubernetes retries it up to the Job's backoffLimit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import IndexerSettings, get_settings
from .models import Chunk


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "msg": msg, **fields}), flush=True)


def _front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """List (path, doc_version, superseded) for every document to index.

    corpus/fetch.py writes _index.json next to the files it downloads; use it when
    present. Otherwise read Markdown front matter (the CI fixtures work this way).
    """
    root = Path(corpus_dir)
    index = root / "_index.json"
    if index.exists():
        entries = json.loads(index.read_text(encoding="utf-8"))
        return [(root / e["file"], str(e.get("doc_version", "unknown")),
                 bool(e.get("superseded", False))) for e in entries]
    found = []
    for path in sorted(root.glob("*")):
        if path.suffix.lower() not in {".pdf", ".md", ".html", ".txt"}:
            continue
        if path.name.lower().startswith("readme"):
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", "unknown"),
                      meta.get("superseded", "false").lower() == "true"))
    return found


def run_pipeline(settings: IndexerSettings) -> int:
    from .chunk import chunk
    from .clean import clean
    from .embed import embed
    from .extract import extract
    from .incremental import (
        IngestionState,
        compute_file_hash,
        diff_corpus,
        get_chunks_by_document,
        purge_document_chunks,
    )
    from .store import get_client, store
    from .verify import verify_and_quarantine

    corpus_path = Path(settings.corpus_dir)
    discovered = discover(settings.corpus_dir)
    if not discovered:
        raise SystemExit(f"no documents found in {settings.corpus_dir}")

    client = get_client(settings)
    state_file = corpus_path / ".ingestion_state.json"
    state = IngestionState.load(state_file)

    # 1. Incremental Diff against current disk state
    new_docs, modified_docs, unchanged_sources, deleted_sources = diff_corpus(discovered, state)
    log(
        "incremental_diff",
        new=len(new_docs),
        modified=len(modified_docs),
        unchanged=len(unchanged_sources),
        deleted=len(deleted_sources),
    )

    # 2. Handle deleted documents: purge all chunks to prevent orphans
    for deleted_src in deleted_sources:
        purged = purge_document_chunks(
            deleted_src,
            client,
            settings.collection,
            state.documents.get(deleted_src, {}).get("chunk_ids"),
        )
        del state.documents[deleted_src]
        log("purged_deleted_document", source=deleted_src, chunks_removed=purged)

    # 3. Check for 0-chunk re-run guarantee
    docs_to_process = new_docs + modified_docs
    if not docs_to_process and not deleted_sources:
        current_counts = get_chunks_by_document(client, settings.collection)
        total_existing = sum(current_counts.values())
        log(
            "incremental_update_complete",
            embedded_chunks=0,
            status="unchanged",
            message="Corpus unchanged: embedded zero chunks.",
            total_collection_chunks=total_existing,
        )
        return total_existing

    # 4. Handle modified documents: purge old chunks before re-embedding
    for path, _, _ in modified_docs:
        src = path.name
        purged = purge_document_chunks(
            src,
            client,
            settings.collection,
            state.documents.get(src, {}).get("chunk_ids"),
        )
        log("purged_modified_document_chunks", source=src, chunks_removed=purged)

    # 5. Extract and Verify only incoming/modified documents
    extracted_candidates = []
    for path, doc_version, superseded in docs_to_process:
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        if "doc_version" not in meta:
            meta["doc_version"] = doc_version
        if "source" not in meta:
            meta["source"] = path.name
        doc = extract(str(path), doc_version, superseded)
        extracted_candidates.append((doc, path, meta))

    passed_docs, v_report = verify_and_quarantine(
        extracted_candidates,
        quarantine_dir=corpus_path / "quarantine",
        report_path=Path("eval/results") / f"verification_report_{corpus_path.name}.json",
    )
    log(
        "verification_stage_complete",
        total_examined=len(extracted_candidates),
        passed=len(passed_docs),
        quarantined=v_report.quarantined_documents,
    )

    if not passed_docs:
        log("no_documents_passed_verification", quarantined=v_report.quarantined_documents)
        state.save(state_file)
        return 0

    # 6. Clean, Chunk and Embed only verified passed documents
    new_chunks: list[Chunk] = []
    chunks_per_doc: dict[str, list[str]] = {}

    for doc in passed_docs:
        cleaned_doc = clean(doc)
        pieces = chunk(cleaned_doc, settings.chunk_size, settings.chunk_overlap)
        log("chunked", source=doc.source, chunks=len(pieces))
        new_chunks.extend(pieces)
        chunks_per_doc[doc.source] = [p.id for p in pieces]

    if not new_chunks:
        state.save(state_file)
        return 0

    vectors = embed([c.text for c in new_chunks], settings)
    stored_count = store(new_chunks, vectors, settings)

    # 7. Update persistent ingestion state
    for path, doc_version, superseded in docs_to_process:
        src = path.name
        if src in chunks_per_doc:
            state.documents[src] = {
                "content_hash": compute_file_hash(path),
                "chunk_ids": chunks_per_doc[src],
                "doc_version": doc_version,
                "superseded": superseded,
                "last_modified": path.stat().st_mtime if path.exists() else time.time(),
                "chunk_count": len(chunks_per_doc[src]),
            }

    state.save(state_file)
    log(
        "incremental_update_complete",
        embedded_chunks=len(new_chunks),
        updated_documents=len(passed_docs),
    )
    return stored_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    parser.add_argument("--dummy", action="store_true", help="write three fake chunks")
    args = parser.parse_args()
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
        else:
            count = run_pipeline(settings)
    except NotImplementedError as exc:
        log("indexer stage not implemented yet", error=str(exc))
        return 2
    log("indexer finished", chunks=count, seconds=round(time.perf_counter() - started, 1))
    _flush_cache(settings)
    return 0


def _flush_cache(settings: IndexerSettings) -> None:
    """Invalidate the API's semantic cache so a reindex is never served stale
    answers (ADR 0002/0003). Best-effort: a cache flush failure must not fail
    the Job -- the index itself already wrote successfully."""
    try:
        import redis

        client: Any = redis.Redis.from_url(settings.redis_url, socket_timeout=2.0,
                                            socket_connect_timeout=2.0)
        keys = client.keys("rahbar:cache:*")
        if keys:
            client.delete(*keys)
        log("cache invalidated", keys=len(keys))
    except Exception as exc:
        log("cache invalidation skipped", error=str(exc))


if __name__ == "__main__":
    sys.exit(main())
