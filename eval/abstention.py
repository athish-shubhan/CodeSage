"""Measures how well a dense-similarity threshold separates answerable from
unanswerable questions, from one dense run with abstention off.

For each candidate threshold: the fraction of unanswerable questions that
would abstain (good), the fraction of answerable ones that would abstain
(bad, each costs recall), and the resulting Recall@K. The threshold is
chosen on the same questions it is reported on, so the numbers are
optimistic; the size of the score gap between the two groups is the more
honest signal of whether a threshold will generalize.

Usage: python abstention.py [--target host:port] [--collection codebase]
"""
from __future__ import annotations

import argparse

from run_eval import run


def sweep(per_question: list[dict], thresholds: list[float]) -> list[dict]:
    answerable = [r for r in per_question if r["recall"] is not None]
    unanswerable = [r for r in per_question if r["category"] == "unanswerable"]
    rows = []
    for t in thresholds:
        kept_recall = [r["recall"] if r["top_dense_score"] >= t else 0.0 for r in answerable]
        rows.append(
            {
                "threshold": t,
                "unanswerable_abstained": sum(r["top_dense_score"] < t for r in unanswerable) / len(unanswerable),
                "answerable_abstained": sum(r["top_dense_score"] < t for r in answerable) / len(answerable),
                "recall_at_k": sum(kept_recall) / len(answerable),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="localhost:50051")
    parser.add_argument("--collection", default="codebase")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    summary = run(args.target, args.collection, args.top_k, "dense", False)
    per_q = summary["per_question"]

    print("| Question | Category | Top dense score |")
    print("|---|---|---|")
    for r in sorted(per_q, key=lambda r: r["top_dense_score"]):
        print(f"| {r['id']} | {r['category']} | {r['top_dense_score']:.3f} |")

    print("\n| Threshold | Unanswerable abstained | Answerable abstained | Recall@K |")
    print("|---|---|---|---|")
    for row in sweep(per_q, [round(0.05 * i, 2) for i in range(0, 15)]):
        print(
            f"| {row['threshold']:.2f} | {row['unanswerable_abstained']:.2f} | "
            f"{row['answerable_abstained']:.2f} | {row['recall_at_k']:.2f} |"
        )


if __name__ == "__main__":
    main()
