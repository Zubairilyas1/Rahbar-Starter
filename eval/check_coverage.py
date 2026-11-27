"""Evaluation Dataset Coverage & Drift Checking Engine.
Assignment 03 Part E (RAGOps paper 3.2.3, 5.1, Figure 3).

Checks whether live production queries are adequately covered by the golden
evaluation dataset. Computes embedding cosine similarity between live queries
and golden questions to identify coverage gaps and topic drift.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path


def embed_texts(texts: list[str], model: str = "nomic-embed-text", ollama_url: str = "http://127.0.0.1:11434") -> list[list[float]]:
    """Batch-embed with the pinned embedding model (the same one the index uses)."""
    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/embed",
        data=json.dumps({"model": model, "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        vecs = json.loads(resp.read().decode("utf-8")).get("embeddings", [])
    if len(vecs) != len(texts):
        raise RuntimeError(f"expected {len(texts)} embeddings, got {len(vecs)}")
    return vecs


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def check_coverage(
    live_queries_path: Path,
    golden_path: Path,
    threshold: float = 0.80,
    model: str = "nomic-embed-text",
    ollama_url: str = "http://127.0.0.1:11434",
) -> dict:
    # 1. Load live queries
    live_queries = []
    with open(live_queries_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                live_queries.append(json.loads(line))

    # 2. Load golden dataset
    golden_questions = []
    with open(golden_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                g = json.loads(line)
                golden_questions.append({
                    "id": g.get("id", ""),
                    "question": g.get("question", ""),
                    "type": g.get("type", "ordinary"),
                })

    print(f"Loaded {len(live_queries)} live queries and {len(golden_questions)} golden evaluation questions.")
    print("Embedding questions with Ollama nomic-embed-text...")

    # Embed both sets
    live_texts = [q["query"] for q in live_queries]
    golden_texts = [g["question"] for g in golden_questions]

    live_vectors = embed_texts(live_texts, model=model, ollama_url=ollama_url)
    golden_vectors = embed_texts(golden_texts, model=model, ollama_url=ollama_url)

    covered_count = 0
    gap_count = 0
    query_reports = []
    topic_gaps = defaultdict(int)
    topic_totals = defaultdict(int)

    for lq, l_vec in zip(live_queries, live_vectors):
        max_sim = -1.0
        best_match = None

        for gq, g_vec in zip(golden_questions, golden_vectors):
            sim = cosine_similarity(l_vec, g_vec)
            if sim > max_sim:
                max_sim = sim
                best_match = gq

        is_covered = max_sim >= threshold
        topic = lq.get("topic", "general")
        topic_totals[topic] += 1

        if is_covered:
            covered_count += 1
        else:
            gap_count += 1
            topic_gaps[topic] += 1

        query_reports.append({
            "query_id": lq.get("query_id"),
            "query": lq.get("query"),
            "topic": topic,
            "max_similarity": round(max_sim, 4),
            "matched_golden_id": best_match["id"] if best_match else None,
            "matched_golden_question": best_match["question"] if best_match else None,
            "is_covered": is_covered,
        })

    coverage_pct = round((covered_count / len(live_queries)) * 100, 2)

    summary = {
        "total_live_queries": len(live_queries),
        "total_golden_questions": len(golden_questions),
        "coverage_threshold": threshold,
        "covered_queries": covered_count,
        "gap_queries": gap_count,
        "coverage_percentage": coverage_pct,
        "topic_breakdown": {
            t: {
                "total": topic_totals[t],
                "gaps": topic_gaps[t],
                "coverage_pct": round(((topic_totals[t] - topic_gaps[t]) / topic_totals[t]) * 100, 1)
            }
            for t in topic_totals
        },
        "query_details": query_reports,
    }

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Query coverage of the golden set (Part E2/E4)")
    parser.add_argument("--live", type=Path, default=Path("eval/live_queries.jsonl"), help="Live queries JSONL")
    parser.add_argument("--golden", type=Path, default=Path("eval/golden.jsonl"), help="Golden questions JSONL")
    parser.add_argument("--threshold", type=float, default=float(os.environ.get("COVERAGE_SIM_THRESHOLD", 0.75)),
                        help="cosine similarity at which a live query counts as covered by a golden question")
    parser.add_argument("--min-coverage", type=float, default=float(os.environ.get("COVERAGE_MIN_SHARE", 0.85)),
                        help="share of live queries that must be covered; below it the script exits 1 "
                             "(0.85 = the paper's example in 4.2.7)")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    parser.add_argument("--output", type=Path, default=None,
                        help="JSON report (default eval/results/coverage_<golden-name>_<timestamp>.json)")
    args = parser.parse_args()

    try:
        summary = check_coverage(args.live, args.golden, threshold=args.threshold,
                                 model=args.embed_model, ollama_url=args.ollama_url)
    except Exception as exc:  # no invented numbers when the embedder is down
        print(f"COVERAGE ERROR: {exc}", file=sys.stderr)
        return 2
    summary["min_coverage_share"] = args.min_coverage
    summary["gate_passed"] = summary["coverage_percentage"] / 100.0 >= args.min_coverage

    out = args.output or Path("eval/results") / f"coverage_{args.golden.stem}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 80)
    print("RAHBAR golden-set coverage of live queries (Part E)")
    print("=" * 80)
    print(f"live queries               : {summary['total_live_queries']}")
    print(f"golden questions           : {summary['total_golden_questions']}  ({args.golden})")
    print(f"similarity threshold       : {summary['coverage_threshold']}")
    print(f"covered                    : {summary['covered_queries']} / {summary['total_live_queries']}"
          f"  = {summary['coverage_percentage']}%   (required >= {args.min_coverage:.0%})")
    print("-" * 80)
    print(f"{'topic':<28} | {'total':>5} | {'gaps':>4} | {'coverage':>8}")
    for topic, st in sorted(summary["topic_breakdown"].items(), key=lambda kv: -kv[1]["gaps"]):
        print(f"{topic:<28} | {st['total']:>5} | {st['gaps']:>4} | {st['coverage_pct']:>7.1f}%")
    gaps = [q for q in summary["query_details"] if not q["is_covered"]]
    if gaps:
        print("-" * 80)
        print("uncovered live queries (grouped by topic):")
        by_topic: dict[str, list[dict]] = defaultdict(list)
        for g in gaps:
            by_topic[g["topic"]].append(g)
        for topic, items in sorted(by_topic.items()):
            print(f"  [{topic}]")
            for g in items:
                print(f"    {g['query_id']}  sim={g['max_similarity']:.3f}  {g['query']}")
    print("=" * 80)
    verdict = "PASS" if summary["gate_passed"] else "FAIL"
    print(f"COVERAGE {verdict}: {summary['coverage_percentage']}% vs required {args.min_coverage:.0%}   report: {out}")
    return 0 if summary["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
