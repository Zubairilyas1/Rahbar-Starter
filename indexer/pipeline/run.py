"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy           # week 1: three fake chunks, no model needed
    python -m pipeline.run                   # ingest -> verify -> update data lake -> update index
    python -m pipeline.run --counts          # chunk count per document id (orphan proof, A2)
    python -m pipeline.run --rollback DOC    # restore an archived version (A2 rollback demo)

Each run (Assignment 03 Part A):
  1. prepares the data lake (seeding it from the image once) and moves any batch
     waiting in <lake>/incoming/ into the corpus,
  2. diffs the corpus against the saved ingestion state (new / modified /
     unchanged / deleted), so an unchanged corpus embeds zero chunks,
  3. runs the verification stage (quality, completeness, recency, uniqueness) on
     new and modified documents, BEFORE chunking; failures go to quarantine,
  4. replaces only the chunks of changed documents, purges deleted documents,
     and archives superseded versions (excluded from retrieval by metadata),
  5. writes a verification report and an ingestion run summary to RESULTS_DIR.

This Job (and its CronJob) is the only writer to the vector store.
Exit code 0 means the index is consistent; anything else fails the Job.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, cast

from .config import IndexerSettings, get_settings
from .models import Chunk

INDEX_FILE = "_index.json"
SUPPORTED = {".pdf", ".md", ".html", ".txt"}


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "msg": msg, **fields}), flush=True)


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def _read_index(folder: Path) -> list[dict[str, Any]]:
    index = folder / INDEX_FILE
    if index.exists():
        return list(json.loads(index.read_text(encoding="utf-8")))
    return []


def _write_index(folder: Path, entries: list[dict[str, Any]]) -> None:
    (folder / INDEX_FILE).write_text(json.dumps(entries, indent=2), encoding="utf-8")


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """List (path, doc_version, superseded) for every document to index.

    corpus/fetch.py writes _index.json next to the files it downloads; use it when
    present (plus any file not listed in it). Otherwise read Markdown front matter
    (the CI fixtures work this way). Files listed but missing on disk are skipped.
    """
    root = Path(corpus_dir)
    found: list[tuple[Path, str, bool]] = []
    listed: set[str] = set()
    for e in _read_index(root):
        path = root / e["file"]
        listed.add(e["file"])
        if path.exists():
            found.append((path, str(e.get("doc_version", "unknown")), bool(e.get("superseded", False))))
    for path in sorted(root.glob("*")):
        if path.suffix.lower() not in SUPPORTED or path.name in listed:
            continue
        if path.name.lower().startswith("readme"):
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", "unknown"),
                      meta.get("superseded", "false").lower() == "true"))
    return found


# --------------------------------------------------------------------------- lake
def prepare_data_lake(settings: IndexerSettings) -> dict[str, int]:
    """Create the lake folders, seed an empty lake from the image once, and move a
    waiting batch from incoming/ into the corpus. Returns intake counts."""
    corpus = Path(settings.corpus_dir)
    for d in (corpus, Path(settings.quarantine_dir), Path(settings.archive_dir), Path(settings.state_dir)):
        d.mkdir(parents=True, exist_ok=True)

    seeded = 0
    # one marker for the whole data lake (not per collection): a candidate collection
    # indexed later must not re-seed documents that were archived or deleted since.
    marker = Path(settings.corpus_dir) / ".seeded"
    seed = Path(settings.seed_corpus_dir) if settings.seed_corpus_dir else None
    if seed and seed.exists() and not marker.exists():
        for f in seed.iterdir():
            if f.is_file() and not (corpus / f.name).exists():
                shutil.copy2(f, corpus / f.name)
                seeded += f.name != INDEX_FILE
        marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")
        log("data_lake_seeded", source=str(seed), documents=seeded)

    received = 0
    incoming = Path(settings.incoming_dir) if settings.incoming_dir else None
    if incoming and incoming.exists():
        batch_index = {e["file"]: e for e in _read_index(incoming)}
        corpus_index = _read_index(corpus)
        listed = {e["file"] for e in corpus_index}
        for f in sorted(incoming.iterdir()):
            if not f.is_file() or f.suffix.lower() not in SUPPORTED:
                continue
            shutil.move(str(f), corpus / f.name)
            received += 1
            if f.name in batch_index and f.name not in listed:
                corpus_index.append(batch_index[f.name])
        if received:
            if corpus_index:
                _write_index(corpus, corpus_index)
            (incoming / INDEX_FILE).unlink(missing_ok=True)
            log("incoming_batch_received", documents=received, source=str(incoming))
    return {"seeded": seeded, "received": received}


def _drop_from_index(corpus: Path, names: set[str]) -> None:
    entries = _read_index(corpus)
    if entries:
        _write_index(corpus, [e for e in entries if e["file"] not in names])


def _add_to_index(corpus: Path, entry: dict[str, Any]) -> None:
    entries = [e for e in _read_index(corpus) if e["file"] != entry["file"]]
    if entries or (corpus / INDEX_FILE).exists():
        _write_index(corpus, entries + [entry])


