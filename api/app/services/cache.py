"""Semantic Cache Service for RAHBAR (Section 3.3).

Caches question-answer pairs in Redis using cosine similarity over query embeddings.
Enforces never-cache rules for follow-up turns and abstentions.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from ..config import Settings
from ..schemas import AskResponse, Citation, RetrievedRef

log = logging.getLogger("rahbar.cache")

# Patterns indicating conversational follow-ups that must never be cached as standalone
FOLLOWUP_PATTERN = re.compile(
    r"^(and\b|what about\b|how about\b|why\b|does it\b|can they\b|and what\b|tell me more\b)",
    re.IGNORECASE,
)


def is_followup(question: str) -> bool:
    """Returns True if the question appears to depend on prior conversation context."""
    return bool(FOLLOWUP_PATTERN.search(question.strip()))


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a, b in zip(v1, v1)))
    norm2 = math.sqrt(sum(b * b for a, b in zip(v2, v2)))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class SemanticCache:
    """Redis-backed semantic cache."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.threshold = settings.cache_threshold
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import redis
            try:
                self._client = redis.Redis.from_url(
                    self.settings.redis_url,
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                )
            except Exception as exc:
                log.warning(f"Failed connecting to Redis at {self.settings.redis_url}: {exc}")
                self._client = None
        return self._client

    def lookup(self, question: str, query_vector: list[float], request_id: str) -> AskResponse | None:
        """Lookup cached response using semantic similarity against stored queries."""
        if is_followup(question):
            log.info(f"[{request_id}] Query is a follow-up; skip_cache=True")
            return None

        r = self.client
        if r is None:
            return None

        try:
            keys = r.keys("rahbar:cache:*")
            best_score = -1.0
            best_entry: dict[str, Any] | None = None

            for key in keys:
                raw_data = r.get(key)
                if not raw_data:
                    continue
                entry = json.loads(raw_data)
                cached_vec = entry.get("vector")
                if not cached_vec:
                    continue

                sim = cosine_similarity(query_vector, cached_vec)
                if sim > best_score:
                    best_score = sim
                    best_entry = entry

            if best_score >= self.threshold and best_entry:
                log.info(f"[{request_id}] Semantic cache HIT: score={best_score:.4f} >= threshold={self.threshold}")
                resp_dict = best_entry["response"]
                return AskResponse(
                    request_id=request_id,
                    answer=resp_dict["answer"],
                    citations=[Citation(**c) for c in resp_dict.get("citations", [])],
                    answered_from_context=resp_dict.get("answered_from_context", True),
                    confidence=resp_dict.get("confidence", "high"),
                    retrieved=[RetrievedRef(**rf) for rf in resp_dict.get("retrieved", [])],
                    provider="cache",
                )
            else:
                log.info(f"[{request_id}] Semantic cache MISS (best_score={best_score:.4f})")
        except Exception as exc:
            log.warning(f"[{request_id}] Redis cache lookup failed: {exc}")

        return None

    def store(
        self,
        question: str,
        query_vector: list[float],
        response: AskResponse,
        request_id: str,
    ) -> None:
        """Store query and response. Enforces never_cache rules on abstentions and followups."""
        # Never-cache rule: never cache if model abstained from answering
        if not response.answered_from_context:
            log.info(f"[{request_id}] never_cache: abstention responses are not stored in cache")
            return

        # Never-cache rule: never cache conversational follow-up turns
        if is_followup(question):
            log.info(f"[{request_id}] never_cache: follow-up queries are not stored in cache")
            return

        r = self.client
        if r is None:
            return

        try:
            cache_key = f"rahbar:cache:{hash(question)}"
            payload = {
                "question": question,
                "vector": query_vector,
                "response": {
                    "answer": response.answer,
                    "citations": [c.model_dump() for c in response.citations],
                    "answered_from_context": response.answered_from_context,
                    "confidence": response.confidence,
                    "retrieved": [rf.model_dump() for rf in response.retrieved],
                },
            }
            r.setex(cache_key, self.settings.cache_ttl, json.dumps(payload))
            log.info(f"[{request_id}] Stored response in semantic cache with TTL={self.settings.cache_ttl}s")
        except Exception as exc:
            log.warning(f"[{request_id}] Redis cache store failed: {exc}")

    def invalidate(self) -> int:
        """Clear the semantic cache upon reindexing to prevent serving stale answers."""
        r = self.client
        if r is None:
            return 0
        try:
            keys = r.keys("rahbar:cache:*")
            if keys:
                deleted = r.delete(*keys)
                log.info(f"Cache invalidated: flushed {deleted} cached entries")
                return deleted
        except Exception as exc:
            log.warning(f"Cache invalidation failed: {exc}")
        return 0
