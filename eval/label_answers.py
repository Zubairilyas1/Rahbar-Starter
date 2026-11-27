#!/usr/bin/env python3
"""Hand-label answers for the faithfulness judge calibration (Part B, end-to-end).

The suite asks an LLM judge whether each answer is supported by its retrieved
context. The assignment requires at least 8 answers labelled by a human and the
agreement rate. This tool shows you the question, the retrieved context and the
answer from a result file, asks for your verdict, saves it to
eval/human_labels.jsonl, and writes the agreement back into the result file.

    python eval/label_answers.py --result eval/results/latest_baseline.json --n 8 --labeller "Zubair"

Labels are keyed by question id AND a hash of the answer text, so a label is
only ever compared with the exact answer the human read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def answer_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--labels", default=str(HERE / "human_labels.jsonl"))
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--labeller", required=True)
    ap.add_argument("--golden", default=str(HERE / "golden.jsonl"))
    args = ap.parse_args()

    result_path = Path(args.result)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    per_q = result["runs"][0]["per_question"]
    golden = {json.loads(l)["id"]: json.loads(l) for l in Path(args.golden).read_text(encoding="utf-8").splitlines() if l.strip()}

    labels_path = Path(args.labels)
    labels = {}
    if labels_path.exists():
        for line in labels_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                labels[(row["id"], row["answer_sha"])] = row

    judged = [(qid, row) for qid, row in per_q.items() if "judge_supported" in row]
    todo = [(q, r) for q, r in judged if (q, answer_hash(r["answer"])) not in labels]
    print(f"{len(judged)} judged answers, {len(judged) - len(todo)} already labelled.\n")

    done = 0
    for qid, row in todo:
        if sum(1 for q, r in judged if (q, answer_hash(r["answer"])) in labels) >= args.n:
            break
        g = golden.get(qid, {})
        print("=" * 100)
        print(f"[{qid}] {row['question']}")
        print(f"Expected (golden): {g.get('expected_answer', '-')}  [{g.get('ground_truth_doc')} p.{g.get('ground_truth_page')}]")
        print(f"Retrieved top-5:   {row.get('retrieved_top5')}")
        print(f"Cited:             {row.get('citations')}")
        print(f"\nANSWER: {row['answer']}\n")
        verdict = ""
        while verdict not in ("y", "n", "s"):
            verdict = input("Is every claim supported by the retrieved context? [y]es / [n]o / [s]kip: ").strip().lower()
        if verdict == "s":
            continue
        note = input("Short note (optional): ").strip()
        labels[(qid, answer_hash(row["answer"]))] = {
            "id": qid, "answer_sha": answer_hash(row["answer"]), "faithful": verdict == "y",
            "labelled_by": args.labeller, "note": note, "answer": row["answer"],
        }
        done += 1
        labels_path.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in labels.values()) + "\n", encoding="utf-8")

    compared = agree = 0
    disagreements = []
    for qid, row in judged:
        lab = labels.get((qid, answer_hash(row["answer"])))
        if lab is None:
            continue
        compared += 1
        if lab["faithful"] == row["judge_supported"]:
            agree += 1
        else:
            disagreements.append(qid)
    e2e = result["end_to_end_level"]
    e2e["judge_human_compared"] = compared
    e2e["judge_human_agreement"] = round(agree / compared, 4) if compared else None
    e2e["judge_human_disagreements"] = disagreements
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nLabelled {done} new answers. Judge/human agreement: {agree}/{compared}"
          f" = {e2e['judge_human_agreement']}. Disagreements: {disagreements or 'none'}")
    print(f"Updated {result_path} and {labels_path}")
    return 0 if compared >= args.n else 1


if __name__ == "__main__":
    raise SystemExit(main())