def print_chunk_counts(client: Any, settings: IndexerSettings) -> dict[str, int]:
    from .incremental import get_chunks_by_document

    counts = get_chunks_by_document(client, settings.collection)
    print(f"\nChunks per document id in collection '{settings.collection}':", flush=True)
    for src in sorted(counts):
        print(f"  {counts[src]:>5}  {src}", flush=True)
    print(f"  {sum(counts.values()):>5}  TOTAL ({len(counts)} documents)\n", flush=True)
    return counts


# ----------------------------------------------------------------------- pipeline
def run_pipeline(settings: IndexerSettings) -> int:
    from .chunk import chunk
    from .clean import clean
    from .embed import embed
    from .extract import extract
    from .incremental import (
        IngestionState,
        archive_superseded_document,
        compute_file_hash,
        diff_corpus,
        purge_document_chunks,
    )
    from .store import get_client, store
    from .verify import canonical_name, format_report_table, verify_and_quarantine

    stamp = _stamp()
    results_dir = Path(settings.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    intake = prepare_data_lake(settings)

    corpus_path = Path(settings.corpus_dir)
    discovered = discover(settings.corpus_dir)
    if not discovered:
        raise SystemExit(f"no documents found in {settings.corpus_dir}")

    client = get_client(settings)
    state_file = Path(settings.state_dir) / ".ingestion_state.json"
    state = IngestionState.load(state_file)

    # 1. Incremental diff against the saved state. Archived (superseded) documents
    #    are no longer in the corpus folder on purpose; they are not "deleted".
    new_docs, modified_docs, unchanged_sources, deleted_sources = diff_corpus(discovered, state)
    deleted_sources = [s for s in deleted_sources if s not in state.archive]
    log("incremental_diff", new=len(new_docs), modified=len(modified_docs),
        unchanged=len(unchanged_sources), deleted=len(deleted_sources))

    summary: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection": settings.collection,
        "embed_model": settings.embed_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        **intake,
        "new": [p.name for p, _, _ in new_docs],
        "modified": [p.name for p, _, _ in modified_docs],
        "unchanged": len(unchanged_sources),
        "deleted": deleted_sources,
        "purged_chunks": {},
        "quarantined": [],
        "archived": [],
        "embedded_chunks": 0,
    }

    # 2. Deleted documents: purge every chunk, prove zero orphans by count.
    for src in deleted_sources:
        purged = purge_document_chunks(src, client, settings.collection,
                                       state.documents.get(src, {}).get("chunk_ids"))
        del state.documents[src]
        summary["purged_chunks"][src] = purged
        log("purged_deleted_document", source=src, chunks_removed=purged, orphans_remaining=0)

    docs_to_process = new_docs + modified_docs
    if not docs_to_process:
        if not deleted_sources:
            log("incremental_update_complete", embedded_chunks=0, status="unchanged",
                message="Corpus unchanged: embedded zero chunks.")
        state.save(state_file)
        summary["chunks_by_document"] = print_chunk_counts(client, settings)
        _write_summary(results_dir, stamp, summary)
        return 0

    # 3. A modified document replaces only its own chunks: purge them first.
    modified_names = {p.name for p, _, _ in modified_docs}
    for src in modified_names:
        purged = purge_document_chunks(src, client, settings.collection,
                                       state.documents.get(src, {}).get("chunk_ids"))
        summary["purged_chunks"][src] = purged
        log("purged_modified_document_chunks", source=src, chunks_removed=purged)

    # 4. Extract, then VERIFY (before chunking) against the whole data lake.
    candidates = []
    versions: dict[str, tuple[str, bool]] = {}
    for path, doc_version, superseded in docs_to_process:
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        meta.setdefault("doc_version", doc_version)
        meta.setdefault("source", path.name)
        candidates.append((extract(str(path), doc_version, superseded), path, meta))
        versions[path.name] = (doc_version, superseded)

    known = {s: r for s, r in state.documents.items() if s not in modified_names}
    report_path = results_dir / f"verification_report_{stamp}.json"
    passed_docs, v_report = verify_and_quarantine(
        candidates,
        quarantine_dir=settings.quarantine_dir,
        report_path=report_path,
        known_docs=known,
        embed_fn=lambda texts: embed(texts, settings),
        near_dup_threshold=settings.near_dup_threshold,
    )
    print("\n" + format_report_table(v_report) + "\n", flush=True)
    quarantined = {r.source for r in v_report.results if r.quarantined}
    summary["quarantined"] = sorted(quarantined)
    summary["verification_report"] = str(report_path)
    _drop_from_index(corpus_path, quarantined)
    for src in quarantined & modified_names:  # bad new version: the document leaves the index
        state.documents.pop(src, None)
    log("verification_stage_complete", total_examined=len(candidates),
        passed=len(passed_docs), quarantined=len(quarantined), report=str(report_path))

    # 5. Clean, chunk, embed and store only verified documents.
    new_chunks: list[Chunk] = []
    chunks_per_doc: dict[str, list[str]] = {}
    for doc in passed_docs:
        pieces = chunk(clean(doc), settings.chunk_size, settings.chunk_overlap)
        log("chunked", source=doc.source, chunks=len(pieces))
        new_chunks.extend(pieces)
        chunks_per_doc[doc.source] = [p.id for p in pieces]

    if new_chunks:
        vectors = embed([c.text for c in new_chunks], settings)
        store(new_chunks, vectors, settings)
    summary["embedded_chunks"] = len(new_chunks)

    for doc in passed_docs:
        path = corpus_path / doc.source
        version, superseded = versions.get(doc.source, (doc.doc_version, doc.superseded))
        state.documents[doc.source] = {
            "content_hash": compute_file_hash(path) if path.exists() else "",
            "text_hash": doc.verification.get("text_hash", ""),
            "doc_embedding": doc.verification.get("doc_embedding"),
            "canonical": canonical_name(doc.source),
            "chunk_ids": chunks_per_doc.get(doc.source, []),
            "doc_version": version,
            "superseded": superseded,
            "last_modified": path.stat().st_mtime if path.exists() else time.time(),
            "chunk_count": len(chunks_per_doc.get(doc.source, [])),
        }

    # 6. Archive the older versions that verified newer documents supersede.
    for doc in passed_docs:
        for old in cast("list[str]", doc.verification.get("supersedes") or []):
            old_path = corpus_path / str(old)
            if not old_path.exists():
                continue
            archive_superseded_document(old_path, Path(settings.archive_dir), client,
                                        settings.collection, doc.source, state)
            old_path.unlink()
            _drop_from_index(corpus_path, {str(old)})
            if str(old) in state.documents:
                state.documents[str(old)]["superseded"] = True
            summary["archived"].append({"document": old, "superseded_by": doc.source})
            log("archived_superseded_version", document=old, superseded_by=doc.source)

    state.save(state_file)
    log("incremental_update_complete", embedded_chunks=len(new_chunks),
        updated_documents=len(passed_docs), quarantined=len(quarantined),
        archived=len(summary["archived"]))
    summary["chunks_by_document"] = print_chunk_counts(client, settings)
    _write_summary(results_dir, stamp, summary)
    return len(new_chunks)


