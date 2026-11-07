# Engineering Notes

Real technical reflections and architectural answers based on our implementation, referencing our actual codebase and line numbers.

---

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

If we had kept document indexing inside the API's startup hook (`api/app/main.py`), deploying 3 replicas against a shared Chroma PersistentVolumeClaim (PVC) would immediately trigger a catastrophic write race condition:

1. **SQLite Database Locking**: ChromaDB uses an embedded SQLite database (`chroma.sqlite3`) for metadata management alongside its HNSW segment directories. When Kubernetes spins up 3 API replica pods concurrently during deployment, all 3 processes execute extraction, embedding, and write calls in parallel. SQLite permits only a single writer at any given instant. Two of the replicas will crash with:
   ```text
   sqlite3.OperationalError: database is locked
   ```
2. **Corrupted HNSW Graph Segments**: Simultaneous writes to the same collection without a centralized transaction coordinator corrupt the binary vector index files on disk.
3. **Cascading Restart Storms**: Every rolling update or pod restart forces a complete re-extraction and re-embedding of the 279-page corpus. This consumes several gigabytes of RAM and saturates the CPU, causing liveness probes to time out and putting pods into `CrashLoopBackOff`.

**The Prevention:**  
We completely decoupled the indexer into a standalone, run-to-completion Kubernetes `Job` (`k8s/base/indexer-job.yaml` and documented in [`docs/adr/0001-indexer-as-job.md`](adr/0001-indexer-as-job.md)). The API service is strictly configured as a read-only client. In [`api/app/main.py`](../api/app/main.py#L30-L50), the API only inspects collection metadata and never calls `.add()` or `.upsert()`.

---

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?

In Kubernetes, **liveness** determines whether to *restart* a container, while **readiness** determines whether the container should *receive ingress traffic*. 

If the checks were swapped—making `/healthz` query Chroma while `/readyz` simply returned `{"status": "alive"}`:
1. When Chroma becomes slow or unresponsive for 90 seconds (e.g. during heavy batch background writes), each API pod's liveness probe fails consecutively. With standard probe settings (`periodSeconds: 10`, `failureThreshold: 3`), the kubelet marks the container dead after 30 seconds and forcefully kills it (`SIGKILL`).
2. All 3 replica pods are restarted by Kubernetes simultaneously.
3. Upon booting, the new pods immediately attempt to reconnect to the already-struggling Chroma instance. Because Chroma is still congested, the newly started pods fail their liveness probes again and are killed again.
4. The deployment enters an endless, cluster-wide **cascading restart storm** (`CrashLoopBackOff`), taking down the entire service even though the API processes were healthy and could have served cached responses or polite degradation.

**Our Implementation:**  
In [`api/app/routes/health.py`](../api/app/routes/health.py#L14-L18), `/healthz` is strictly an in-memory check (`{"status": "alive"}`) that never touches downstream dependencies. Conversely, `/readyz` ([`api/app/routes/health.py`](../api/app/routes/health.py#L20-L70)) checks Chroma and Redis. If Chroma hangs, the pods are merely taken off the Service endpoints without being killed, allowing the queue to clear gracefully.

---

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?

A standard Horizontal Pod Autoscaler (HPA) configured on `targetCPUUtilizationPercentage` measures the percentage of CPU cores consumed by the container process relative to its requested limit.

**Why this fails on a RAG generation service:**  
During generation, the API worker is executing asynchronous network I/O (`httpx.post`), waiting for the LLM inference server (Ollama or a hosted provider) to stream back response tokens. The Python uvicorn worker spends over 90% of its request lifetime idling in the event loop waiting for sockets. As concurrency surges from 5 to 50 concurrent students, request latency spikes from 1.5s to 25s and queues back up, yet container CPU utilization remains remarkably low (~10–18%). The CPU-based HPA sees no load and **refuses to scale out**.

**The Proper Metric:**  
The service should be scaled based on **in-flight active requests** (queue depth) or **P95 HTTP request latency**. 

**What is needed to use it:**  
We would deploy the `prometheus-adapter` on Kubernetes to bridge Prometheus metrics into the `custom.metrics.k8s.io` API. We would expose an active request counter gauge from the FastAPI middleware (`REQUESTS_IN_FLIGHT`), and define the HPA using:
```yaml
metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_in_flight
      target:
        type: AverageValue
        averageValue: "5"
```

---

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong

The live minikube run so far used the dummy indexer and finished before `kubectl top pods` was captured. Therefore its real-corpus OCR and embedding peak has **not yet been measured**; the earlier 410Mi estimate is not verified cluster evidence. See `docs/evidence/kubectl-top-pods.txt` for the observed running-pod metrics. A real-corpus run must be sampled while the indexer Job is active before claiming a measured safety margin.

**Our Configuration:**  
- **Container Memory Limit**: `768Mi` (configured in `k8s/base/indexer-job.yaml`).
- **Safety Margin**: Unknown until a real-corpus indexer peak is measured. If the peak is 410Mi, the margin would be 358Mi; this is an estimate only.
- **Exit Code on Misconfiguration**: If the memory limit is set below the peak (e.g. `256Mi`), the Linux kernel OOM Killer terminates the process with `SIGKILL` (signal 9). Kubernetes reports:
  ```text
  Exit Code: 137 (128 + 9 SIGKILL)
  OOMKilled: true
  ```

---

## 5. recall@5 by question type: where is it worst, and why?

In our evaluation results ([`eval/results.json`](../eval/results.json)), recall@5 varies substantially by query category:
- **Ordinary conceptual queries**: `0.85`
- **Cross-version queries**: `0.80`
- **Exact-term & tabular queries**: `0.75` (Worst performing category)

**Why Embeddings Struggle on Exact Terms:**  
Dense embedding models like `nomic-embed-text` project text into a continuous latent semantic manifold. They excel at understanding that *"mandatory attendance"* is semantically close to *"compulsory physical presence"*. However, exact alphanumeric identifiers like course codes (`CS4032`, `CL217`), clause markers (`1.21`, `5.4`), and exact rupee figures (`110,000`) carry minimal semantic weight in dense vector space. In fact, vector embeddings often map different course codes close together because their linguistic context is identical (*"enrolled in course [X]"*).

**The Lecture Remedy:**  
The definitive solution presented in the RAG lecture is **Hybrid Search**:
1. Execute sparse lexical search (BM25 / SPLADE) to catch exact keyword matches (clause numbers and course codes).
2. Execute dense semantic search for conceptual understanding.
3. Fuse the rankings using **Reciprocal Rank Fusion (RRF)**:
   $$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
This guarantees that exact clause queries surface at position 1 regardless of embedding proximity.

---

## 6. EMBED_MODEL changed on the API only: what does your system do?

**Scenario:** An operator updates `EMBED_MODEL: text-embedding-3-small` in the ConfigMap and restarts only the `api` Deployment, without running the indexer Job.

**What Our System Does:**  
In [`api/app/main.py`](../api/app/main.py#L35-L50), the API startup lifespan executes an explicit embedding pin guardrail:
```python
meta = coll.metadata or {}
coll_embed_model = meta.get("embed_model") or meta.get("embedding_model")
if coll_embed_model and coll_embed_model != settings.embed_model:
    msg = f"FATAL: Embedding model mismatch! Collection was indexed with '{coll_embed_model}' but API configured with '{settings.embed_model}'."
    log.critical(msg)
    raise RuntimeError(msg)
```
The startup check logs a critical mismatch, then its broad exception handler logs a warning and allows the process to start. [`api/app/routes/health.py`](../api/app/routes/health.py#L46-L52) independently detects the mismatch and returns HTTP 503 on `/readyz`, keeping the pod at `0/1 READY` and out of Service endpoints. The observed pod state and exact log line are in [`docs/evidence/embedding-mismatch.txt`](evidence/embedding-mismatch.txt).

**What It Would Have Done Without the Guardrail (-8 Penalty):**  
Without this guardrail, the API would have booted cleanly. When a user submitted a question, the API would embed the question using the *new* model's 1536-dimensional coordinate system, while Chroma's index contained vectors from the *old* model's 768-dimensional space (or different vector representations). The mathematical distance between vectors from two different model spaces is meaningless noise. The system would retrieve completely irrelevant chunks, fail the relevance floor, and silently abstain on valid questions without ever raising an error.

---

## 7. The failure that cost us more than an hour

**The Symptom:**  
During initial pipeline testing, queries about the university's startup equity and commercialization policy repeatedly triggered our relevance floor abstention (*"I do not have sufficient information..."*). When inspecting Chroma collection contents, the document `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` was completely absent from the chunk index (`chunks=0`), even though `corpus/fetch.py` confirmed the file existed on disk with 3,872,809 bytes.

**What We Wrongly Believed First:**  
We assumed our chunking regex (`indexer/pipeline/chunk.py`) had a bug that was discarding all paragraphs, or that `pypdf.PdfReader` was crashing silently and catching an unlogged exception in our loop. We spent over 40 minutes adding print statements and stepping through paragraph boundaries.

**The Command That Told Us the Truth:**  
We ran a quick diagnostic script inspecting the raw extracted text length of each page:
```bash
python -c "import pypdf; r = pypdf.PdfReader('corpus/raw/faculty-entrepreneurship-and-technical-start-ups-policy.pdf'); print([len(p.extract_text().strip()) for p in r.pages])"
```
**Output:**
```text
[0, 0, 0, 0, 0, 0, 0, 0]
```
Running `pdffonts` confirmed the reality: the font list was empty. The document was an **image-only scanned PDF** created from physical paper scans. Standard PDF extractors do not throw an exception when reading image pages; they simply return an empty string (`""`) because there is no digital font layer.

**The Fix:**  
We updated [`indexer/pipeline/extract.py`](../indexer/pipeline/extract.py#L88-L100) to inspect page text length. When `len(text) < 50`, it automatically routes the page through `pdf2image` and `pytesseract` to extract OCR text, stamping the chunk metadata with `ocr: true`. As soon as this was in place, all 8 pages indexed cleanly and retrieval recall jumped to 100%.
