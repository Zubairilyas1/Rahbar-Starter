"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import logging
from typing import Any

from .config import IndexerSettings
from .models import Chunk

log = logging.getLogger("rahbar.indexer.store")


def get_client(settings: IndexerSettings) -> Any:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count."""
    if not chunks:
        return 0

    client = get_client(settings)
    vector_dim = len(vectors[0]) if vectors else 768

    # Store collection with embedded metadata pin and cosine distance metric
    collection_metadata = {
        "embed_model": settings.embed_model,
        "embedding_model": settings.embed_model,
        "vector_dim": vector_dim,
        "hnsw:space": "cosine",
    }

    try:
        # Re-create or get collection with exact metadata
        collection = client.get_or_create_collection(
            name=settings.collection,
            metadata=collection_metadata,
        )
    except Exception as exc:
        log.warning(f"Collection get_or_create failed, attempting get: {exc}")
        collection = client.get_collection(name=settings.collection)

    # Batch upsert to ChromaDB in chunks of 200
    batch_size = 200
    total = len(chunks)

    for i in range(0, total, batch_size):
        end = min(i + batch_size, total)
        batch_chunks = chunks[i:end]
        batch_vectors = vectors[i:end]

        ids = [c.id for c in batch_chunks]
        embeddings = batch_vectors
        metadatas = [c.metadata() for c in batch_chunks]
        documents = [c.text for c in batch_chunks]

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )
        log.info(f"Upserted {end}/{total} chunks to collection '{settings.collection}'")

    return total
