# Evidence checklist

Capture these once the real cluster is up (`RETRIEVER=chroma`, `LLM_PROVIDER=ollama-host`),
not against the stub. Minimum 5, required by the submission checker:

- [ ] `branch-protection.png` -- the `main` branch protection settings page.
- [ ] `blocked-merge.png` + `green-merge.png` -- a PR that fails the eval/CI gate, then
      passes after a fix (handout section 8).
- [ ] `kubectl-top-pods.txt` -- `kubectl top pods -n rahbar`, captured *while the indexer
      Job is running*, so the peak is real (backs the `768Mi` limit in
      `docs/ENGINEERING-NOTES.md` Q4).
- [ ] `get-endpoints.txt` -- `kubectl get endpoints -n rahbar` showing the `api` Service
      with 3+ pod IPs.
- [ ] `get-hpa.txt` -- `kubectl get hpa -n rahbar` with a real `<current>/70%`, not
      `<unknown>`.
- [ ] (nice-to-have) `rollout-and-rollback.txt` -- `kubectl set image` + `rollout status`
      + `rollout undo` output.
- [ ] (nice-to-have) `embedding-mismatch.png`/`.txt` -- the pod stuck at `0/1 READY` and
      the log line naming the conflict, after changing `EMBED_MODEL` without reindexing.
