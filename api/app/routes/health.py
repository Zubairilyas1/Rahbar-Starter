"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Response

log = logging.getLogger("rahbar.health")
router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """Returns 200 when ready to serve traffic; returns 503 naming the failed dependency
    if Chroma is unreachable, collection is empty, Redis is down, or embed_model mismatches."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        response.status_code = 503
        return {"status": "not_ready", "error": "settings not loaded"}

    checks: dict[str, str | int] = {}
    failed: list[str] = []

    # If running with stub retriever, pass through for testing
    if settings.retriever == "stub":
        checks["retriever"] = "stub"
        checks["redis"] = "skipped"
        return {"status": "ready", "checks": checks}

    # Check 1: ChromaDB connectivity and non-empty collection
    try:
        retriever = getattr(request.app.state, "retriever", None)
        if not retriever or not hasattr(retriever, "client"):
            failed.append("chroma_client_missing")
        else:
            collection = retriever.client.get_collection(name=settings.collection)
            chunk_count = collection.count()
            checks["collection_count"] = chunk_count

            # Section 4.2 / 4.3: collection must be NON-EMPTY
            if chunk_count == 0:
                failed.append("chroma_collection_empty")
            else:
                checks["chroma"] = "ok"

            # Section 4.4: Guardrail against silent embedding model mismatch
            meta = collection.metadata or {}
            coll_embed_model = meta.get("embed_model") or meta.get("embedding_model")
            if coll_embed_model and coll_embed_model != settings.embed_model:
                failed.append(
                    f"embed_model mismatch: collection has '{coll_embed_model}', settings has '{settings.embed_model}'"
                )
            else:
                checks["embed_model_pin"] = "ok"
    except Exception as exc:
        log.warning(f"Readiness check failed for ChromaDB: {exc}")
        failed.append(f"chroma_error: {exc}")

    # Check 2: Redis connectivity
    try:
        import redis
        r = redis.Redis.from_url(
            settings.redis_url,
            socket_timeout=1.5,
            socket_connect_timeout=1.5,
        )
        if r.ping():
            checks["redis"] = "ok"
        else:
            failed.append("redis_ping_failed")
    except Exception as exc:
        log.warning(f"Readiness check failed for Redis: {exc}")
        failed.append(f"redis_error: {exc}")

    if failed:
        response.status_code = 503
        return {"status": "not_ready", "failed_checks": failed, "checks": checks}

    return {"status": "ready", "checks": checks}
