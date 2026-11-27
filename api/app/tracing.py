"""Structured Query Tracing Engine.
Assignment 03 Part D1 & D4 (RAGOps paper 3.2.3, 5.1, Table 2).

Captures complete provenance for every user query:
- trace id, timestamp, user query, rewritten query
- embedding model & collection version
- retrieved chunks with scores and document metadata
- filters applied & prompt hash
- model parameters & full assembled prompt
- response, citations & guardrail actions
- latency per stage & cache status
Writes JSON lines to stdout and traces/live_traces.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("rahbar.tracing")

env_path = os.environ.get("TRACE_LOG_PATH")
if env_path:
    DEFAULT_TRACE_LOG_PATH = Path(env_path)
elif (Path.cwd().parent / "traces").exists():
    DEFAULT_TRACE_LOG_PATH = Path.cwd().parent / "traces" / "live_traces.jsonl"
else:
    DEFAULT_TRACE_LOG_PATH = Path.cwd() / "traces" / "live_traces.jsonl"


@dataclass
class RetrievedChunkTrace:
    chunk_id: str
    document_id: str
    doc_version: str
    score: float
    page: int
    section: str = ""


@dataclass
class GuardrailActionTrace:
    rail: str
    action: str  # "flagged", "neutralized", "passed", "abstained"
    reason: str
    triggered: bool = False


@dataclass
class TraceRecord:
    trace_id: str
    timestamp: str
    user_query: str
    rewritten_query: str | None
    embedding_model: str
    embedding_version: str
    collection_name: str
    collection_version: str
    retrieved_chunks: list[dict[str, Any]]
    filters_applied: dict[str, Any]
    reranked_order: list[str]
    prompt_hash: str
    full_prompt: str
    model: str
    parameters: dict[str, Any]
    response: dict[str, Any]
    citations: list[dict[str, Any]]
    guardrail_actions: list[dict[str, Any]]
    latency_per_stage: dict[str, float]
    cache_status: str  # "hit" | "miss"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def compute_prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def log_trace(record: TraceRecord, log_path: Path = DEFAULT_TRACE_LOG_PATH) -> None:
    """Emits trace as structured JSON to stdout and appends to traces/live_traces.jsonl."""
    json_line = record.to_json()
    
    # 1. Output to stdout (readable via kubectl logs)
    print(f"TRACE: {json_line}", flush=True)

    # 2. Append to persistent trace log volume
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_line + "\n")
    except Exception as e:
        log.warning(f"Could not append trace to {log_path}: {e}")
