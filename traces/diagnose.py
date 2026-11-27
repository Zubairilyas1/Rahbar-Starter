#!/usr/bin/env python3
"""Root cause from the trace only (Assignment 03 D5, RAGOps paper 3.2.3, 5.1).

Reads ONE trace record and points at the stage, chunk, document version or filter
that explains a wrong or abstained answer. It uses nothing but the trace.

    python traces/diagnose.py <trace_id> [--path traces/cluster]

Rules, in order:
  injection        a guardrail flagged an instruction in the query or a chunk
  below floor      top-1 similarity under the relevance floor -> retrieval gap
  filter/version   the filter excluded superseded chunks, or retrieved chunks mix
                   document versions of the same document
  generation       chunks above the floor but the model abstained / cited nothing
                   valid -> generation or citation-verification stage
  near-floor       answered, but top-1 within 0.05 of the floor -> fragile retrieval
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_io import DEFAULT_TRACE_PATH, find_trace, load_traces  # noqa: E402


def diagnose(rec: dict) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    chunks = rec.get("retrieved_chunks", [])
    resp = rec.get("response", {})
    params = rec.get("parameters", {})
    floor = float(params.get("relevance_floor", 0.5))
    top1 = float(chunks[0]["score"]) if chunks else 0.0
    answered = bool(resp.get("answered_from_context"))
    findings: list[tuple[str, str]] = []

    for g in rec.get("guardrail_actions", []):
        if g.get("rail") == "prompt_injection_guardrail" and g.get("triggered"):
            where = f"chunk {g.get('chunk_id')} of {g.get('document_id')}" if g.get("chunk_id") else "the user query"
            findings.append(("guardrail", f"injection-like instruction in {where}: action={g.get('action')}"))

    if not chunks:
        findings.append(("retrieval", "nothing retrieved: the collection returned no chunk for this filter"))
    elif top1 < floor:
        findings.append(("retrieval", f"top-1 similarity {top1:.4f} < relevance floor {floor:.2f} -> abstained "
                                      f"before generation; best chunk {chunks[0]['chunk_id']} "
                                      f"({chunks[0].get('document_id')} p.{chunks[0].get('page')}) is off-topic: "
                                      "corpus/golden gap"))

    flt = rec.get("filters_applied") or {}
    if flt.get("superseded") is False:
        findings.append(("filter", "filter superseded=False was applied: archived versions were excluded"))
    versions = defaultdict(set)
    for c in chunks:
        versions[c.get("document_id")].add(c.get("doc_version"))
    for doc, vs in versions.items():
        if len(vs) > 1:
            findings.append(("version", f"{doc} retrieved in several versions {sorted(map(str, vs))}"))

    if chunks and top1 >= floor and not answered:
        cited = rec.get("citations", [])
        findings.append(("generation", f"retrieval passed the floor (top-1 {top1:.4f}, chunk {chunks[0]['chunk_id']} "
                                       f"from {chunks[0].get('document_id')} v{chunks[0].get('doc_version')} "
                                       f"p.{chunks[0].get('page')}) but the model abstained"
                                       + (" / its citations failed verification" if not cited else "")))
    if answered and chunks and top1 < floor + 0.05:
        findings.append(("retrieval", f"answered with top-1 {top1:.4f}, within 0.05 of the floor: fragile"))
    if not findings:
        findings.append(("ok", "no anomaly visible in the trace"))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Root-cause a trace using only the trace record")
    ap.add_argument("trace_id", nargs="?", help="trace id (default: newest trace)")
    ap.add_argument("--path", "--file", dest="path", default=str(DEFAULT_TRACE_PATH))
    args = ap.parse_args()

    if args.trace_id:
        rec = find_trace(Path(args.path), args.trace_id)
    else:
        all_recs = load_traces(Path(args.path))
        rec = all_recs[-1] if all_recs else None
    if rec is None:
        print(f"trace not found under {args.path}")
        return 1

    resp = rec.get("response", {})
    print("=" * 96)
    print(f"ROOT CAUSE FROM TRACE {rec['trace_id']}  ({rec.get('timestamp')})")
    print("=" * 96)
    print(f"query      : {rec.get('user_query')}")
    print(f"collection : {rec.get('collection_name')} v{rec.get('collection_version')}  "
          f"embed {rec.get('embedding_model')} {rec.get('embedding_version')}")
    print(f"filters    : {json.dumps(rec.get('filters_applied'))}   params: {json.dumps(rec.get('parameters'))}")
    print(f"answer     : answered_from_context={resp.get('answered_from_context')}  {resp.get('answer', '')[:150]}")
    print("chunks     :")
    for i, c in enumerate(rec.get("retrieved_chunks", []), 1):
        print(f"  [{i}] {c.get('score'):.4f}  {c.get('chunk_id')}  {c.get('document_id')} "
              f"v{c.get('doc_version')} p.{c.get('page')}")
    print("-" * 96)
    for stage, text in diagnose(rec):
        print(f"[{stage}] {text}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
