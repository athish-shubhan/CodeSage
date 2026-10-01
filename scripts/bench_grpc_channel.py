"""Per-call latency of gateway -> retrieval-service gRPC calls: a new channel
per call (what rag_client used to do) vs. one shared channel (what it does
now). Starts the real retrieval-service servicer in-process against an
embedded Qdrant and calls the Health RPC, so the number isolates transport
overhead rather than search work.

    python -m grpc_tools.protoc -I services/retrieval-service/proto \
        --python_out=services/retrieval-service --grpc_python_out=services/retrieval-service \
        services/retrieval-service/proto/retrieval.proto
    python scripts/bench_grpc_channel.py --calls 1000
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from concurrent import futures
from pathlib import Path

os.environ.setdefault("QDRANT_URL", ":memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "retrieval-service"))

import grpc  # noqa: E402

import retrieval_pb2  # noqa: E402
import retrieval_pb2_grpc  # noqa: E402
from server import RetrievalServicer  # noqa: E402


def start_server() -> tuple[grpc.Server, str]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    retrieval_pb2_grpc.add_RetrievalServicer_to_server(RetrievalServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, f"127.0.0.1:{port}"


async def per_call_channel(target: str, n: int) -> list[float]:
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        async with grpc.aio.insecure_channel(target) as channel:
            await retrieval_pb2_grpc.RetrievalStub(channel).Health(retrieval_pb2.HealthRequest(), timeout=5)
        samples.append((time.perf_counter() - start) * 1000)
    return samples


async def shared_channel(target: str, n: int) -> list[float]:
    samples = []
    async with grpc.aio.insecure_channel(target) as channel:
        stub = retrieval_pb2_grpc.RetrievalStub(channel)
        await stub.Health(retrieval_pb2.HealthRequest(), timeout=5)  # connect outside the timed loop
        for _ in range(n):
            start = time.perf_counter()
            await stub.Health(retrieval_pb2.HealthRequest(), timeout=5)
            samples.append((time.perf_counter() - start) * 1000)
    return samples


def summarize(name: str, samples: list[float]) -> str:
    q = statistics.quantiles(samples, n=100)
    return f"| {name} | {len(samples)} | {statistics.median(samples):.3f} | {q[94]:.3f} | {q[98]:.3f} | {statistics.mean(samples):.3f} |"


async def main(calls: int) -> None:
    server, target = start_server()
    try:
        await shared_channel(target, 50)  # warm up server threads and the embedded store
        results = {
            "new channel per call": await per_call_channel(target, calls),
            "shared channel": await shared_channel(target, calls),
        }
    finally:
        server.stop(None)
    print("| Pattern | Calls | p50 ms | p95 ms | p99 ms | mean ms |")
    print("|---|---|---|---|---|---|")
    for name, samples in results.items():
        print(summarize(name, samples))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=1000)
    asyncio.run(main(parser.parse_args().calls))
