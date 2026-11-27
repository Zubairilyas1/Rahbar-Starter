"""Load trace records for the report scripts (Assignment 03 D2/D3/D5, F4).

Accepts any of:
  * one JSON-lines file           traces/live_traces.jsonl
  * a directory of them           traces/cluster/        (one file per API pod, copied
                                                          from the rahbar-traces volume)
  * saved `kubectl logs` output   kubectl logs deploy/api -n rahbar > api.log
Lines that are not trace records (ordinary JSON log lines, uvicorn text) are skipped.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TRACE_PATH = Path("traces")


def _files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.suffix in (".jsonl", ".log", ".txt") and p.is_file())
    return [path]


def iter_traces(path: Path) -> Iterator[dict[str, Any]]:
    for f in _files(path):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("TRACE: "):        # traces written by the Assignment 02 API
                    line = line[len("TRACE: "):]
                if not line.startswith("{"):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("record_type") == "trace" or ("trace_id" in rec and "user_query" in rec):
                    yield rec


def load_traces(path: Path) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for rec in iter_traces(path):
        seen[rec["trace_id"]] = rec      # the same trace can be in a file and in a log dump
    return sorted(seen.values(), key=lambda r: r.get("timestamp", ""))


def find_trace(path: Path, trace_id: str) -> dict[str, Any] | None:
    exact = None
    prefix = None
    for rec in iter_traces(path):
        tid = rec.get("trace_id", "")
        if tid == trace_id:
            exact = rec
        elif prefix is None and tid.startswith(trace_id):
            prefix = rec
    return exact or prefix


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
