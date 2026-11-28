"""Indexer configuration, from the same ConfigMap the API reads (section 4.1).

Data-lake layout (Assignment 03 A1/A2/F1). On the cluster DATA_LAKE_DIR is the
mount point of the `rahbar-datalake` PersistentVolumeClaim, so everything below
survives pod restarts:

    <data lake>/corpus/       active documents (what is indexed) + _index.json
    <data lake>/incoming/     drop a new batch here; the next run verifies it
    <data lake>/quarantine/   documents that failed verification (never indexed)
    <data lake>/archive/      superseded versions, restorable with --rollback
    <data lake>/state/<collection>/  .ingestion_state.json (hashes, chunk ids, versions)

When DATA_LAKE_DIR is unset (local runs, CI) the old single-folder behaviour is
kept: CORPUS_DIR holds the documents and the other folders sit inside it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IndexerSettings:
    embed_model: str        # EMBED_MODEL: must equal the API's value (section 4.4)
    chroma_host: str
    chroma_port: int
    collection: str
    corpus_dir: str         # active corpus folder (documents + _index.json)
    chunk_size: int
    chunk_overlap: int
    ollama_url: str
    redis_url: str          # flushed after a successful reindex (ADR 0002/0003)
    quarantine_dir: str = ""
    archive_dir: str = ""
    state_dir: str = ""
    incoming_dir: str = ""
    seed_corpus_dir: str = ""   # image-baked corpus copied into an empty data lake once
    results_dir: str = "eval/results"
    near_dup_threshold: float = 0.95   # embedding cosine for a near-duplicate document
    embed_version: str = "v1.5"


def get_settings() -> IndexerSettings:
    lake = os.environ.get("DATA_LAKE_DIR", "")
    corpus = os.environ.get("CORPUS_DIR") or (str(Path(lake) / "corpus") if lake else "/corpus")

    def lake_dir(env: str, name: str) -> str:
        if os.environ.get(env):
            return os.environ[env]
        return str(Path(lake) / name) if lake else str(Path(corpus) / name)

    return IndexerSettings(
        embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        chroma_host=os.environ.get("CHROMA_HOST", "chroma"),
        chroma_port=int(os.environ.get("CHROMA_PORT", 8000)),
        collection=os.environ.get("CHROMA_COLLECTION", "rahbar"),
        corpus_dir=corpus,
        chunk_size=int(os.environ.get("CHUNK_SIZE", 400)),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", 50)),
        ollama_url=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"),
        redis_url=os.environ.get("REDIS_URL", "redis://redis:6379"),
        quarantine_dir=lake_dir("QUARANTINE_DIR", "quarantine"),
        archive_dir=lake_dir("ARCHIVE_DIR", "archive"),
        # One ingestion state per collection: the baseline and a candidate collection
        # (own chunking, Part C/F3) index the same data lake independently.
        state_dir=(lake_dir("STATE_DIR", f"state/{os.environ.get('CHROMA_COLLECTION', 'rahbar')}")
                   if lake else os.environ.get("STATE_DIR", corpus)),
        incoming_dir=os.environ.get("INCOMING_DIR") or (str(Path(lake) / "incoming") if lake else ""),
        seed_corpus_dir=os.environ.get("SEED_CORPUS_DIR", ""),
        results_dir=os.environ.get("RESULTS_DIR", "eval/results"),
        near_dup_threshold=float(os.environ.get("NEAR_DUP_THRESHOLD", 0.95)),
        embed_version=os.environ.get("EMBED_VERSION", "v1.5"),
    )
