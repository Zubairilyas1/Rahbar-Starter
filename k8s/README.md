# RAHBAR on Kubernetes: fresh cluster to the full Assignment 03 demo

Every manifest is in this folder. On a fresh cluster, applying them in the order
below gives a working pipeline. The only extra commands are the ones listed here.
Commands are written so they run unchanged in bash and in PowerShell.

```
k8s/
  base/                     always-on objects (kubectl apply -k k8s/overlays/dev)
    namespace, serviceaccounts, configmap (rahbar-config), gate-configmap (rahbar-gate),
    storage (PVCs: rahbar-datalake, rahbar-results, rahbar-traces),
    chroma-statefulset (+ its own PVC), redis-deployment, services, ingress,
    networkpolicy, api-deployment, hpa, ui-deployment, indexer-job, reindex-cronjob
  eval-job.yaml             Part B suite + release gate against the candidate (F2)
  jobs/                     on-demand Jobs: baseline eval, gate-only, Batch B, rollback, chunk counts
  release/                  candidate collections + api-candidate Deployments + promotion patches (F3)
  overlays/dev, overlays/prod
```

## RAGOps responsibilities by Kubernetes object

| Responsibility (paper) | Object |
|---|---|
| Ingest + verify + update data lake + update retrieval source | Job `rahbar-indexer` and CronJob `reindex` (same pod template) |
| Only one writer to the vector store | The indexer Job is the only workload with a write path. NetworkPolicy `allow-api-and-indexer-to-chroma` admits only `app=api`, `app=api-candidate` (read-only code) and `app=rahbar-indexer`. `concurrencyPolicy: Forbid` stops two runs overlapping |
| Data lake, quarantine, archived versions survive restarts | PVC `rahbar-datalake` (`/datalake/{corpus,incoming,quarantine,archive,state}`) |
| Vector store state | StatefulSet `chroma` + its `volumeClaimTemplate` |
| Offline testing + release gate | Job `rahbar-eval` (`k8s/eval-job.yaml`), exit 1 on gate failure, `backoffLimit: 0` |
| Gate thresholds, changeable without rebuild | ConfigMap `rahbar-gate` |
| Results and reports | PVC `rahbar-results` |
| Traces (monitorability / traceability) | stdout JSON lines (`kubectl logs`) + PVC `rahbar-traces` (one file per pod) |
| Controlled release | Deployment `api-candidate` + Service `api-candidate` (own collection), then a rolling update of Deployment `api` (`maxUnavailable: 0`), reversed with `kubectl rollout undo` |
| Live metrics | `/metrics` on Service `api` (`kubectl port-forward`) |

## 0. Prerequisites (host)

```
ollama serve                      # with OLLAMA_HOST=0.0.0.0 so the cluster can reach it
ollama pull nomic-embed-text
ollama pull llama3.2:3b
```

Cluster: minikube (`minikube start --driver=docker --cni=calico --memory=6144 --cpus=4`,
then `minikube addons enable ingress` and `minikube addons enable metrics-server`).
Docker Desktop's Kubernetes also works (no Calico, so the NetworkPolicies are accepted
but not enforced). There, set `OLLAMA_URL` in `base/configmap.yaml` to
`http://host.docker.internal:11434`.

**Our runs (the numbers in the report):** Docker Desktop Kubernetes v1.36 with Ollama in
Docker on **CPU only**:

```
docker run -d --name rahbar-ollama -p 11434:11434 -v no1_ollama_data:/root/.ollama -e OLLAMA_HOST=0.0.0.0 ollama/ollama:latest
kubectl apply -k k8s/overlays/docker-desktop
```

**For a faster live demo**, run Ollama on the NVIDIA GPU (T1200, 4 GB: about 90% of
llama3.2:3b fits, answers drop from 26–50 s to 10–20 s). The cluster side does not change:

```
docker rm -f rahbar-ollama
docker run -d --gpus all --name rahbar-ollama -p 11434:11434 -v no1_ollama_data:/root/.ollama -e OLLAMA_HOST=0.0.0.0 ollama/ollama:latest
docker exec rahbar-ollama ollama ps        # PROCESSOR column shows the CPU/GPU split
```

