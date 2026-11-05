"""The real retriever. Yours to build (sections 3.2 and 4.4).

Connection details are already here; the query is not.
"""

from __future__ import annotations

import logging
import re
import httpx

from ..config import Settings
from ..schemas import Passage

log = logging.getLogger("rahbar.retrieval.chroma")


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def _embed_query(self, text: str) -> list[float]:
        """Embeds question using the pinned embed_model via Ollama /api/embed."""
        url = f"{self.settings.ollama_url.rstrip('/')}/api/embed"
        payload = {
            "model": self.settings.embed_model,
            "input": [text],
        }
        with httpx.Client(timeout=30.0) as http_client:
            resp = http_client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [])
            if not embeddings:
                raise ValueError("No embeddings returned from Ollama")
            return embeddings[0]

    def retrieve(self, question: str, k: int | None = None) -> list[Passage]:
        """Embed the question with settings.embed_model, query the collection for the
        top k, filter out superseded documents, and map each hit to a Passage.
        Chroma returns cosine distance; Passage.score expects similarity: score = 1 - distance."""
        limit = k or self.settings.top_k
        query_vector = self._embed_query(question)

        collection = self.client.get_collection(name=self.settings.collection)

        # Detect historical question intent to allow superseded clauses if explicitly requested
        is_historical = bool(re.search(r"\b(2023|old|previous|superseded|earlier|past|history)\b", question, re.I))

        # Build where filter: filter out superseded documents unless historical question
        where_filter = None if is_historical else {"superseded": False}

        # Query ChromaDB: request extra candidates to filter safely if needed
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=min(limit * 2, 20),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        passages: list[Passage] = []
        if not results or not results.get("ids") or not results["ids"][0]:
            return passages

        ids = results["ids"][0]
        docs = results["documents"][0] if results.get("documents") else []
        metas = results["metadatas"][0] if results.get("metadatas") else []
        distances = results["distances"][0] if results.get("distances") else []

        for idx, chunk_id in enumerate(ids):
            meta = metas[idx] if idx < len(metas) else {}
            text = docs[idx] if idx < len(docs) else ""
            dist = distances[idx] if idx < len(distances) else 1.0

            # Filter superseded documents if where_filter was not applied at the database layer
            superseded = bool(meta.get("superseded", False))
            if not is_historical and superseded:
                continue

            # Convert cosine distance to cosine similarity: similarity = 1 - distance
            score = round(max(0.0, min(1.0, 1.0 - dist)), 4)

            passages.append(
                Passage(
                    chunk_id=chunk_id,
                    text=text,
                    source=str(meta.get("source", "unknown")),
                    section=str(meta.get("section", "General")),
                    page=int(meta["page"]) if meta.get("page") is not None else None,
                    score=score,
                )
            )
            if len(passages) >= limit:
                break

        return passages
