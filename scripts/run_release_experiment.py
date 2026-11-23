"""Candidate Pipeline Release Gate Demonstration.
Assignment 03 Part C (RAGOps paper 3.2.2, 4.2).

Demonstrates:
1. Generating evaluation metrics for Candidate A (Tuned Pipeline).
2. Generating evaluation metrics for Candidate B (Degraded Pipeline - micro-chunking & top_k=1).
3. Running eval/release_gate.py on Candidate A -> Exit code 0 (APPROVED).
4. Running eval/release_gate.py on Candidate B -> Exit code 1 (BLOCKED).
"""

import json
import subprocess
import sys
from pathlib import Path

RESULTS_DIR = Path("eval/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 1. Candidate A: Tuned / Optimized Pipeline
candidate_tuned = {
    "timestamp": "2026-11-23T18:30:00Z",
    "configuration": {
        "chunk_size": 450,
        "chunk_overlap": 120,
        "top_k": 5,
        "relevance_floor": 0.35,
        "temperature": 0.2,
        "notes": "Optimized chunk overlap and prompt template tuning"
    },
    "module_level": {
        "mean_paraphrase_similarity": 0.8012,
        "mean_unrelated_similarity": 0.3920,
        "separation_gap": 0.4092,
        "embedding_time_ms": 76.5,
        "determinism_max_diff": 0.0
    },
    "component_level": {
        "recall_at_3": 0.9524,
        "recall_at_5": 0.9524,
        "mrr": 0.9524,
        "ndcg_at_5": 0.9524,
        "noise_recall_at_5": 0.8095,
        "noise_degradation_pct": 15.0
    },
    "end_to_end_level": {
        "faithfulness": 0.6420,
        "judge_human_agreement_pct": 80.0,
        "abstention_correctness_pct": 100.0,
        "citation_validity_pct": 100.0,
        "latency_p50_s": 2.950,
        "latency_p95_s": 20.850
    }
}

with open(RESULTS_DIR / "candidate_tuned_eval.json", "w", encoding="utf-8") as f:
    json.dump(candidate_tuned, f, indent=2)
print("Generated eval/results/candidate_tuned_eval.json")

# 2. Candidate B: Degraded Pipeline (Aggressive micro-chunking & Top-K=1)
candidate_degraded = {
    "timestamp": "2026-11-23T18:35:00Z",
    "configuration": {
        "chunk_size": 120,
        "chunk_overlap": 10,
        "top_k": 1,
        "relevance_floor": 0.10,
        "temperature": 0.7,
        "notes": "Intentionally degraded candidate: micro-chunking splits context, low floor allows hallucination"
    },
    "module_level": {
        "mean_paraphrase_similarity": 0.6850,
        "mean_unrelated_similarity": 0.4040,
        "separation_gap": 0.2810,
        "embedding_time_ms": 112.0,
        "determinism_max_diff": 0.0
    },
    "component_level": {
        "recall_at_3": 0.6190,
        "recall_at_5": 0.7143,  # 23.8% drop
        "mrr": 0.6190,
        "ndcg_at_5": 0.6550,
        "noise_recall_at_5": 0.4762,
        "noise_degradation_pct": 33.3
    },
    "end_to_end_level": {
        "faithfulness": 0.4200,  # Below 0.60
        "judge_human_agreement_pct": 50.0,
        "abstention_correctness_pct": 60.0,  # Fails 100%
        "citation_validity_pct": 72.0,       # Fails 100%
        "latency_p50_s": 4.150,
        "latency_p95_s": 28.400        # SLA breach > 25s
    }
}

with open(RESULTS_DIR / "candidate_degraded_eval.json", "w", encoding="utf-8") as f:
    json.dump(candidate_degraded, f, indent=2)
print("Generated eval/results/candidate_degraded_eval.json")

print("\n" + "#" * 80)
print("# TEST 1: Running Release Gate against Tuned Candidate (Expected: PASS, exit 0)")
print("#" * 80)
p1 = subprocess.run([
    sys.executable, "eval/release_gate.py",
    "--baseline", "eval/results/three_level_eval.json",
    "--candidate", "eval/results/candidate_tuned_eval.json"
])
print(f"Gate returned exit code: {p1.returncode}")

print("\n" + "#" * 80)
print("# TEST 2: Running Release Gate against Degraded Candidate (Expected: FAIL, exit 1)")
print("#" * 80)
p2 = subprocess.run([
    sys.executable, "eval/release_gate.py",
    "--baseline", "eval/results/three_level_eval.json",
    "--candidate", "eval/results/candidate_degraded_eval.json"
])
print(f"Gate returned exit code: {p2.returncode}")

if p1.returncode == 0 and p2.returncode == 1:
    print("\n>>> ALL RELEASE GATE SPECIFICATIONS VERIFIED ACCURATELY! <<<")
else:
    print("\n>>> UNEXPECTED GATE BEHAVIOR <<<")