GPU latencies are not comparable with the CPU numbers in the report. Re-measure the
baseline before gating a candidate on a different machine.

## 1. Images

```
python corpus/fetch.py                                   # corpus/raw/ is baked into the indexer image
docker build -t rahbar-api:dev api
docker build -f indexer/Dockerfile -t rahbar-indexer:dev .
docker build -t rahbar-ui:dev ui
docker build -f eval/Dockerfile -t rahbar-eval:dev .
minikube image load rahbar-api:dev                       # minikube only, for each of the 4 images
minikube image load rahbar-indexer:dev
minikube image load rahbar-ui:dev
minikube image load rahbar-eval:dev
```

## 2. Apply

```
kubectl apply -k k8s/overlays/dev                 # minikube
kubectl apply -k k8s/overlays/docker-desktop      # Docker Desktop Kubernetes (our runs)
kubectl create secret generic rahbar-secret -n rahbar --from-literal=LLM_API_KEY=local-placeholder
kubectl wait --for=condition=complete job/rahbar-indexer -n rahbar --timeout=30m
kubectl rollout status deployment/api -n rahbar
kubectl get all,pvc,configmap,cronjob,job -n rahbar          # screenshot F
```

The first indexer run seeds `/datalake/corpus` from the image, verifies all
documents and builds collection `rahbar` (chunk 400 / overlap 50).

Files on the volumes are read and changed with `scripts/cluster_files.py`, which runs
short-lived Jobs that mount the volumes (`sh`, `put`, `export`). It doesn't use
`kubectl exec`/`cp`, which fail on Docker Desktop's Kubernetes with
"server gave HTTP response to HTTPS client".

## 3. Part A: verify and update

```
kubectl logs job/rahbar-indexer -n rahbar                           # verification table + run summary
kubectl create job --from=cronjob/reindex rerun-unchanged -n rahbar
kubectl logs -f job/rerun-unchanged -n rahbar                       # "embedded_chunks": 0   (screenshot A)
kubectl apply -f k8s/jobs/ingest-batch-b-job.yaml
kubectl logs -f job/rahbar-ingest-batch-b -n rahbar                 # Batch B report: P/F per check (screenshot A)
python scripts/cluster_files.py sh "ls -la /datalake/quarantine /datalake/archive"
```

Changed document, deleted document (orphan proof), rollback:

```
python scripts/cluster_files.py sh "echo 'Updated: help desk extension 100.' >> /datalake/corpus/doc02-library-digital-resources-2026.md"
kubectl create job --from=cronjob/reindex rerun-modified -n rahbar
kubectl logs -f job/rerun-modified -n rahbar                        # only doc02 purged + re-embedded
python scripts/cluster_files.py sh "rm /datalake/corpus/doc03-sports-complex-regulations-2026.md"
kubectl create job --from=cronjob/reindex rerun-deleted -n rahbar
kubectl logs -f job/rerun-deleted -n rahbar                         # purged, orphans 0, chunk counts per document
kubectl apply -f k8s/jobs/rollback-doc-job.yaml
kubectl logs -f job/rahbar-rollback -n rahbar                       # 2022 policy restored, doc11 archived
```

Unseen batch at the demo:

```
python scripts/cluster_files.py put ./unseen-batch /datalake/incoming
kubectl create job --from=cronjob/reindex ingest-unseen -n rahbar
kubectl logs -f job/ingest-unseen -n rahbar
```

## 4. Parts B, C and F3: baseline, candidate, gate, release, rollback

