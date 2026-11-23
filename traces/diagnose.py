"""Root-Cause Diagnosis Engine.
Assignment 03 Part D5 (RAGOps paper 3.2.3, 5.1, Table 2).

Given a trace ID, automatically diagnoses the root cause of degraded, abstained,
or unexpected responses into one of five canonical failure modes:
1. Retrieval Failure (Knowledge Gap / Low Relevance)
2. Wrong Chunk / Version Conflict (Superseded or Irrelevant passage retrieved)
3. Context Truncation (Context length exceeded model limit)
4. Generation Hallucination (LLM hallucinated citations or facts not in retrieved context)
5. Adversarial Injection Attempt (Prompt injection detected and blocked)
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_TRACE_FILE = Path("traces/live_traces.jsonl")


def diagnose_trace(trace_id: str, trace_file: Path = DEFAULT_TRACE_FILE) -> int:
    if not trace_file.exists():
        print(f"Error: Trace file not found at {trace_file}")
        return 1

    record = None
    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("trace_id") == trace_id or trace_id in data.get("trace_id", ""):
                    record = data
                    break
            except Exception:
                continue

    if not record:
        print(f"Trace ID '{trace_id}' not found.")
        return 1

    print("\n" + "=" * 80)
    print(f"RAHBAR RAGOps: Root-Cause Diagnosis Report [{record.get('trace_id')}]")
    print("=" * 80)
    print(f"Query:         {record.get('user_query')}")
    print(f"Timestamp:     {record.get('timestamp')}")
    print(f"Provider:      {record.get('model')}")
    print(f"Cache Status:  {record.get('cache_status', 'miss').upper()}")

    retrieved = record.get("retrieved_chunks", [])
    response = record.get("response", {})
    rails = record.get("guardrail_actions", [])
    prompt = record.get("full_prompt", "")
    citations = record.get("citations", [])

    diagnosis = []
    recommendation = []

    # Check 1: Adversarial Prompt Injection
    injections = [r for r in rails if r.get("rail") == "prompt_injection_guardrail" and r.get("triggered")]
    if injections:
        diagnosis.append({
            "stage": "Security / Guardrail Stage",
            "root_cause": "ADVERSARIAL_PROMPT_INJECTION",
            "confidence": 1.0,
            "evidence": f"Instruction override pattern detected: '{injections[0].get('reason')}'",
        })
        recommendation.append("Maintain strict system prompt delimiters and honeypot canary tokens.")

    # Check 2: Low Retrieval Similarity / Knowledge Gap
    max_score = max([c.get("score", 0.0) for c in retrieved]) if retrieved else 0.0
    if not response.get("answered_from_context") and max_score < 0.35:
        diagnosis.append({
            "stage": "Retrieval Stage",
            "root_cause": "RETRIEVAL_FAILURE_KNOWLEDGE_GAP",
            "confidence": 0.95,
            "evidence": f"Top-1 retrieval score ({max_score:.4f}) is below relevance floor (0.3500). System abstained honestly.",
        })
        recommendation.append("Expand the corpus with domain documents covering this topic or evaluate query expansion.")

    # Check 3: Superseded / Version Conflict
    superseded_chunks = [c for c in retrieved if "2023" in c.get("document_id", "") or "2024" in c.get("document_id", "")]
    if superseded_chunks and any("2026" in c.get("document_id", "") for c in retrieved):
        diagnosis.append({
            "stage": "Indexing / Metadata Filter Stage",
            "root_cause": "VERSION_CONFLICT_SUPERSEDED_DOCUMENT",
            "confidence": 0.85,
            "evidence": f"Retrieved mix of active and superseded documents: {[c.get('document_id') for c in retrieved]}",
        })
        recommendation.append("Enforce strict metadata filter {'superseded': {'$ne': True}} during Chroma query.")

    # Check 4: Context Truncation
    if len(prompt) > 8000:
        diagnosis.append({
            "stage": "Augmented Prompt Stage",
            "root_cause": "CONTEXT_TRUNCATION",
            "confidence": 0.90,
            "evidence": f"Prompt length ({len(prompt)} chars) exceeds model attention window. Tail passages may be lost.",
        })
        recommendation.append("Reduce top_k or tune chunk size to prevent context overflow.")

    # Check 5: Hallucination / Ungrounded Citations
    if response.get("answered_from_context") and not citations and len(retrieved) > 0:
        diagnosis.append({
            "stage": "Generation / Verification Stage",
            "root_cause": "GENERATION_UNGROUNDED_SYNTHESIS",
            "confidence": 0.80,
            "evidence": "Model generated answer but citations could not be verified against retrieved passages and were dropped.",
        })
        recommendation.append("Increase temperature constraint (T<=0.2) or apply strict Pydantic citation grounding.")

    if not diagnosis:
        diagnosis.append({
            "stage": "End-to-End Pipeline",
            "root_cause": "NOMINAL_EXECUTION",
            "confidence": 1.0,
            "evidence": "Query answered successfully with verified citations and high confidence.",
        })
        recommendation.append("No remediation required.")

    print("\n--- Diagnostic Findings ---")
    for d in diagnosis:
        print(f"Stage:          {d['stage']}")
        print(f"Root Cause:     {d['root_cause']} (Confidence: {d['confidence']*100:.0f}%)")
        print(f"Evidence:       {d['evidence']}")
        print()

    print("--- Remediation Recommendations ---")
    for r in recommendation:
        print(f"  * {r}")
    print("=" * 80 + "\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Diagnose root causes of query failures from traces")
    parser.add_argument("trace_id", nargs="?", help="Trace ID to diagnose")
    args = parser.parse_args()

    trace_id = args.trace_id
    if not trace_id:
        if DEFAULT_TRACE_FILE.exists():
            with open(DEFAULT_TRACE_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                if lines:
                    trace_id = json.loads(lines[-1]).get("trace_id")
    if not trace_id:
        print("Please provide a trace ID or ensure traces/live_traces.jsonl exists.")
        return 1

    return diagnose_trace(trace_id)


if __name__ == "__main__":
    sys.exit(main())
