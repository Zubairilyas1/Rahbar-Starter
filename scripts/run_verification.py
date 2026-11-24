"""Run data verification stage on any corpus directory (Part A1, RAGOps paper 4.2.1-4.2.4).
Usage:
    python scripts/run_verification.py --corpus corpus/raw
    python scripts/run_verification.py --corpus corpus/batch_b
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.pipeline.extract import extract
from indexer.pipeline.run import discover, _front_matter
from indexer.pipeline.verify import verify_and_quarantine


def run_verification(corpus_dir: str, quarantine_dir: str, report_path: str):
    print(f"\n========================================================")
    print(f"Running Data Verification on: {corpus_dir}")
    print(f"Quarantine directory:         {quarantine_dir}")
    print(f"Report output path:           {report_path}")
    print(f"========================================================\n")
    
    raw_files = discover(corpus_dir)
    if not raw_files:
        print(f"Error: No files found in {corpus_dir}")
        return 1
    
    extracted_docs = []
    for path, doc_version, superseded in raw_files:
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        if "doc_version" not in meta:
            meta["doc_version"] = doc_version
        if "source" not in meta:
            meta["source"] = path.name
            
        doc = extract(str(path), doc_version, superseded)
        extracted_docs.append((doc, path, meta))
        
    passed_docs, report = verify_and_quarantine(
        extracted_docs,
        quarantine_dir=quarantine_dir,
        report_path=report_path
    )
    
    print("\n--- VERIFICATION SUMMARY REPORT ---")
    print(f"Total Documents:     {report.total_documents}")
    print(f"Passed Documents:    {report.passed_documents}")
    print(f"Quarantined:         {report.quarantined_documents}")
    print(f"Report File:         {report_path}\n")
    
    print(f"{'Source Document':<42} | {'Status':<10} | {'Checks (Q/C/R/U)':<16} | {'Reason / Notes'}")
    print("-" * 110)
    for res in report.results:
        status_str = "PASS" if res.passed else "QUARANTINED"
        checks_str = "".join("P" if c.passed else "F" for c in res.checks)
        reasons = "; ".join(c.reason for c in res.checks if not c.passed)
        if not reasons:
            reasons = "All 4 checks passed"
        print(f"{res.source:<42} | {status_str:<10} | {checks_str:<16} | {reasons}")
    print("-" * 110 + "\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RAGOps document verification")
    parser.add_argument("--corpus", default="corpus/batch_b", help="Corpus directory to verify")
    parser.add_argument("--quarantine", default="corpus/quarantine", help="Quarantine directory")
    parser.add_argument("--report", default="eval/results/verification_report_batch_b.json", help="Report output file")
    args = parser.parse_args()
    
    sys.exit(run_verification(args.corpus, args.quarantine, args.report))