```
kubectl apply -f k8s/jobs/eval-baseline-job.yaml                    # Part B on the live api -> latest_baseline.json
kubectl logs -f job/rahbar-eval-baseline -n rahbar                  # summary table, all three levels (screenshot B)

# candidate that the gate STOPS (never rolled out)
kubectl apply -f k8s/release/index-candidate-c120-job.yaml
kubectl wait --for=condition=complete job/index-candidate-c120 -n rahbar --timeout=30m
kubectl apply -f k8s/release/api-candidate-c120.yaml
kubectl rollout status deployment/api-candidate -n rahbar
kubectl apply -f k8s/eval-job.yaml
kubectl logs -f job/rahbar-eval -n rahbar                           # GATE RESULT: FAIL -> REJECT (screenshot C)
kubectl get job rahbar-eval -n rahbar                               # Failed: not promoted

# candidate that PASSES, then promotion with a rolling update
kubectl apply -f k8s/release/index-candidate-c600-job.yaml
kubectl wait --for=condition=complete job/index-candidate-c600 -n rahbar --timeout=30m
kubectl apply -f k8s/release/api-candidate-c600.yaml
kubectl rollout status deployment/api-candidate -n rahbar
kubectl delete job rahbar-eval -n rahbar
kubectl apply -f k8s/eval-job.yaml
kubectl logs -f job/rahbar-eval -n rahbar                           # GATE RESULT: PASS -> RELEASE (screenshot C)
kubectl patch deployment api -n rahbar --patch-file k8s/release/promote-c600-patch.yaml
kubectl rollout status deployment/api -n rahbar                     # (screenshot F)

# a bad release reversed with rollout undo
kubectl patch deployment api -n rahbar --patch-file k8s/release/bad-release-c120-patch.yaml
kubectl rollout status deployment/api -n rahbar
kubectl rollout history deployment/api -n rahbar
kubectl rollout undo deployment/api -n rahbar
kubectl rollout status deployment/api -n rahbar                     # (screenshot F)
kubectl port-forward svc/api 8000:8000 -n rahbar                    # second terminal
curl -s -X POST localhost:8000/api/ask -H "Content-Type: application/json" -d "{\"question\": \"What CGPA puts a student on academic warning?\"}"
kubectl logs deploy/api -n rahbar --tail=50 | grep record_type      # PowerShell: | findstr record_type
```

The last trace shows `collection_name`, `collection_version` and `embedding_version`
of the revision before the bad one (screenshot F).

## 5. F2: a ConfigMap edit changes the gate, no rebuild

```
kubectl apply -f k8s/jobs/eval-gate-only-job.yaml
kubectl logs -f job/rahbar-eval-gate -n rahbar                      # PASS with the default thresholds
kubectl patch configmap rahbar-gate -n rahbar --patch-file k8s/jobs/gate-strict-patch.yaml
kubectl delete job rahbar-eval-gate -n rahbar
kubectl apply -f k8s/jobs/eval-gate-only-job.yaml
kubectl logs -f job/rahbar-eval-gate -n rahbar                      # FAIL: same result file, stricter threshold
kubectl patch configmap rahbar-gate -n rahbar --patch-file k8s/jobs/gate-default-patch.yaml
```

## 6. F4/F5: traces, metrics, resources, and getting the files into the repo

```
kubectl logs deploy/api -n rahbar | grep record_type                # traces on stdout
kubectl port-forward svc/api 8000:8000 -n rahbar                    # then: curl localhost:8000/metrics
kubectl top pods -n rahbar --containers                             # while the eval / indexer Jobs run
python scripts/cluster_files.py export                          # /results, /traces -> repo
python traces/inspect.py <trace_id> --path traces/cluster           # D2 (screenshot D)
python traces/metrics_summary.py --path traces/cluster --exclude-eval
python traces/diagnose.py <trace_id> --path traces/cluster          # D5
```

## Troubleshooting

- Indexer or API cannot reach Ollama: check `OLLAMA_URL` in `rahbar-config` and that
  Ollama listens on `0.0.0.0`.
- `rahbar-eval` is `Failed`: read `kubectl logs job/rahbar-eval -n rahbar`. Exit 1 is a
  gate rejection; exit 2 means the suite could not reach a Service or Ollama.
- Re-running a Job with the same name: `kubectl delete job <name> -n rahbar` first.
