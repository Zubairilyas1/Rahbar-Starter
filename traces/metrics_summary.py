#!/usr/bin/env python3
"""Summarise the trace log over a time window (Assignment 03 D3, RAGOps paper 5.1, Table 2).

Reports: top-1 retrieval similarity distribution, abstention rate, cache hit rate,
p95 latency per stage, and the number of prompt-injection attempts flagged
(in queries and in retrieved context).

    python traces/metrics_summary.py                                   # everything under traces/
    python traces/metrics_summary.py --path traces/cluster --last-minutes 60
    python traces/metrics_summary.py --since 2026-11-27T10:00:00Z --until 2026-11-27T12:00:00Z
    python traces/metrics_summary.py --exclude-eval                    # live traffic only
    python traces/metrics_summary.py --json-out eval/results/trace_metrics.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_io import DEFAULT_TRACE_PATH, load_traces, parse_ts  # noqa: E402


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[max(1, math.ceil(p / 100 * len(s))) - 1]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    hits = sum(r.get("cache_status") == "hit" for r in records)
    lookups = sum(r.get("cache_status") in ("hit", "miss") for r in records)
    abstained = sum(not (r.get("response") or {}).get("answered_from_context") for r in records)
    top1 = [float(r["retrieved_chunks"][0]["score"]) for r in records if r.get("retrieved_chunks")]
    inj_query = inj_ctx = 0
    for r in records:
        for g in r.get("guardrail_actions", []):
            if g.get("rail") == "prompt_injection_guardrail" and g.get("triggered"):
                if g.get("action") == "neutralized":
                    inj_ctx += 1
                else:
                    inj_query += 1
    stages: dict[str, list[float]] = {}
    for r in records:
        for k, v in (r.get("latency_per_stage") or {}).items():
            stages.setdefault(k.removesuffix("_ms"), []).append(float(v))
    hist_edges = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
    histogram = {f"{a:.1f}-{min(b, 1.0):.1f}": sum(a <= x < b for x in top1) for a, b in zip(hist_edges, hist_edges[1:])}
    return {
        "queries": n,
        "collections": sorted({r.get("collection_name", "?") for r in records}),
        "abstention_rate": round(abstained / n, 4) if n else None,
        "cache_hit_rate": round(hits / lookups, 4) if lookups else None,
        "cache_lookups": lookups,
        "injection_attempts_flagged": inj_query + inj_ctx,
        "injection_in_query": inj_query,
        "injection_in_context": inj_ctx,
        "top1_similarity": {
            "count": len(top1),
            "min": round(min(top1), 4) if top1 else None,
            "p50": round(pct(top1, 50), 4) if top1 else None,
            "mean": round(statistics.mean(top1), 4) if top1 else None,
            "p95": round(pct(top1, 95), 4) if top1 else None,
            "max": round(max(top1), 4) if top1 else None,
            "histogram": histogram,
        },
        "p95_latency_ms": {k: round(pct(v, 95), 1) for k, v in stages.items()},
        "p50_latency_ms": {k: round(pct(v, 50), 1) for k, v in stages.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise RAGOps metrics from trace records over a time window")
    ap.add_argument("--path", "--file", dest="path", default=str(DEFAULT_TRACE_PATH))
    ap.add_argument("--since", help="UTC, e.g. 2026-11-27T10:00:00Z")
    ap.add_argument("--until", help="UTC, e.g. 2026-11-27T12:00:00Z")
    ap.add_argument("--last-minutes", type=float, help="window ending now")
    ap.add_argument("--exclude-eval", action="store_true", help="drop traces sent by the eval suite (ids eval-*)")
    ap.add_argument("--collection", help="only traces served by this collection")
    ap.add_argument("--json-out")
    args = ap.parse_args()

    records = load_traces(Path(args.path))
    since = parse_ts(args.since) if args.since else None
    until = parse_ts(args.until) if args.until else None
    if args.last_minutes:
        until = datetime.now(timezone.utc)
        since = until - timedelta(minutes=args.last_minutes)
    window = [r for r in records
              if (since is None or parse_ts(r["timestamp"]) >= since)
              and (until is None or parse_ts(r["timestamp"]) <= until)
              and not (args.exclude_eval and str(r.get("trace_id", "")).startswith("eval-"))
              and (not args.collection or r.get("collection_name") == args.collection)]

    s = summarize(window)
    lo = window[0]["timestamp"] if window else "-"
    hi = window[-1]["timestamp"] if window else "-"
    print("=" * 78)
    print(f"RAHBAR trace metrics (D3)   source={args.path}")
    print(f"window: {args.since or (since.strftime('%Y-%m-%dT%H:%M:%SZ') if since else 'start')} .. "
          f"{args.until or (until.strftime('%Y-%m-%dT%H:%M:%SZ') if until else 'end')}   "
          f"(records {lo} .. {hi})")
    print("=" * 78)
    if not window:
        print("no trace records in this window")
        return 1
    t = s["top1_similarity"]
    print(f"queries                    : {s['queries']}   collections: {', '.join(s['collections'])}")
    print(f"abstention rate            : {s['abstention_rate']:.1%}")
    print(f"cache hit rate             : {s['cache_hit_rate']:.1%} of {s['cache_lookups']} lookups"
          if s["cache_hit_rate"] is not None else "cache hit rate             : n/a (cache bypassed)")
    print(f"injection attempts flagged : {s['injection_attempts_flagged']} "
          f"(query {s['injection_in_query']}, retrieved context {s['injection_in_context']})")
    print(f"top-1 similarity           : min {t['min']}  p50 {t['p50']}  mean {t['mean']}  p95 {t['p95']}  max {t['max']}")
    print("  distribution             : " + "  ".join(f"[{k}] {v}" for k, v in t["histogram"].items()))
    print("latency per stage (ms)     :  stage           p50        p95")
    for k in s["p95_latency_ms"]:
        print(f"                              {k:<14}{s['p50_latency_ms'][k]:>8}  {s['p95_latency_ms'][k]:>9}")
    print("=" * 78)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps({"window": {"since": args.since, "until": args.until,
                                                              "last_minutes": args.last_minutes}, **s}, indent=2),
                                       encoding="utf-8")
        print(f"written {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
