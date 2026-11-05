# ADR 0001: Indexing Decoupled as a Kubernetes Job

## Status
Accepted — November 2026

## Context
The RAHBAR API deployment is scaled to 3 replicas for high availability and load balancing, interacting with a persistent ChromaDB instance backed by a PersistentVolumeClaim (PVC). If document ingestion and embedding were executed during API process startup, all 3 replica pods would attempt to extract, embed, and upsert the corpus simultaneously upon rolling updates or pod restarts. This creates concurrent write races on the underlying Chroma database (causing SQLite locking errors and corrupted HNSW index graphs), consumes excessive cluster CPU/memory during pod boot, and delays pod readiness.

## Decision
We decouple corpus indexing entirely from the API runtime by executing it as a standalone Kubernetes `Job` (`indexer-job.yaml`). The indexer is the sole writer to the Chroma collection, running to completion and exiting with status code 0. The API service acts strictly as a read-only consumer of the indexed collection. Periodic reindexing is managed via a separate Kubernetes `CronJob`.

## Options considered
1. **API Startup Hook (`@app.on_event('startup')`)**: Rejected because running ingestion inside API startup leads to multi-replica write race conditions, unpredictable startup latency, and crashes when scaling.
2. **Kubernetes InitContainer**: Rejected because an InitContainer executes on *every* pod restart across all 3 replicas, causing redundant re-indexing and lock contention on the shared persistent volume.
3. **Dedicated Indexer Service (HTTP Worker)**: Rejected as unnecessarily complex for batch document processing; a Kubernetes Job natively handles run-to-completion semantics with restart policies and exponential backoff.

## Consequences
- **Positive**: Clean separation of responsibilities; API pods boot in seconds; zero concurrent write contention on ChromaDB; the indexer Job can be assigned dedicated, isolated resource requests and limits.
- **Negative**: Requires orchestration between the Job and API deployment (e.g. API readiness probe must wait until the indexer finishes and the collection is non-empty before receiving traffic).
- **Monitoring**: We monitor Job completion status via `kubectl get jobs -n rahbar` and ensure `backoffLimit: 3`.
