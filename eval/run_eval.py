"""Retrieval evaluation: Recall@K and MRR against eval/qa_pairs.jsonl.

Deterministic: knowing the right *files* for a question doesn't need an
LLM judge, just a set comparison. Talks to a running retrieval-service over
gRPC (the same client gateway-api uses), so this exercises the real
service's fusion/rerank/budgeting pipeline, not an in-process shortcut.

Usage:
    python -m grpc_tools.protoc -I ../services/retrieval-service/proto \\
        --python_out=. --grpc_python_out=. \\
        ../services/retrieval-service/proto/retrieval.proto
    python run_eval.py --strategy dense
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

import grpc

sys.path.insert(0, str(Path(__file__).parent))
import retrieval_pb2  # noqa: E402
import retrieval_pb2_grpc  # noqa: E402

DEFAULT_QA_PATH = Path(__file__).parent / "qa_pairs.jsonl"


def load_qa_pairs(path: Path = DEFAULT_QA_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def search(
    stub,
    query: str,
    top_k: int,
    collection: str,
    strategy: str,
    use_reranker: bool,
    min_score: float = 0.0,
    timeout: float | None = None,
) -> dict:
    req = retrieval_pb2.SearchRequest(
        query=query,
        top_k=top_k,
        collection=collection,
        strategy=strategy,
        use_reranker=use_reranker,
        min_score=min_score,
    )
    # Reranking costs a cross-encoder forward pass per candidate; on CPU
    # that is meaningfully slower than plain fusion, so it gets a longer
    # deadline rather than failing under load.
    start = time.perf_counter()
    resp = stub.Search(req, timeout=timeout or (60 if use_reranker else 30))
    latency_ms = (time.perf_counter() - start) * 1000
    return {
        "paths": [c.source_path for c in resp.chunks],
        "latency_ms": latency_ms,
        "context_tokens": resp.context_tokens,
        "top_dense_score": resp.top_dense_score,
    }


def recall_at_k(retrieved: list[str], expected: list[str]) -> float | None:
    if not expected:
        return None  # unanswerable case, not a retrieval-recall question
    return 1.0 if any(p in retrieved for p in expected) else 0.0


def reciprocal_rank(retrieved: list[str], expected: list[str]) -> float | None:
    if not expected:
        return None
    for i, p in enumerate(retrieved):
        if p in expected:
            return 1.0 / (i + 1)
    return 0.0


def unanswerable_is_clean(retrieved: list[str]) -> bool:
    """For an unanswerable question, a clean result is an empty or
    near-empty retrieval, not confidently returning unrelated files."""
    return len(retrieved) == 0


def bootstrap_ci(values: list[float], iterations: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile-bootstrap interval for the mean. Seeded so a report is
    reproducible. With ~20 questions this interval is wide, and showing it is
    the point: a 0.05 difference between two strategies is inside the noise."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return (means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1])


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def run(
    target: str,
    collection: str,
    top_k: int,
    strategy: str,
    use_reranker: bool,
    qa_path: Path = DEFAULT_QA_PATH,
    min_score: float = 0.0,
) -> dict:
    channel = grpc.insecure_channel(target)
    stub = retrieval_pb2_grpc.RetrievalStub(channel)
    qa_pairs = load_qa_pairs(qa_path)

    # Untimed warm-up: the first query of a config may load (or download) the
    # embedding or reranker model, which is a cold-start cost, not per-query latency.
    search(stub, qa_pairs[0]["question"], top_k, collection, strategy, use_reranker, min_score, timeout=900)

    per_question = []
    for qa in qa_pairs:
        result = search(stub, qa["question"], top_k, collection, strategy, use_reranker, min_score)
        per_question.append(
            {
                "id": qa["id"],
                "category": qa["category"],
                "retrieved": result["paths"],
                "latency_ms": result["latency_ms"],
                "context_tokens": result["context_tokens"],
                "top_dense_score": result["top_dense_score"],
                "recall": recall_at_k(result["paths"], qa["expected_paths"]),
                "rr": reciprocal_rank(result["paths"], qa["expected_paths"]),
            }
        )

    scored = [r for r in per_question if r["recall"] is not None]
    unanswerable = [r for r in per_question if r["category"] == "unanswerable"]

    latencies = [r["latency_ms"] for r in per_question]
    return {
        "strategy": strategy,
        "use_reranker": use_reranker,
        "min_score": min_score,
        "n": len(qa_pairs),
        "n_scored": len(scored),
        "recall_at_k": sum(r["recall"] for r in scored) / len(scored) if scored else 0.0,
        "recall_ci95": bootstrap_ci([r["recall"] for r in scored]),
        "mrr": sum(r["rr"] for r in scored) / len(scored) if scored else 0.0,
        "avg_latency_ms": statistics.fmean(latencies),
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "avg_context_tokens": sum(r["context_tokens"] for r in per_question) / len(per_question),
        "unanswerable_clean_rate": (
            sum(unanswerable_is_clean(r["retrieved"]) for r in unanswerable) / len(unanswerable)
            if unanswerable
            else None
        ),
        "per_question": per_question,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="localhost:50051")
    parser.add_argument("--collection", default="codebase")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--strategy", default="dense", choices=["hybrid", "dense", "lexical"])
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--qa-pairs", type=Path, default=DEFAULT_QA_PATH)
    parser.add_argument("--min-recall", type=float, default=None, help="exit 1 if recall_at_k is below this")
    parser.add_argument("--min-score", type=float, default=0.0, help="abstention threshold, see abstention.py")
    args = parser.parse_args()

    summary = run(
        args.target, args.collection, args.top_k, args.strategy, args.rerank, args.qa_pairs, args.min_score
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "per_question"}, indent=2))

    if args.min_recall is not None and summary["recall_at_k"] < args.min_recall:
        print(f"FAIL: recall_at_k {summary['recall_at_k']:.2f} below required {args.min_recall:.2f}")
        raise SystemExit(1)
