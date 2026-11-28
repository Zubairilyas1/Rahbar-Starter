#!/usr/bin/env python3
"""Run only the verification stage (Part A1) on a folder, without indexing anything.

    python scripts/run_verification.py --corpus corpus/batch_b
    python scripts/run_verification.py --corpus corpus/batch_b --ollama-url http://127.0.0.1:11434

The folder is copied to a temporary directory first, because quarantine MOVES
failing files. The committed corpus is never modified. With --ollama-url the
near-duplicate check uses embeddings, as in the indexer Job. Without it, it falls
back to shingle Jaccard and says so in the reason column. The real pipeline run (on
the cluster) is the indexer Job; this script is for checking a batch locally.
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "indexer"))

from pipeline.config import get_settings  # noqa: E402
from pipeline.extract import extract  # noqa: E402
from pipeline.run import _front_matter, discover  # noqa: E402
from pipeline.verify import format_report_table, verify_and_quarantine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the RAGOps verification stage on a folder")
    ap.add_argument("--corpus", default="corpus/batch_b")
    ap.add_argument("--report", default=None, help="default eval/results/verification_<folder>_<timestamp>.json")
    ap.add_argument("--ollama-url", default=None, help="enable embedding near-duplicate detection")
    ap.add_argument("--near-dup-threshold", type=float, default=0.95)
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    report = Path(args.report or f"eval/results/verification_{Path(args.corpus).name}_{stamp}.json")
    embed_fn = None
    if args.ollama_url:
        from pipeline.embed import embed

        settings = dataclasses.replace(get_settings(), ollama_url=args.ollama_url)
        embed_fn = lambda texts: embed(texts, settings)  # noqa: E731

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "corpus"
        shutil.copytree(args.corpus, work)
        docs = []
        for path, version, superseded in discover(str(work)):
            meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
            meta.setdefault("doc_version", version)
            meta.setdefault("source", path.name)
            docs.append((extract(str(path), version, superseded), path, meta))
        _, rep = verify_and_quarantine(docs, quarantine_dir=Path(tmp) / "quarantine", report_path=report,
                                       embed_fn=embed_fn, near_dup_threshold=args.near_dup_threshold)
    print(format_report_table(rep))
    print(f"\nreport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
