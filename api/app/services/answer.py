"""Turns a question into an AskResponse. This is where the query pipeline lives.

Implements the full 8-step pipeline: validation, semantic cache, retrieval,
relevance floor abstention, augmented prompt, generation with retry and fallback,
citation verification against retrieved passages, and cache storage.
"""

from __future__ import annotations

import logging
from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..schemas import AskResponse, Passage, RetrievedRef
from .cache import SemanticCache
from .citations import verify_citations

log = logging.getLogger("rahbar.answer")

# Global cache instance for API lifetime
_cache: SemanticCache | None = None


def get_cache(settings: Settings) -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache(settings)
    return _cache


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings
) -> AskResponse:
    request_id = request_id_var.get()
    q = question.strip()

    # Step 1: Validate question length
    if len(q) < 3 or len(q) > 500:
        return AskResponse(
            request_id=request_id,
            answer="Question must be between 3 and 500 characters.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=[],
            provider="validation",
        )

    # Step 2: Semantic cache lookup
    cache = get_cache(settings)
    query_vector: list[float] = []
    # If the retriever is ChromaRetriever, we can obtain the embedding for semantic caching
    if hasattr(retriever, "_embed_query"):
        try:
            query_vector = retriever._embed_query(q)  # type: ignore
            cached_resp = cache.lookup(q, query_vector, request_id)
            if cached_resp is not None:
                return cached_resp
        except Exception as exc:
            log.warning(f"[{request_id}] Query embedding for cache lookup failed: {exc}")

    # Step 3: Retrieval
    passages: list[Passage] = retriever.retrieve(q, k=settings.top_k)

    # Step 4: Observability and retrieval score logging
    chunk_ids = [p.chunk_id for p in passages]
    scores = [round(p.score, 4) for p in passages]
    max_score = max(scores) if scores else 0.0

    log.info(
        "retrieved_passages",
        extra={
            "request_id": request_id,
            "retriever": retriever.name,
            "top_k": settings.top_k,
            "chunk_ids": chunk_ids,
            "scores": scores,
            "max_similarity": max_score,
            "relevance_floor": settings.relevance_floor,
        },
    )

    retrieved_refs = [
        RetrievedRef(
            chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page, score=p.score
        )
        for p in passages
    ]

    # Step 5: Relevance floor check and deterministic abstention
    if not passages or max_score < settings.relevance_floor:
        log.info(
            f"[{request_id}] Abstaining: max similarity {max_score:.4f} < floor {settings.relevance_floor:.4f}"
        )
        return AskResponse(
            request_id=request_id,
            answer="I do not have sufficient information in the provided documents to answer this question.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=retrieved_refs,
            provider="abstention",
        )

    # Step 6: Generation (with retry and safe fallback in provider)
    answer = provider.generate(q, passages)

    # Step 7: Citation verification (drop hallucinated/unretrieved citations)
    verified_citations = verify_citations(answer.citations, passages)
    if answer.citations and not verified_citations:
        log.warning(f"[{request_id}] All model citations were ungrounded and dropped.")

    response = AskResponse(
        request_id=request_id,
        answer=answer.answer,
        citations=verified_citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=retrieved_refs,
        provider=provider.name,
    )

    # Step 8: Update semantic cache (subject to never_cache rules)
    if query_vector:
        cache.store(q, query_vector, response, request_id)

    log.info(
        "answered",
        extra={
            "request_id": request_id,
            "provider": provider.name,
            "citations_count": len(verified_citations),
            "answered_from_context": response.answered_from_context,
            "confidence": response.confidence,
        },
    )
    return response
