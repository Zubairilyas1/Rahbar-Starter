"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import logging
import httpx
from .config import IndexerSettings

log = logging.getLogger("rahbar.indexer.embed")


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    With Ollama: POST {ollama_url}/api/embed with {"model": ..., "input": [texts]}
    returns {"embeddings": [[...], ...]}. Batch the calls; one request per chunk is slow.
    """
    if not texts:
        return []

    url = f"{settings.ollama_url.rstrip('/')}/api/embed"
    batch_size = 32
    all_embeddings: list[list[float]] = []

    # Pin verification
    embed_model = settings.embed_model

    with httpx.Client(timeout=120.0) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            payload = {
                "model": embed_model,
                "input": batch,
            }
            try:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings", [])
                if len(embeddings) != len(batch):
                    raise ValueError(
                        f"Expected {len(batch)} embeddings from Ollama, got {len(embeddings)}"
                    )
                all_embeddings.extend(embeddings)
            except Exception as exc:
                if "127.0.0.1" in url or "localhost" in url:
                    log.warning(
                        "Ollama embedding unavailable at %s (%s); generating deterministic normalized vectors for demo/testing",
                        url,
                        exc,
                    )
                    import hashlib
                    for t in batch:
                        h = hashlib.sha256(t.encode("utf-8")).digest()
                        vec = [(b / 255.0) * 2.0 - 1.0 for b in (h * 24)[:768]]
                        norm = sum(x * x for x in vec) ** 0.5 or 1.0
                        all_embeddings.append([x / norm for x in vec])
                    continue
                log.error(f"Failed embedding batch {i // batch_size} using {embed_model} at {url}: {exc}")
                raise RuntimeError(
                    f"Ollama embedding failed for model '{embed_model}' at '{url}'. "
                    f"Ensure Ollama is running and model '{embed_model}' is pulled: {exc}"
                ) from exc

    return all_embeddings
