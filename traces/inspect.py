#!/usr/bin/env python3
"""Trace tool (Assignment 03 D2, RAGOps paper 3.2.3, Table 2).

Takes a trace id and prints the exact context and prompt that produced that answer,
with the provenance needed to reproduce it (collection + version, embedding model +
version, filters, model parameters, per-stage latency, guardrail actions).

    python traces/inspect.py <trace_id>                      # searches traces/ recursively
    python traces/inspect.py <trace_id> --path traces/cluster
    python traces/inspect.py <trace_id> --path api.log       # saved `kubectl logs` output
    python traces/inspect.py <trace_id> --json               # the raw record

A unique prefix of the id is enough.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# PDF text contains ligatures/symbols; never crash on a cp1252 console or pipe.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from trace_io import DEFAULT_TRACE_PATH, find_trace  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Print the exact context and prompt behind a trace id")
    ap.add_argument("trace_id")
    ap.add_argument("--path", "--file", dest="path", default=str(DEFAULT_TRACE_PATH))
    ap.add_argument("--since", help="only traces at/after this UTC time (when an id repeats across runs)")
    ap.add_argument("--until", help="only traces at/before this UTC time")
    ap.add_argument("--json", action="store_true", help="print the raw trace record")
    args = ap.parse_args()

    rec = find_trace(Path(args.path), args.trace_id, args.since, args.until)
    if rec is None:
        print(f"No trace matching '{args.trace_id}' under {args.path}")
        return 1
    if args.json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0

    bar = "=" * 96
    print(bar)
    print(f"TRACE {rec['trace_id']}   {rec.get('timestamp')}")
    print(bar)
    print(f"user query        : {rec.get('user_query')}")
    print(f"rewritten query   : {rec.get('rewritten_query')}")
    print(f"pipeline version  : {rec.get('pipeline_version', '-')}")
    print(f"collection        : {rec.get('collection_name')}  (version {rec.get('collection_version')})")
    print(f"embedding model   : {rec.get('embedding_model')}  (version {rec.get('embedding_version')})")
    print(f"filters applied   : {json.dumps(rec.get('filters_applied'))}")
    print(f"model / params    : {rec.get('model')}  {json.dumps(rec.get('parameters'))}")
    print(f"cache             : {rec.get('cache_status')}")
    lat = rec.get("latency_per_stage", {})
    print("latency (ms)      : " + ", ".join(f"{k.removesuffix('_ms')}={v}" for k, v in lat.items()))

    print("\n--- retrieved context (reranked order) " + "-" * 57)
    for i, c in enumerate(rec.get("retrieved_chunks", []), 1):
        doc = c.get("document_id") or c.get("source")
        print(f"[{i}] score={c.get('score'):.4f}  chunk={c.get('chunk_id')}  doc={doc}  "
              f"version={c.get('doc_version', '-')}  page={c.get('page')}  section={c.get('section', '')}")
    if not rec.get("retrieved_chunks"):
        print("(nothing retrieved)")

    print("\n--- guardrail actions " + "-" * 74)
    for g in rec.get("guardrail_actions", []):
        print(f"{g.get('rail')}: {g.get('action')}  -- {g.get('reason')}")

    prompt = rec.get("full_prompt", "")
    ok = hashlib.sha256(prompt.encode("utf-8")).hexdigest() == rec.get("prompt_hash")
    print(f"\n--- exact prompt sent to the model (sha256 {str(rec.get('prompt_hash'))[:16]}..., "
          f"hash {'VERIFIED' if ok else 'MISMATCH'}) " + "-" * 10)
    print(prompt)

    resp = rec.get("response", {})
    print("\n--- response " + "-" * 83)
    print(f"answered_from_context={resp.get('answered_from_context')}  confidence={resp.get('confidence')}  "
          f"provider={resp.get('provider')}")
    print(resp.get("answer", ""))
    print("citations: " + ", ".join(f"{c.get('source')} p.{c.get('page')}" for c in rec.get("citations", [])))
    print(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