def _write_summary(results_dir: Path, stamp: str, summary: dict[str, Any]) -> None:
    path = results_dir / f"ingestion_run_{stamp}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log("ingestion_run_summary_written", path=str(path), embedded_chunks=summary["embedded_chunks"])


def rollback(settings: IndexerSettings, doc_name: str) -> int:
    """Restore an archived version: its chunks become retrievable again and the
    document that superseded it is archived in its place (a version swap)."""
    from .incremental import IngestionState, archive_superseded_document, rollback_archived_document
    from .store import get_client

    client = get_client(settings)
    state_file = Path(settings.state_dir) / ".ingestion_state.json"
    state = IngestionState.load(state_file)
    entry = state.archive.get(doc_name)
    if not entry:
        log("rollback_failed", document=doc_name, reason="not in archive",
            archived=sorted(state.archive))
        return 1
    newer = entry.get("superseded_by")
    corpus = Path(settings.corpus_dir)
    if not rollback_archived_document(doc_name, Path(settings.archive_dir), corpus, client,
                                      settings.collection, state):
        return 1
    rec = state.documents.get(doc_name, {})
    rec["superseded"] = False
    _add_to_index(corpus, {"file": doc_name, "doc_version": rec.get("doc_version", "unknown"), "superseded": False})
    if newer and (corpus / newer).exists():
        archive_superseded_document(corpus / newer, Path(settings.archive_dir), client,
                                    settings.collection, f"rollback-to:{doc_name}", state)
        (corpus / newer).unlink()
        _drop_from_index(corpus, {newer})
        if newer in state.documents:
            state.documents[newer]["superseded"] = True
    state.save(state_file)
    log("rollback_complete", restored=doc_name, archived=newer)
    print_chunk_counts(client, settings)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    parser.add_argument("--dummy", action="store_true", help="write three fake chunks")
    parser.add_argument("--counts", action="store_true", help="print chunk count per document id and exit")
    parser.add_argument("--rollback", metavar="DOC", help="restore an archived document version and exit")
    args = parser.parse_args()
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        corpus=settings.corpus_dir, pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if args.counts:
            from .store import get_client

            print_chunk_counts(get_client(settings), settings)
            return 0
        if args.rollback:
            rc = rollback(settings, args.rollback)
            _flush_cache(settings)
            return rc
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
        else:
            count = run_pipeline(settings)
    except NotImplementedError as exc:
        log("indexer stage not implemented yet", error=str(exc))
        return 2
    log("indexer finished", embedded_chunks=count, seconds=round(time.perf_counter() - started, 1))
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
