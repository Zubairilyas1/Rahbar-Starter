# RAHBAR RAGOps: Kubernetes Deployment & Controlled Release (Part F)

## 1. Overview and Architecture Alignment
In the RAGOps paradigm (Xu et al., 2026, Section 4.3), deploying changes to live RAG pipelines requires automated synchronization between data stores, model configurations, and serving containers. All workloads are deployed in the isolated namespace `rahbar` under strict least-privilege security controls.

```
                         [ Ingress: rahbar.local ]
                         /                       \
                     path: /                   path: /api
                        v                         v
               [ UI Deployment ]          [ API Deployment ]
                 (3 Replicas)               (3 Replicas)
                                            /           \
                                           v             v
                                 [ Chroma StatefulSet ] [ Redis Deployment ]
                                   (rahbar-corpus-pvc)   (redis-data PVC)
                                           ^
                                           |
                                 [ Indexer Job / CronJob ]
```

---

## 2. Manifest Enhancements for RAGOps

### 2.1 Persistent Ingestion & Data Lake Volumes (`corpus-pvc.yaml`)
To support Part A2 incremental ingestion, quarantine routing, and version archiving, a dedicated persistent volume claim `rahbar-corpus-pvc` (2 Gi) is bound:
- `/data/corpus/active/`: Clean verified policy files.
- `/data/corpus/quarantine/`: Defective or corrupt documents isolated during verification.
- `/data/corpus/archive/`: Superseded policy versions preserved for rollback audit.

A second volume `rahbar-traces-pvc` (1 Gi) ensures structured query trace logs (`traces/live_traces.jsonl`) persist across pod restarts and scaling events.

### 2.2 In-Cluster Evaluation & Release Gate Job (`eval-job.yaml`)
Before a candidate image receives live production traffic, `rahbar-eval-job` executes in-cluster to enforce the 5 release gates:
```bash
python -m eval.release_gate --baseline eval/results/three_level_eval.json --candidate eval/results/candidate_tuned_eval.json
```
If the job fails (exit code 1), deployment pipelines halt immediately.

---

## 3. Zero-Downtime Rolling Update & Rollback Verification

### 3.1 Rolling Update Strategy
The API deployment enforces:
```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
```
- **Zero-Downtime Guarantee**: At least 3 healthy replicas remain in service at all times during a rollout.
- **Graceful Termination**: `terminationGracePeriodSeconds: 30` with `preStop: sleep 5` hook allows in-flight LLM generations to finish before SIGKILL.
- **Probe Verification**: `startupProbe` (failureThreshold 30), `livenessProbe` (20s), and `readinessProbe` (/readyz checking Chroma, collection, and Redis).

### 3.2 Rollback Simulation (`kubectl rollout undo`)
When an anomalous configuration or degraded candidate is detected:
1. **Trigger Rollback**:
   ```bash
   kubectl rollout undo deployment/api -n rahbar
   ```
2. **Monitor Rollback Status**:
   ```bash
   kubectl rollout status deployment/api -n rahbar
   ```
3. **Endpoint Verification**:
   ```bash
   kubectl get endpoints api -n rahbar
   ```
   All 3 endpoints transition seamlessly back to the previous healthy revision without dropping user requests.

---

## 4. Resource Allocation & Autoscaling (HPA)

| Workload | Container | CPU Request | CPU Limit | Memory Request | Memory Limit | Autoscaling Policy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **api** | `api` | 100m | 500m | 256Mi | 512Mi | HPA 3 to 8 (CPU > 70%) |
| **chroma** | `chroma` | 200m | 1000m | 512Mi | 1.5Gi | StatefulSet PVC (Persistent) |
| **redis** | `redis` | 50m | 200m | 64Mi | 256Mi | Persistent PVC Append-Only |
| **ui** | `ui` | 50m | 100m | 64Mi | 128Mi | Static 3 Replicas |
| **indexer** | `indexer` | 200m | 500m | 320Mi | 768Mi | Job / CronJob Batch |
| **eval-job**| `evaluator` | 200m | 1000m | 256Mi | 1Gi | Pre-deployment gate Job |
