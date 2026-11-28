"""Prometheus metrics at /metrics (section 4.8, Assignment 03 D3/F4).

HTTP request count and latency, plus the RAGOps metrics the assignment asks for:
top-1 retrieval similarity distribution, abstention rate, cache hit rate, latency
per stage, and the number of injection attempts flagged. Reach it on the cluster
with `kubectl port-forward svc/api 8000:8000 -n rahbar` then GET /metrics.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)

# --- RAGOps query metrics (one observation per /api/ask) -----------------------
QUERIES = Counter(
    "rahbar_queries_total",
    "Answered queries by outcome",
    ["outcome", "collection"],          # outcome: answered | abstained | rejected
)
CACHE = Counter("rahbar_cache_lookups_total", "Semantic cache lookups", ["status", "collection"])
TOP1_SIMILARITY = Histogram(
    "rahbar_top1_similarity",
    "Cosine similarity of the top-1 retrieved chunk",
    ["collection"],
    buckets=(0.2, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0),
)
STAGE_LATENCY = Histogram(
    "rahbar_stage_seconds",
    "Latency per pipeline stage",
    ["stage", "collection"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)
INJECTIONS = Counter(
    "rahbar_injection_flags_total",
    "Prompt-injection attempts flagged by the guardrail",
    ["where", "collection"],            # where: query | context
)


def observe_trace(trace: dict) -> None:  # type: ignore[type-arg]
    """Update the RAGOps metrics from one finished trace record."""
    coll = str(trace.get("collection_name", "unknown"))
    response = trace.get("response") or {}
    provider = response.get("provider")
    if provider == "validation":
        outcome = "rejected"
    elif response.get("answered_from_context"):
        outcome = "answered"
    else:
        outcome = "abstained"
    QUERIES.labels(outcome=outcome, collection=coll).inc()

    status = trace.get("cache_status", "miss")
    if status in ("hit", "miss"):
        CACHE.labels(status=status, collection=coll).inc()

    chunks = trace.get("retrieved_chunks") or []
    if chunks:
        TOP1_SIMILARITY.labels(collection=coll).observe(float(chunks[0].get("score", 0.0)))

    for stage, ms in (trace.get("latency_per_stage") or {}).items():
        STAGE_LATENCY.labels(stage=stage.removesuffix("_ms"), collection=coll).observe(float(ms) / 1000.0)

    for rail in trace.get("guardrail_actions") or []:
        if rail.get("rail") == "prompt_injection_guardrail" and rail.get("triggered"):
            where = "context" if rail.get("action") == "neutralized" else "query"
            INJECTIONS.labels(where=where, collection=coll).inc()


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
