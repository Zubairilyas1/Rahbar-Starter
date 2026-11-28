# Controlled release and rollback on Kubernetes (Assignment 03 C3 / F3)

1. **Candidate side by side.** `api-candidate` is a second Deployment with its own
   Service and its own collection (`rahbar_c600` or `rahbar_c120`). NetworkPolicy
   `allow-eval-to-api-candidate` admits only the eval Job, so users never reach it.
2. **Gate.** `k8s/eval-job.yaml` runs the Part B suite against `http://api-candidate:8000`,
   writes the result to the `rahbar-results` volume and applies the gate against
   `latest_baseline.json`. A failed gate exits 1. With `backoffLimit: 0` the Job ends
   `Failed` and nothing is promoted: the gate-rejected candidate is never rolled out.
3. **Promote.** After a passing Job, `kubectl patch deployment api --patch-file
   k8s/release/promote-c600-patch.yaml` changes the live pod template
   (`CHROMA_COLLECTION`, `COLLECTION_VERSION`, `PIPELINE_VERSION`, plus the
   change-cause annotation). The Deployment rolls with `maxSurge: 1, maxUnavailable: 0`
   while `kubectl rollout status` watches. Old pods leave only after new ones pass
   `/readyz`, which checks that the new collection exists and is non-empty and that
   its embedding model matches the pin.
4. **Undo.** `k8s/release/bad-release-c120-patch.yaml` ships a bad release that skips
   the gate. `kubectl rollout undo deployment/api` restores the previous pod
   template. The release provenance lives in the pod template's `env`, not in the
   ConfigMap, so after the undo the next trace records the previous `collection_name`,
   `collection_version` and `embedding_version`. `GET /api/info` shows the same.

The release values sit in the pod template because a ConfigMap change does not restart
pods and is not recorded in `kubectl rollout history`. A pod-template change is both.

Commands and the screenshot list are in `k8s/README.md` (sections 4 and 5).
