"""Trace Log Metrics Summary.
Assignment 03 Part D3 (RAGOps paper 5.1, Table 2).

Summarizes operational RAG performance over a trace log:
- Top-1 retrieval similarity distribution (Min, Mean, P50, P95, Max)
- Abstention rate (%)
- Cache hit rate (%)
- P95 latency per stage (Cache, Embedding, Retrieval, Generation, Total)
- Number of prompt injection attempts flagged
"""

import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_TRACE_FILE = Path("traces/live_traces.jsonl")


def summarize_traces(trace_file: Path) -> dict:
    if not trace_file.exists():
        print(f"Error: Trace log file not found at {trace_file}")
        return {}

    records = []
    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    if not records:
        print(f"No valid trace records found in {trace_file}")
        return {}

    total_queries = len(records)
    cache_hits = sum(1 for r in records if r.get("cache_status") == "hit")
    abstentions = sum(1 for r in records if r.get("response", {}).get("answered_from_context") is False)
    
    # Top-1 similarity scores
    top1_scores = []
    for r in records:
        chunks = r.get("retrieved_chunks", [])
        if chunks:
            top1_scores.append(chunks[0].get("score", 0.0))

    # Injection attempts flagged
    injection_attempts = 0
    for r in records:
        for rail in r.get("guardrail_actions", []):
            if rail.get("rail") == "prompt_injection_guardrail" and rail.get("triggered"):
                injection_attempts += 1

    # Stage latencies
    stage_latencies: dict[str, list[float]] = {
        "cache_lookup_ms": [],
        "embedding_ms": [],
        "retrieval_ms": [],
        "generation_ms": [],
        "total_ms": [],
    }
    for r in records:
        lats = r.get("latency_per_stage", {})
        for stage, val in lats.items():
            if stage in stage_latencies:
                stage_latencies[stage].append(float(val))

    def p95(values: list[float]) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * 0.95)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    top1_scores.sort()
    min_top1 = top1_scores[0] if top1_scores else 0.0
    mean_top1 = sum(top1_scores) / len(top1_scores) if top1_scores else 0.0
    p50_top1 = top1_scores[len(top1_scores) // 2] if top1_scores else 0.0
    p95_top1 = p95(top1_scores)
    max_top1 = top1_scores[-1] if top1_scores else 0.0

    print("\n" + "=" * 75)
    print("RAHBAR RAGOps: Trace Operational Metrics Summary (Part D3)")
    print("=" * 75)
    print(f"Total Queries Processed:         {total_queries}")
    print(f"Cache Hit Rate:                  {(cache_hits / total_queries) * 100:.1f}% ({cache_hits}/{total_queries})")
    print(f"Abstention Rate:                 {(abstentions / total_queries) * 100:.1f}% ({abstentions}/{total_queries})")
    print(f"Injection Attempts Flagged:      {injection_attempts}")

    print("\n--- Top-1 Retrieval Similarity Distribution ---")
    print(f"  Min:  {min_top1:.4f}")
    print(f"  Mean: {mean_top1:.4f}")
    print(f"  P50:  {p50_top1:.4f}")
    print(f"  P95:  {p95_top1:.4f}")
    print(f"  Max:  {max_top1:.4f}")

    print("\n--- P95 Latency Per Stage (ms) ---")
    for stage, vals in stage_latencies.items():
        print(f"  - {stage:<20}: {p95(vals):>8.2f} ms")
    print("=" * 75 + "\n")

    return {
        "total_queries": total_queries,
        "cache_hit_rate_pct": round((cache_hits / total_queries) * 100, 2),
        "abstention_rate_pct": round((abstentions / total_queries) * 100, 2),
        "injection_attempts_flagged": injection_attempts,
        "top1_similarity": {
            "min": round(min_top1, 4),
            "mean": round(mean_top1, 4),
            "p50": round(p50_top1, 4),
            "p95": round(p95_top1, 4),
            "max": round(max_top1, 4),
        },
        "p95_latency_ms": {k: round(p95(v), 2) for k, v in stage_latencies.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize metrics from live query traces")
    parser.add_argument("--file", default=str(DEFAULT_TRACE_FILE), help="Path to live_traces.jsonl")
    args = parser.parse_args()

    summarize_traces(Path(args.file))


if __name__ == "__main__":
    main()
