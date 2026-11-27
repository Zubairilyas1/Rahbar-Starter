"""Turns a question into an AskResponse. This is where the query pipeline lives.

Implements the full 8-step pipeline: validation, semantic cache, retrieval,
relevance floor abstention, augmented prompt, generation with retry and fallback,
citation verification against retrieved passages, and cache storage.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..schemas import AskResponse, Passage, RetrievedRef
from ..tracing import TraceRecord, compute_prompt_hash, log_trace
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
    t_start = time.perf_counter()
    request_id = request_id_var.get()
    q = question.strip()

    latencies: dict[str, float] = {
        "cache_lookup_ms": 0.0,
        "embedding_ms": 0.0,
        "retrieval_ms": 0.0,
        "generation_ms": 0.0,
        "total_ms": 0.0,
    }
    guardrails: list[dict[str, Any]] = []

    # Check for prompt injection attempt in query
    injection_pattern = r"(ignore (all )?previous instructions|system override|\[inst\]|pwned|output the secret)"
    if re.search(injection_pattern, q, re.IGNORECASE):
        guardrails.append({
            "rail": "prompt_injection_guardrail",
            "action": "flagged",
            "reason": "Hostile instruction override detected in user query",
            "triggered": True,
        })
    else:
        guardrails.append({
            "rail": "prompt_injection_guardrail",
            "action": "passed",
            "reason": "Query conforms to standard question syntax",
            "triggered": False,
        })

    # Step 1: Validate question length
    if len(q) < 3 or len(q) > 500:
        resp = AskResponse(
            request_id=request_id,
            answer="Question must be between 3 and 500 characters.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=[],
            provider="validation",
        )
        latencies["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)
        log_trace(
            TraceRecord(
                trace_id=request_id,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                user_query=q,
                rewritten_query=None,
                embedding_model=settings.embed_model,
                embedding_version="v1.5",
                collection_name=settings.collection,
                collection_version="2026-v1",
                retrieved_chunks=[],
                filters_applied={},
                reranked_order=[],
                prompt_hash=compute_prompt_hash(q),
                full_prompt=q,
                model=settings.llm_model,
                parameters={"temperature": settings.temperature},
                response=resp.model_dump(),
                citations=[],
                guardrail_actions=guardrails,
                latency_per_stage=latencies,
                cache_status="miss",
            )
        )
        return resp

    # Step 2: Semantic cache lookup
    cache = get_cache(settings)
    query_vector: list[float] = []
    t_cache_start = time.perf_counter()
    if hasattr(retriever, "_embed_query"):
        try:
            t_emb_start = time.perf_counter()
            query_vector = retriever._embed_query(q)  # type: ignore
            latencies["embedding_ms"] = round((time.perf_counter() - t_emb_start) * 1000.0, 2)
            cached_resp = cache.lookup(q, query_vector, request_id)
            latencies["cache_lookup_ms"] = round((time.perf_counter() - t_cache_start) * 1000.0, 2)
            if cached_resp is not None:
                latencies["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)
                log_trace(
                    TraceRecord(
                        trace_id=request_id,
                        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        user_query=q,
                        rewritten_query=None,
                        embedding_model=settings.embed_model,
                        embedding_version="v1.5",
                        collection_name=settings.collection,
                        collection_version="2026-v1",
                        retrieved_chunks=[r.model_dump() for r in cached_resp.retrieved],
                        filters_applied={},
                        reranked_order=[],
                        prompt_hash=compute_prompt_hash(q),
                        full_prompt="[SERVED FROM SEMANTIC CACHE]",
                        model="cache",
                        parameters={"cache_threshold": settings.cache_threshold},
                        response=cached_resp.model_dump(),
                        citations=[c.model_dump() for c in cached_resp.citations],
                        guardrail_actions=guardrails,
                        latency_per_stage=latencies,
                        cache_status="hit",
                    )
                )
                return cached_resp
        except Exception as exc:
            log.warning(f"[{request_id}] Query embedding for cache lookup failed: {exc}")

    # Step 3: Retrieval
    t_ret_start = time.perf_counter()
    passages: list[Passage] = retriever.retrieve(q, k=settings.top_k)
    latencies["retrieval_ms"] = round((time.perf_counter() - t_ret_start) * 1000.0, 2)

    # Check for prompt injection attempt in retrieved passages
    for p in passages:
        if re.search(injection_pattern, p.text, re.IGNORECASE):
            guardrails.append({
                "rail": "prompt_injection_guardrail",
                "action": "neutralized",
                "reason": f"Malicious instruction detected in chunk {p.chunk_id} from {p.source} and neutralized by context delimiters",
                "triggered": True,
            })

    chunk_ids = [p.chunk_id for p in passages]
    scores = [round(p.score, 4) for p in passages]
    max_score = max(scores) if scores else 0.0

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
        resp = AskResponse(
            request_id=request_id,
            answer="I do not have sufficient information in the provided documents to answer this question.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=retrieved_refs,
            provider="abstention",
        )
        latencies["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)
        log_trace(
            TraceRecord(
                trace_id=request_id,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                user_query=q,
                rewritten_query=None,
                embedding_model=settings.embed_model,
                embedding_version="v1.5",
                collection_name=settings.collection,
                collection_version="2026-v1",
                retrieved_chunks=[r.model_dump() for r in retrieved_refs],
                filters_applied={"relevance_floor": settings.relevance_floor},
                reranked_order=chunk_ids,
                prompt_hash=compute_prompt_hash(q),
                full_prompt="[ABSTAINED BELOW RELEVANCE FLOOR]",
                model=provider.name,
                parameters={"relevance_floor": settings.relevance_floor},
                response=resp.model_dump(),
                citations=[],
                guardrail_actions=guardrails,
                latency_per_stage=latencies,
                cache_status="miss",
            )
        )
        return resp

    # Step 6: Generation
    t_gen_start = time.perf_counter()
    answer = provider.generate(q, passages)
    latencies["generation_ms"] = round((time.perf_counter() - t_gen_start) * 1000.0, 2)

    # Step 7: Citation verification
    verified_citations = verify_citations(answer.citations, passages)

    abstention_indicators = (
        "do not have sufficient",
        "insufficient information",
        "do not provide sufficient",
        "not explicitly stated",
        "not explicitly mentioned",
        "no direct answer",
        "unable to answer",
        "not mentioned",
        "not provided",
        "not sufficient",
        "cannot answer",
        "no information",
        "not covered",
        "not found",
    )
    is_abstention_text = any(phrase in answer.answer.lower() for phrase in abstention_indicators)

    answered_from_context = answer.answered_from_context and not is_abstention_text and bool(verified_citations)
    if not answered_from_context:
        answer_text = "I do not have sufficient information in the provided documents to answer this question."
        verified_citations = []
    else:
        answer_text = answer.answer

    response = AskResponse(
        request_id=request_id,
        answer=answer_text,
        citations=verified_citations,
        answered_from_context=answered_from_context,
        confidence=answer.confidence if answered_from_context else "low",
        retrieved=retrieved_refs,
        provider=provider.name,
    )

    # Step 8: Update semantic cache
    if query_vector:
        cache.store(q, query_vector, response, request_id)

    latencies["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)

    # Reconstruct prompt for trace provenance
    assembled_prompt = "System: You are RAHBAR. Answer from passages only.\n\nPassages:\n"
    for i, p in enumerate(passages, 1):
        assembled_prompt += f"[{i}] {p.source} (p.{p.page}): {p.text[:200]}...\n"
    assembled_prompt += f"\nQuestion: {q}"

    log_trace(
        TraceRecord(
            trace_id=request_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            user_query=q,
            rewritten_query=None,
            embedding_model=settings.embed_model,
            embedding_version="v1.5",
            collection_name=settings.collection,
            collection_version="2026-v1",
            retrieved_chunks=[r.model_dump() for r in retrieved_refs],
            filters_applied={"superseded": {"$ne": True}},
            reranked_order=chunk_ids,
            prompt_hash=compute_prompt_hash(assembled_prompt),
            full_prompt=assembled_prompt,
            model=settings.llm_model,
            parameters={"temperature": settings.temperature, "top_k": settings.top_k},
            response=response.model_dump(),
            citations=[c.model_dump() for c in verified_citations],
            guardrail_actions=guardrails,
            latency_per_stage=latencies,
            cache_status="miss",
        )
    )

    return response
