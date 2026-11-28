"""Offline tests for the Assignment 03 ingestion layer (A1 verification, A2 incremental
update, archiving and rollback). Chroma and Ollama are replaced by small in-memory
fakes so these run in CI; the real runs happen in the indexer Job on the cluster."""

from __future__ import annotations

import hashlib
import math
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline import run as run_mod
from pipeline.config import IndexerSettings

BATCH_B = Path(__file__).resolve().parents[2] / "corpus" / "batch_b"


class FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def upsert(self, ids, embeddings, metadatas, documents):  # noqa: ANN001
        for i, e, m, d in zip(ids, embeddings, metadatas, documents):
            self.rows[i] = {"meta": dict(m), "doc": d}

    def _match(self, meta: dict, where: dict | None) -> bool:
        return not where or all(meta.get(k) == v for k, v in where.items())

    def get(self, where=None, include=None, ids=None):  # noqa: ANN001
        hits = [(i, r) for i, r in self.rows.items() if self._match(r["meta"], where)]
        return {"ids": [i for i, _ in hits], "metadatas": [dict(r["meta"]) for _, r in hits]}

    def update(self, ids, metadatas):  # noqa: ANN001
        for i, m in zip(ids, metadatas):
            self.rows[i]["meta"] = dict(m)

    def delete(self, ids):  # noqa: ANN001
        for i in ids:
            self.rows.pop(i, None)


class FakeClient:
    def __init__(self) -> None:
        self.collection = FakeCollection()

    def get_or_create_collection(self, name, metadata=None):  # noqa: ANN001
        return self.collection

    def get_collection(self, name):  # noqa: ANN001
        return self.collection


def fake_embed(texts: list[str], settings: object = None) -> list[list[float]]:
    """Deterministic bag-of-words vectors: identical text -> cosine 1, light edits -> ~0.97."""
    out = []
    for t in texts:
        v = [0.0] * 256
        for w in re.findall(r"\w+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


@pytest.fixture()
def lake(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr("pipeline.store.get_client", lambda s: client)
    monkeypatch.setattr("pipeline.embed.embed", fake_embed)
    root = tmp_path / "lake"
    settings = IndexerSettings(
        embed_model="fake", chroma_host="x", chroma_port=0, collection="t",
        corpus_dir=str(root / "corpus"), chunk_size=200, chunk_overlap=20,
        ollama_url="", redis_url="", quarantine_dir=str(root / "quarantine"),
        archive_dir=str(root / "archive"), state_dir=str(root / "state"),
        incoming_dir=str(root / "incoming"), results_dir=str(tmp_path / "results"),
        near_dup_threshold=0.90,
    )
    return settings, client


def _drop(settings: IndexerSettings, names: list[str]) -> None:
    inc = Path(settings.incoming_dir)
    inc.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copy2(BATCH_B / n, inc / n)


def _sources(client: FakeClient, active_only: bool = False) -> set[str]:
    return {r["meta"]["source"] for r in client.collection.rows.values()
            if not active_only or not r["meta"].get("superseded")}


def test_batch_b_verification_and_incremental_rerun(lake):
    settings, client = lake
    _drop(settings, [p.name for p in BATCH_B.glob("doc*.md")])
    run_mod.run_pipeline(settings)

    q = {p.name for p in Path(settings.quarantine_dir).iterdir()}
    assert "doc04-campus-wifi-policy-duplicate.md" in q          # exact duplicate
    assert "doc05-sports-complex-duplicate.md" in q              # exact duplicate
    assert "doc07-hostel-allotment-corrupted.md" in q            # truncated
    assert "doc08-unlabeled-cafeteria-guidelines.md" in q        # missing metadata
    assert "doc09-campus-wifi-policy-2024-outdated.md" in q      # older than doc01
    assert not (_sources(client) & q), "quarantined documents must never be indexed"

    # A2: an unchanged corpus embeds zero chunks.
    before = dict(client.collection.rows)
    assert run_mod.run_pipeline(settings) == 0
    assert client.collection.rows == before


def test_modified_deleted_superseded_and_rollback(lake):
    settings, client = lake
    _drop(settings, ["doc01-campus-wifi-policy-2026.md", "doc02-library-digital-resources-2026.md"])
    run_mod.run_pipeline(settings)
    corpus = Path(settings.corpus_dir)
    lib_ids = {i for i, r in client.collection.rows.items() if r["meta"]["source"].startswith("doc02")}

    # A changed document replaces only its own chunks.
    f = corpus / "doc01-campus-wifi-policy-2026.md"
    f.write_text(f.read_text(encoding="utf-8") + "\n\n## 4. Support\nContact the IT help desk at extension 100.\n",
                 encoding="utf-8")
    run_mod.run_pipeline(settings)
    assert lib_ids <= set(client.collection.rows), "unchanged document's chunks must be untouched"

    # A deleted document leaves no orphan chunks.
    (corpus / "doc02-library-digital-resources-2026.md").unlink()
    run_mod.run_pipeline(settings)
    assert not any(s.startswith("doc02") for s in _sources(client))

    # A newer version supersedes the indexed one: archived, excluded by metadata.
    newer = Path(settings.incoming_dir) / "campus-wifi-policy-2027.md"
    newer.parent.mkdir(parents=True, exist_ok=True)
    text = f.read_text(encoding="utf-8").replace("doc_version: 2026-09", "doc_version: 2027-01")
    newer.write_text(text.replace("15 GB", "25 GB").replace("source: doc01-campus-wifi-policy-2026.md",
                                                             "source: campus-wifi-policy-2027.md"), encoding="utf-8")
    run_mod.run_pipeline(replace(settings, near_dup_threshold=0.999))
    assert (Path(settings.archive_dir) / f.name).exists()
    assert f.name not in _sources(client, active_only=True)
    assert f.name in _sources(client)          # kept, but superseded=True

    # Rollback restores the archived version and archives the newer one.
    assert run_mod.rollback(settings, f.name) == 0
    assert f.name in _sources(client, active_only=True)
    assert "campus-wifi-policy-2027.md" not in _sources(client, active_only=True)


def test_canonical_names_versions_vs_series():
    from pipeline.verify import canonical_name

    assert canonical_name("doc09-campus-wifi-policy-2024-outdated.md") == "campus-wifi-policy"
    assert canonical_name("doc01-campus-wifi-policy-2026.md") == "campus-wifi-policy"
    assert canonical_name("doc11-faculty-entrepreneurship-and-technical-start-ups-policy-2026.md") == \
        canonical_name("faculty-entrepreneurship-and-technical-start-ups-policy.pdf")
    assert canonical_name("annual-report-2019-20.pdf") != canonical_name("annual-report-2023-24.pdf")
