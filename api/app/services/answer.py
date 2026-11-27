"""Turns a question into an AskResponse. This is where the query pipeline lives.

Implements the full 8-step pipeline: validation, semantic cache, retrieval,
relevance floor abstention, augmented prompt, generation with retry and fallback,
citation verification against retrieved passages, and cache storage.

Every exit path writes exactly one trace record (Assignment 03 D1) through
`_emit`, which also updates the Prometheus RAGOps metrics (D3).
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
from ..routes.metrics import observe_trace
from ..schemas import AskResponse, Passage, RetrievedRef
from ..tracing import TraceRecord, compute_prompt_hash, log_trace
from .cache import SemanticCache
from .citations import verify_citations

log = logging.getLogger("rahbar.answer")

ABSTAIN_TEXT = "I do not have sufficient information in the provided documents to answer this question."

# The injection rail from Assignment 02, applied to the query and to every
# retrieved chunk. Its action is written into the trace (D4).
INJECTION_PATTERN = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions|disregard (the )?(system|previous)|"
    r"system override|\[inst\]|pwned|output the secret|reveal (the )?(system )?prompt)",
    re.IGNORECASE,
)

ABSTENTION_INDICATORS = (
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

# Global cache instance for API lifetime
_cache: SemanticCache | None = None


def get_cache(settings: Settings) -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache(settings)
    return _cache


def _filter_for(retriever: Retriever, question: str) -> dict[str, Any]:
    if getattr(retriever, "name", "") == "chroma":
        from ..retrieval.chroma import where_filter_for

        return where_filter_for(question) or {}
    return {}


def _chunk_trace(refs: list[RetrievedRef]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": r.chunk_id,
            "document_id": r.source,
            "doc_version": r.doc_version,
            "page": r.page,
            "section": r.section,
            "score": round(r.score, 4),
        }
        for r in refs
    ]


def _emit(
    *,
    settings: Settings,
    request_id: str,
    question: str,
    response: AskResponse,
    refs: list[RetrievedRef],
    filters: dict[str, Any],
    prompt: str,
    model: str,
    parameters: dict[str, Any],
    guardrails: list[dict[str, Any]],
    latencies: dict[str, float],
    t_start: float,
    cache_status: str,
) -> None:
    latencies["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 2)
    record = TraceRecord(
        trace_id=request_id,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        user_query=question,
        rewritten_query=None,  # RAHBAR does not rewrite queries; recorded explicitly as null
        embedding_model=settings.embed_model,
        embedding_version=settings.embed_version,
        collection_name=settings.collection,
        collection_version=settings.collection_version,
        pipeline_version=settings.pipeline_version,
        retrieved_chunks=_chunk_trace(refs),
        filters_applied=filters,
        reranked_order=[r.chunk_id for r in refs],
        prompt_hash=compute_prompt_hash(prompt),
        full_prompt=prompt,
        model=model,
        parameters=parameters,
        response=response.model_dump(),
        citations=[c.model_dump() for c in response.citations],
        guardrail_actions=guardrails,
        latency_per_stage=latencies,
        cache_status=cache_status,
    )
    log_trace(record)
    try:
        observe_trace(record.as_dict())
    except Exception as exc:  # metrics must never break a query
        log.warning(f"[{request_id}] metrics update failed: {exc}")


def answer_question(
    question: str,
    retriever: Retriever,
    provider: LLMProvider,
    settings: Settings,
    use_cache: bool = True,
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
    gen_params: dict[str, Any] = {
        "temperature": settings.temperature,
        "seed": settings.llm_seed,
        "top_k": settings.top_k,
        "relevance_floor": settings.relevance_floor,
        "reranker": "none",
        "cache_enabled": use_cache,
    }
    filters = _filter_for(retriever, q)

    guardrails: list[dict[str, Any]] = []
    if INJECTION_PATTERN.search(q):
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

    common = dict(settings=settings, request_id=request_id, question=q,
                  guardrails=guardrails, latencies=latencies, t_start=t_start)

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
        _emit(**common, response=resp, refs=[], filters=filters,  # type: ignore[arg-type]
              prompt="[REJECTED BY VALIDATION: no prompt sent]", model="none",
              parameters=gen_params, cache_status="bypass")
        return resp

    # Step 2: Semantic cache lookup
    cache = get_cache(settings)
    query_vector: list[float] = []
    if hasattr(retriever, "_embed_query"):
        try:
            t_emb_start = time.perf_counter()
            query_vector = retriever._embed_query(q)  # type: ignore[attr-defined]
            latencies["embedding_ms"] = round((time.perf_counter() - t_emb_start) * 1000.0, 2)
            if use_cache:
                t_cache_start = time.perf_counter()
                cached_resp = cache.lookup(q, query_vector, request_id)
                latencies["cache_lookup_ms"] = round((time.perf_counter() - t_cache_start) * 1000.0, 2)
                if cached_resp is not None:
                    _emit(**common, response=cached_resp, refs=list(cached_resp.retrieved),  # type: ignore[arg-type]
                          filters=filters,
                          prompt="[SERVED FROM SEMANTIC CACHE: no prompt sent to the model]",
                          model="cache",
                          parameters={**gen_params, "cache_threshold": settings.cache_threshold},
                          cache_status="hit")
                    return cached_resp
        except Exception as exc:
            log.warning(f"[{request_id}] Query embedding for cache lookup failed: {exc}")
    cache_status = "miss" if use_cache else "bypass"

    # Step 3: Retrieval
    t_ret_start = time.perf_counter()
    passages: list[Passage] = retriever.retrieve(q, k=settings.top_k)
    latencies["retrieval_ms"] = round((time.perf_counter() - t_ret_start) * 1000.0, 2)

    # Step 4: Retrieval rail -- injected instructions inside retrieved chunks (D4)
    for p in passages:
        if INJECTION_PATTERN.search(p.text):
            guardrails.append({
                "rail": "prompt_injection_guardrail",
                "action": "neutralized",
                "reason": (f"Instruction-like text in chunk {p.chunk_id} from {p.source} "
                           "kept inside evidence delimiters; the system prompt forbids following it"),
                "chunk_id": p.chunk_id,
                "document_id": p.source,
                "triggered": True,
            })

    retrieved_refs = [
        RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section,
                     page=p.page, score=p.score, doc_version=p.doc_version)
        for p in passages
    ]
    max_score = max((p.score for p in passages), default=0.0)

    # Step 5: Relevance floor check and deterministic abstention
    if not passages or max_score < settings.relevance_floor:
        log.info(f"[{request_id}] Abstaining: max similarity {max_score:.4f} < floor {settings.relevance_floor:.4f}")
        guardrails.append({
            "rail": "relevance_floor",
            "action": "abstained",
            "reason": f"top-1 similarity {max_score:.4f} below floor {settings.relevance_floor:.2f}",
            "triggered": True,
        })
        resp = AskResponse(
            request_id=request_id,
            answer=ABSTAIN_TEXT,
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=retrieved_refs,
            provider="abstention",
        )
        _emit(**common, response=resp, refs=retrieved_refs, filters=filters,  # type: ignore[arg-type]
              prompt="[ABSTAINED BELOW RELEVANCE FLOOR: no prompt sent to the model]",
              model=provider.name, parameters=gen_params, cache_status=cache_status)
        return resp

    # Step 6: Generation (the exact prompt is captured for the trace tool, D2)
    render = getattr(provider, "render_prompt", None)
    prompt = render(q, passages) if callable(render) else q
    t_gen_start = time.perf_counter()
    answer = provider.generate(q, passages)
    latencies["generation_ms"] = round((time.perf_counter() - t_gen_start) * 1000.0, 2)

    # Step 7: Citation verification
    verified_citations = verify_citations(answer.citations, passages)
    is_abstention_text = any(phrase in answer.answer.lower() for phrase in ABSTENTION_INDICATORS)
    answered_from_context = answer.answered_from_context and not is_abstention_text and bool(verified_citations)
    if not answered_from_context:
        if answer.citations and not verified_citations:
            guardrails.append({
                "rail": "citation_verification",
                "action": "abstained",
                "reason": "model cited passages that were not retrieved; answer withheld",
                "triggered": True,
            })
        answer_text = ABSTAIN_TEXT
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
    if query_vector and use_cache:
        cache.store(q, query_vector, response, request_id)

    _emit(**common, response=response, refs=retrieved_refs, filters=filters,  # type: ignore[arg-type]
          prompt=prompt, model=f"{provider.name}:{settings.llm_model}",
          parameters=gen_params, cache_status=cache_status)
    return response


def retrieve_only(question: str, retriever: Retriever, settings: Settings) -> tuple[list[Passage], dict[str, Any]]:
    """Retrieval without generation, for the component-level evaluation (Part B)."""
    q = question.strip()
    return retriever.retrieve(q, k=settings.top_k), _filter_for(retriever, q)
