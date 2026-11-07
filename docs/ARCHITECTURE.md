# Architecture

## Topology

One writer (the indexer Job/CronJob), one reader (the api Deployment, 3 replicas),
one shared pin (`EMBED_MODEL` in `rahbar-config`). See the README's architecture
diagram for the full picture (namespace `rahbar`, Ingress -> ui/api, api -> Chroma +
Redis, Job/CronJob -> Chroma, api/indexer -> Ollama on the host).

## Why Chroma is a StatefulSet, not a Deployment

ADR 0001 already rejects running the indexer inside the API's startup because three
replica pods would race to write one PVC. The same argument applies one level down,
to Chroma itself: Chroma's own storage (`chroma.sqlite3` + HNSW segment files under
`/data`) is a single embedded database, not a multi-writer service. Running it as a
`Deployment` with `replicas: 1` would *happen* to avoid multi-writer corruption today,
but a `Deployment`'s identity (pod name, PVC binding) is not stable across a reschedule
the way a `StatefulSet`'s is: a `Deployment` replica's PVC claim is whatever the pod
template requests, and if anyone later bumps `replicas` on a `Deployment` by habit (as
people do, since every other component in this system scales), two Chroma pods would
mount the same `ReadWriteOnce` PVC or silently get two different empty volumes,
depending on the access mode -- both are corruption or data-loss modes with no error
at apply time. A `StatefulSet` with `volumeClaimTemplates` makes "one Chroma, one
volume, one stable identity" the structure of the object itself, not a convention
someone has to remember. Redis gets the opposite treatment (`Deployment` + PVC, per
the handout's own table) because the handout specifies it that way and because its
`strategy: Recreate` plus `replicas: 1` makes the same single-writer intent explicit
without needing `StatefulSet` machinery for a cache that can be cold-started cheaply.

## Corpus delivery to the indexer image

`corpus/raw/` is gitignored; the indexer Job needs real documents at `CORPUS_DIR`
(default `/corpus`) to index for real, and the tiny, committed `eval/fixtures/` corpus
when CI runs. `indexer/Dockerfile` bakes both in at build time, using the **repository
root** as the Docker build context (`docker build -f indexer/Dockerfile -t
rahbar-indexer:<tag> .`, not the `indexer/` subfolder STARTER.md shows as the default)
so it can `COPY corpus/raw/` and `COPY eval/fixtures/` from outside the `indexer/`
folder. Real deployment: run `python corpus/fetch.py` once, then `make images`, which
bakes whatever is in `corpus/raw/` into the image and sets `CORPUS_DIR=/corpus`. CI:
the fixture corpus is always present (it's committed), so the `e2e-eval` job overrides
`CORPUS_DIR=/app/fixtures` and never calls the real university site.
