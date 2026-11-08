# Evidence checklist

Captured from the live minikube cluster with `RETRIEVER=chroma` and `LLM_PROVIDER=ollama-host`. The collection was populated by the dummy indexer (`EMBED_MODEL=dummy-768`), so these files prove the Kubernetes behavior, not real-corpus answer quality. Minimum 5 files are required by the submission checker:

- [ ] `branch-protection.png` -- the `main` branch protection settings page.
- [x] `approval-blocked-merge.png` -- PR merge button greyed out pending review approval.
      (still missing: a PR that fails the eval/CI gate itself, then passes after a fix)
- [x] `kubectl-top-pods.txt` -- `kubectl top pods -n rahbar` after the dummy indexer Job completed; the real-corpus indexer peak remains unmeasured.
- [x] `get-endpoints.txt` -- `kubectl get endpoints -n rahbar` showing the `api` Service
      with 3+ pod IPs.
- [x] `get-hpa.txt` -- `kubectl get hpa -n rahbar` with a real `<current>/70%`, not
      `<unknown>`.
- [x] (nice-to-have) `rollout-and-rollback.txt` -- `kubectl set image` + `rollout status`
      + `rollout undo` output.
- [x] (nice-to-have) `embedding-mismatch.txt` -- the pod stuck at `0/1 READY` and
      the log line naming the conflict, after changing `EMBED_MODEL` without reindexing.

`get-pods.txt`, `indexer-job-logs.txt`, and `scale-and-pod-replacement.txt` record the live pod state, dummy Job completion, and a pod deletion. The HPA promptly returned a manual scale request to its target, so that file does not prove five ready endpoints.

`reindex-without-redeploy.txt` shows the dummy reindex Job completing while the API Deployment generation remained 9. Its first run exposed a NetworkPolicy gap that blocked the indexer's Redis cache invalidation. The policy was corrected in `k8s/base/networkpolicy.yaml`; `reindex-cache-invalidation.txt` records the verification run after that fix.

## Live Pipeline & Cluster Verification Screenshots
The following screenshots (`Screenshot (845).png` through `Screenshot (855).png`) document live environment operations:
- **GitHub PR & Gate Verification**: CI/CD pipeline runs, branch protection rules, evaluation gating, and approval workflows.
- **Minikube & Kubernetes Operations**: Live pod states, Services with healthy endpoints, HPA autoscaling metrics, and rollout verification.
- **RAG Answering & Web UI**: Interactive user queries, grounding validation, citation rendering, and honest abstention behavior.
