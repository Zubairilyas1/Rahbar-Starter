# Evidence checklist

Captured from the live minikube cluster with `RETRIEVER=chroma` and `LLM_PROVIDER=ollama-host`. The collection was populated by the dummy indexer (`EMBED_MODEL=dummy-768`), so these files prove the Kubernetes behavior, not real-corpus answer quality. Minimum 5 files are required by the submission checker:

- [ ] `branch-protection.png` -- the `main` branch protection settings page.
- [ ] `blocked-merge.png` + `green-merge.png` -- a PR that fails the eval/CI gate, then
      passes after a fix (handout section 8).
- [x] `kubectl-top-pods.txt` -- `kubectl top pods -n rahbar` after the dummy indexer Job completed; the real-corpus indexer peak remains unmeasured.
- [x] `get-endpoints.txt` -- `kubectl get endpoints -n rahbar` showing the `api` Service
      with 3+ pod IPs.
- [x] `get-hpa.txt` -- `kubectl get hpa -n rahbar` with a real `<current>/70%`, not
      `<unknown>`.
- [ ] (nice-to-have) `rollout-and-rollback.txt` -- `kubectl set image` + `rollout status`
      + `rollout undo` output.
- [x] (nice-to-have) `embedding-mismatch.txt` -- the pod stuck at `0/1 READY` and
      the log line naming the conflict, after changing `EMBED_MODEL` without reindexing.

`get-pods.txt`, `indexer-job-logs.txt`, and `scale-and-pod-replacement.txt` record the live pod state, dummy Job completion, and a pod deletion. The HPA promptly returned a manual scale request to its target, so that file does not prove five ready endpoints.
