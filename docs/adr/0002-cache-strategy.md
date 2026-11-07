# ADR 0002: Redis Semantic Cache with Strict Never-Cache Guardrails

## Status
Accepted — November 2026

## Context
Generative inference via Ollama or hosted LLM endpoints represents the primary source of latency and computational cost in RAHBAR. Users frequently query identical or semantically equivalent questions (e.g., *"What is the minimum attendance required?"* vs *"How much attendance is mandatory?"*). A standard exact-string key-value cache yields low hit rates due to variations in punctuation, casing, and phrasing. However, naive semantic caching risks caching negative responses, conversational follow-ups, or ungrounded answers.

## Decision
We deploy Redis as a standalone Stateful service and implement an application-level semantic cache in `api/app/services/cache.py`. Incoming query vectors are compared against cached query vectors using cosine similarity. If the maximum similarity exceeds `CACHE_THRESHOLD = 0.85`, the cached response is served directly with `provider: "cache"`. 

Furthermore, we enforce two non-negotiable **Never-Cache Rules**:
1. **Never Cache Abstentions**: If the system abstains (`answered_from_context == False`), the result is never saved. This ensures that when new documents are indexed, previously unanswerable queries are re-evaluated rather than returning a cached refusal.
2. **Never Cache Follow-up Questions**: Questions identified as contextual follow-up turns (e.g. starting with *"And what about..."*, *"Does it apply..."*) are excluded from semantic caching because their meaning depends on preceding conversational context.

## Options considered
1. **Exact String Key-Value Cache**: Rejected due to low hit rates (<15%) on natural human variations.
2. **In-Memory Cache in API Python Process**: Rejected because with 3 replicas, an in-memory cache creates cache fragmentation and inconsistent responses across pods.
3. **Always Cache Everything**: Rejected because caching abstentions prevents the system from answering questions once missing documents are ingested.

## Consequences
- **Positive**: Sub-10ms response latency on cache hits; reduced GPU/CPU load on the LLM runtime; cluster-wide cache coherence across all 3 API replicas via Redis.
- **Negative**: Adds a Redis dependency to cluster operations and network policies; requires cache invalidation upon index rebuilding.
