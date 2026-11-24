"""Evaluation Dataset Coverage & Drift Checking Engine.
Assignment 03 Part E (RAGOps paper 3.2.3, 5.1, Figure 3).

Checks whether live production queries are adequately covered by the golden
evaluation dataset. Computes embedding cosine similarity between live queries
and golden questions to identify coverage gaps and topic drift.
"""

import argparse
import json
import math
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path


def embed_texts(texts: list[str], model: str = "nomic-embed-text", ollama_url: str = "http://127.0.0.1:11434") -> list[list[float]]:
    embeddings = []
    for text in texts:
        req = urllib.request.Request(
            f"{ollama_url}/api/embeddings",
            data=json.dumps({"model": model, "prompt": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode("utf-8"))
        embeddings.append(data["embedding"])
    return embeddings


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


def main():
    parser = argparse.ArgumentParser(description="Check evaluation golden set coverage against live production queries")
    parser.add_argument("--live", type=Path, default=Path("eval/live_queries.jsonl"), help="Live queries JSONL")
    parser.add_argument("--golden", type=Path, default=Path("eval/golden.jsonl"), help="Golden questions JSONL")
    parser.add_argument("--threshold", type=float, default=0.78, help="Cosine similarity coverage threshold")
    parser.add_argument("--output", type=Path, default=Path("eval/results/coverage_report.json"), help="Output JSON report")
    args = parser.parse_args()

    summary = check_coverage(args.live, args.golden, threshold=args.threshold)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("RAHBAR RAGOps: Golden Dataset Coverage & Drift Report (Part E)")
    print("=" * 80)
    print(f"Total Live Queries:         {summary['total_live_queries']}")
    print(f"Golden Questions:           {summary['total_golden_questions']}")
    print(f"Similarity Threshold:       {summary['coverage_threshold']}")
    print(f"Covered Queries:            {summary['covered_queries']} / {summary['total_live_queries']}")
    print(f"Coverage Gaps (Drift):      {summary['gap_queries']}")
    print(f"Overall Coverage Rate:      {summary['coverage_percentage']}%")
    print("-" * 80)
    print(f"{'Topic':<25} | {'Total':<6} | {'Gaps':<6} | {'Coverage %':<10}")
    print("-" * 80)
    for topic, stats in summary["topic_breakdown"].items():
        print(f"{topic:<25} | {stats['total']:<6} | {stats['gaps']:<6} | {stats['coverage_pct']:<10.1f}%")
    print("=" * 80)

    # Print top 5 coverage gaps
    gaps = [q for q in summary["query_details"] if not q["is_covered"]]
    if gaps:
        print("\n--- Top Uncovered Queries Needing Golden Test Cases ---")
        for g in gaps[:5]:
            print(f"  [{g['query_id']}] ({g['topic']}) sim={g['max_similarity']:.4f}: {g['query']}")
    print()


if __name__ == "__main__":
    main()
