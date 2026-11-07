"""Unit tests for the semantic cache and /readyz against fake Chroma/Redis clients
(no network, no real Chroma or Redis server) -- these paths were previously
untested and are what pushed api coverage below the 60% CI gate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas import AskResponse, Citation, RetrievedRef
from app.services.cache import SemanticCache, cosine_similarity


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        return True

    def keys(self, pattern: str) -> list[str]:
        return list(self.store)

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if self.store.pop(k, None) is not None:
                n += 1
        return n


def test_cosine_similarity_identical_and_orthogonal() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def _response(answered: bool = True) -> AskResponse:
    return AskResponse(
        request_id="r1",
        answer="80%",
        citations=[Citation(source="a.pdf", section="1", page=1)],
        answered_from_context=answered,
        confidence="high",
        retrieved=[RetrievedRef(chunk_id="c1", source="a.pdf", section="1", page=1, score=0.9)],
        provider="ollama",
    )


def test_cache_store_then_lookup_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **kw: fake)
    cache = SemanticCache(Settings(cache_threshold=0.9))

    cache.store("What is the attendance requirement?", [1.0, 0.0], _response(), "r1")
    hit = cache.lookup("What is the attendance requirement?", [1.0, 0.0], "r2")

    assert hit is not None
    assert hit.provider == "cache"
    assert hit.answer == "80%"


def test_cache_never_stores_abstentions_or_followups(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **kw: fake)
    cache = SemanticCache(Settings())

    cache.store("What about the fee?", [1.0, 0.0], _response(), "r1")  # follow-up
    cache.store("Real question?", [1.0, 0.0], _response(answered=False), "r2")  # abstention

    assert fake.store == {}


def test_cache_lookup_skips_followups_without_touching_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **kw: fake)
    cache = SemanticCache(Settings())

    assert cache.lookup("And what about the fee?", [1.0, 0.0], "r1") is None


def test_cache_invalidate_flushes_all_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **kw: fake)
    cache = SemanticCache(Settings())
    cache.store("Real question?", [1.0, 0.0], _response(), "r1")

    assert cache.invalidate() == 1
    assert fake.store == {}


def test_cache_lookup_returns_none_when_redis_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*a: object, **kw: object) -> None:
        raise ConnectionError("no redis")

    monkeypatch.setattr("redis.Redis.from_url", boom)
    cache = SemanticCache(Settings())

    assert cache.lookup("Real question?", [1.0, 0.0], "r1") is None


class FakeChromaCollection:
    def __init__(self, count: int, metadata: dict[str, object]) -> None:
        self._count = count
        self.metadata = metadata

    def count(self) -> int:
        return self._count


class FakeChromaClient:
    def __init__(self, count: int = 10, embed_model: str = "nomic-embed-text") -> None:
        self._collection = FakeChromaCollection(count, {"embed_model": embed_model})

    def get_collection(self, name: str) -> FakeChromaCollection:
        return self._collection


class FakeChromaRetriever:
    name = "chroma"

    def __init__(self, client: FakeChromaClient) -> None:
        self.client = client


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_readyz_reports_ready_when_chroma_and_redis_are_healthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.state.settings = Settings(retriever="chroma", embed_model="nomic-embed-text")
    client.app.state.retriever = FakeChromaRetriever(FakeChromaClient(count=5))
    monkeypatch.setattr(
        "redis.Redis.from_url", lambda *a, **kw: FakeRedis()
    )

    r = client.get("/readyz")

    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_readyz_503_when_collection_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.state.settings = Settings(retriever="chroma", embed_model="nomic-embed-text")
    client.app.state.retriever = FakeChromaRetriever(FakeChromaClient(count=0))
    monkeypatch.setattr(
        "redis.Redis.from_url", lambda *a, **kw: FakeRedis()
    )

    r = client.get("/readyz")

    assert r.status_code == 503
    assert "chroma_collection_empty" in r.json()["failed_checks"]


def test_readyz_503_on_embed_model_mismatch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.app.state.settings = Settings(retriever="chroma", embed_model="nomic-embed-text")
    client.app.state.retriever = FakeChromaRetriever(
        FakeChromaClient(count=5, embed_model="dummy-768")
    )
    monkeypatch.setattr(
        "redis.Redis.from_url", lambda *a, **kw: FakeRedis()
    )

    r = client.get("/readyz")

    assert r.status_code == 503
    assert any("mismatch" in f for f in r.json()["failed_checks"])


def test_readyz_503_when_redis_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.app.state.settings = Settings(retriever="chroma", embed_model="nomic-embed-text")
    client.app.state.retriever = FakeChromaRetriever(FakeChromaClient(count=5))
    monkeypatch.setattr(
        "redis.Redis.from_url", lambda *a, **kw: FakeRedis(fail=True)
    )

    r = client.get("/readyz")

    assert r.status_code == 503
    assert any("redis" in f for f in r.json()["failed_checks"])
