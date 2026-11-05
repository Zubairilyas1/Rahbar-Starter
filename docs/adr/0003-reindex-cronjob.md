# ADR 0003: Scheduled Corpus Reindexing via Kubernetes CronJob

## Status
Accepted — November 2026

## Context
Academic rules, grading guidelines, and fee structures are periodically updated by the university. While a one-time Kubernetes Job initializes the vector store, a production system requires scheduled, hands-off maintenance to reflect document revisions without requiring cluster teardown or manual intervention. Moreover, reindexing poses the risk of serving obsolete answers if existing cache entries are not flushed concurrently.

## Decision
We deploy a Kubernetes `CronJob` (`reindex-cronjob.yaml`) running weekly (scheduled at 03:00 UTC every Sunday). The CronJob executes the identical container image and arguments as the primary indexer Job. Upon successful completion of vector upsertion, the indexer triggers a cache invalidation signal (`FLUSHDB` or deleting `rahbar:cache:*` keys) in Redis. 

## Options considered
1. **Manual Ingestion via Admin API Endpoint**: Rejected because an HTTP endpoint in the API would introduce vector embedding computation into the user-facing worker pool, causing worker starvation and potential timeout failures.
2. **File Watcher Daemon**: Rejected as inefficient on Kubernetes NFS/Ceph/HostPath mounts and prone to thrashing during partial file uploads.

## Consequences
- **Positive**: Guaranteed corpus freshness; automatic cache invalidation ensures no stale answers persist across policy updates; standard Kubernetes telemetry tracks job failures and retries.
- **Negative**: Reindexing temporarily increases ChromaDB disk I/O and Ollama embedding compute during the scheduled window.
