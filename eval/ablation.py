"""Ablation: runs the retrieval eval across strategies (dense-only /
lexical-only / hybrid / hybrid+rerank) and writes a comparison report --
the empirical answer to "did this added complexity actually help?" rather
than an assumption. See docs/evaluation.md for how to read the result.

Usage: python ablation.py [--target host:port] [--collection codebase]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from run_eval import run

CONFIGS = [
    ("dense", False, "dense only"),
    ("lexical", False, "lexical (BM25) only"),
    ("hybrid", False, "hybrid (dense + lexical, fused)"),
    ("hybrid", True, "hybrid + reranker"),
]

REPORT_PATH = Path(__file__).parent / "report.md"


def render_report(rows: list[dict], n: int, corpus_note: str) -> str:
    lines = [
        "# CodeSage retrieval ablation report",
        "",
        f"N = {n} hand-written questions against this repo's own content "
        f"({corpus_note}). Small-N by design: this is a demo-scale benchmark, "
        "not a claim of statistical significance. The harness itself is corpus-agnostic.",
        "",
        "| Strategy | Recall@K | MRR | Avg latency (ms) | Avg context tokens |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['recall_at_k']:.2f} | {row['mrr']:.2f} | "
            f"{row['avg_latency_ms']:.0f} | {row['avg_context_tokens']:.0f} |"
        )
    lines.append("")

    best = max(rows, key=lambda r: r["recall_at_k"])
    baseline = next(r for r in rows if r["label"] == "dense only")
    if best["label"] == baseline["label"]:
        lines.append(
            "**Finding:** hybrid retrieval and reranking did not improve Recall@K over dense-only "
            "on this corpus/benchmark. The simpler dense-only path is what should ship as the "
            "default until a larger corpus or benchmark shows otherwise."
        )
    else:
        delta = best["recall_at_k"] - baseline["recall_at_k"]
        lines.append(
            f"**Finding:** {best['label']} improved Recall@K by {delta:+.2f} over dense-only "
            f"({baseline['recall_at_k']:.2f} -> {best['recall_at_k']:.2f}), at "
            f"{best['avg_latency_ms'] - baseline['avg_latency_ms']:+.0f}ms extra average latency."
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="localhost:50051")
    parser.add_argument("--collection", default="codebase")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    rows = []
    n = 0
    for strategy, use_reranker, label in CONFIGS:
        summary = run(args.target, args.collection, args.top_k, strategy, use_reranker)
        n = summary["n"]
        rows.append({**summary, "label": label})
        print(f"{label}: recall@{args.top_k}={summary['recall_at_k']:.2f} mrr={summary['mrr']:.2f}")

    report = render_report(rows, n, f"collection={args.collection}")
    REPORT_PATH.write_text(report)
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
