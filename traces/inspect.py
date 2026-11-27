"""CLI Trace Inspection Tool.
Assignment 03 Part D2 (RAGOps paper 3.2.3, Table 2).

Given a trace ID, retrieves the trace record from traces/live_traces.jsonl
and prints:
1. Complete query provenance and latency breakdown.
2. The exact assembled context passages with chunk IDs, scores, and sources.
3. The exact prompt sent to the LLM.
4. The generated response, citations, and guardrail actions.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_TRACE_FILE = Path("traces/live_traces.jsonl")


def inspect_trace(trace_id: str, trace_file: Path = DEFAULT_TRACE_FILE) -> int:
    if not trace_file.exists():
        print(f"Error: Trace log file not found at {trace_file}")
        return 1

    matched_record = None
    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("trace_id") == trace_id or trace_id in record.get("trace_id", ""):
                    matched_record = record
                    break
            except Exception:
                continue

    if not matched_record:
        print(f"No trace found matching ID: '{trace_id}' in {trace_file}")
        return 1

    print("\n" + "=" * 80)
    print(f"RAHBAR RAGOps: Trace Record Inspection [{matched_record.get('trace_id')}]")
    print("=" * 80)

    print(f"Timestamp:          {matched_record.get('timestamp')}")
    print(f"User Query:         {matched_record.get('user_query')}")
    if matched_record.get("rewritten_query"):
        print(f"Rewritten Query:    {matched_record.get('rewritten_query')}")
    print(f"Embedding Model:    {matched_record.get('embedding_model')} (version: {matched_record.get('embedding_version')})")
    print(f"Collection:         {matched_record.get('collection_name')} (version: {matched_record.get('collection_version')})")
    print(f"Cache Status:       {matched_record.get('cache_status', 'miss').upper()}")
    print(f"Prompt Hash:        {matched_record.get('prompt_hash')[:16]}...")
    
    print("\n--- Latency Breakdown (ms) ---")
    latencies = matched_record.get("latency_per_stage", {})
    for stage, ms in latencies.items():
        print(f"  - {stage:<20}: {ms:>8.2f} ms")

    print("\n--- Guardrail Actions ---")
    rails = matched_record.get("guardrail_actions", [])
    if rails:
        for r in rails:
            flag = "[TRIGGERED]" if r.get("triggered") else "[PASSED]"
            print(f"  {flag:<12} Rail: {r.get('rail')} | Action: {r.get('action')} | Reason: {r.get('reason')}")
    else:
        print("  All safety and injection guardrails passed cleanly.")

    print("\n--- Retrieved Grounding Passages ---")
    chunks = matched_record.get("retrieved_chunks", [])
    if chunks:
        for idx, c in enumerate(chunks, 1):
            doc = c.get('source') or c.get('document_id') or 'unknown'
            print(f"  [{idx}] Chunk ID: {c.get('chunk_id')} | Doc: {doc} (p. {c.get('page')}) | Score: {c.get('score', 0.0):.4f}")
    else:
        print("  No passages retrieved (honest abstention triggered before retrieval).")

    print("\n--- Exact Assembled Prompt Reconstructed ---")
    print("-" * 80)
    print(matched_record.get("full_prompt", "[Prompt not captured]"))
    print("-" * 80)

    print("\n--- Generated Answer & Provenance ---")
    resp = matched_record.get("response", {})
    print(f"Answer:                 {resp.get('answer')}")
    print(f"Confidence:             {resp.get('confidence')}")
    print(f"Answered From Context:  {resp.get('answered_from_context')}")
    
    citations = matched_record.get("citations", [])
    if citations:
        print("Citations:")
        for cit in citations:
            print(f"  - {cit.get('source')} (section: {cit.get('section', 'N/A')}, p. {cit.get('page')})")
    print("=" * 80 + "\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Inspect a specific query trace by trace ID")
    parser.add_argument("trace_id", nargs="?", help="Trace ID to inspect")
    parser.add_argument("--trace-id", dest="opt_trace_id", help="Trace ID (as flag)")
    parser.add_argument("--file", default=str(DEFAULT_TRACE_FILE), help="Path to live_traces.jsonl")
    args = parser.parse_args()

    tid = args.trace_id or args.opt_trace_id
    if not tid:
        print("Error: Please provide a trace ID. Usage: python traces/inspect.py <trace_id>")
        sys.exit(1)

    sys.exit(inspect_trace(tid, Path(args.file)))


if __name__ == "__main__":
    main()
