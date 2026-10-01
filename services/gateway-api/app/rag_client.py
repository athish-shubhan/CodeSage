"""gRPC client for the retrieval-service (the RAG lookup + ingest boundary).

One channel is shared by every request instead of opening a new one per
call: a gRPC channel owns the TCP/HTTP2 connection, and building one per
call paid a connection setup on every search (scripts/bench_grpc_channel.py
measures the difference). grpc.aio channels are bound to the event loop
that created them, so the cache is keyed on the running loop.
"""
from __future__ import annotations

import asyncio
import json

import grpc

import retrieval_pb2
import retrieval_pb2_grpc
from app.config import settings

# Retry only UNAVAILABLE (connection refused/reset, server restarting), with
# backoff. Safe for every RPC here because all of them are idempotent,
# including IngestRepo, which skips unchanged files and uses deterministic
# point IDs. DEADLINE_EXCEEDED is deliberately not retried: a slow backend
# would just be hit again with the same slow request.
_SERVICE_CONFIG = json.dumps(
    {
        "methodConfig": [
            {
                "name": [{"service": "retrieval.Retrieval"}],
                "retryPolicy": {
                    "maxAttempts": 3,
                    "initialBackoff": "0.2s",
                    "maxBackoff": "2s",
                    "backoffMultiplier": 2,
                    "retryableStatusCodes": ["UNAVAILABLE"],
                },
            }
        ]
    }
)
_CHANNEL_OPTIONS = [
    ("grpc.enable_retries", 1),
    ("grpc.service_config", _SERVICE_CONFIG),
    ("grpc.keepalive_time_ms", 30_000),
    ("grpc.keepalive_timeout_ms", 10_000),
]

_channel: grpc.aio.Channel | None = None
_channel_loop: asyncio.AbstractEventLoop | None = None


def _stub() -> retrieval_pb2_grpc.RetrievalStub:
    global _channel, _channel_loop
    loop = asyncio.get_running_loop()
    if _channel is None or _channel_loop is not loop:
        _channel = grpc.aio.insecure_channel(settings.retrieval_grpc_target, options=_CHANNEL_OPTIONS)
        _channel_loop = loop
    return retrieval_pb2_grpc.RetrievalStub(_channel)


async def close() -> None:
    global _channel, _channel_loop
    if _channel is not None:
        await _channel.close()
    _channel, _channel_loop = None, None


async def search(
    query: str,
    top_k: int | None = None,
    collection: str | None = None,
    use_reranker: bool = False,
    strategy: str = "dense",  # see docs/evaluation.md: hybrid fusion measured no better than dense-only on this corpus
) -> list[dict]:
    request = retrieval_pb2.SearchRequest(
        query=query,
        top_k=top_k or settings.top_k,
        collection=collection or settings.default_collection,
        use_reranker=use_reranker,
        strategy=strategy,
    )
    response = await _stub().Search(request, timeout=10)
    return [
        {
            "text": c.text,
            "source_path": c.source_path,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "score": c.score,
        }
        for c in response.chunks
    ]


async def expand_context(
    source_path: str, start_line: int, end_line: int, extra_lines: int = 20, collection: str | None = None
) -> str | None:
    request = retrieval_pb2.ExpandContextRequest(
        collection=collection or settings.default_collection,
        source_path=source_path,
        start_line=start_line,
        end_line=end_line,
        extra_lines=extra_lines,
    )
    response = await _stub().ExpandContext(request, timeout=10)
    return response.text if response.found else None


async def get_file(source_path: str, max_bytes: int = 20_000, collection: str | None = None) -> dict | None:
    request = retrieval_pb2.GetFileRequest(
        collection=collection or settings.default_collection, source_path=source_path, max_bytes=max_bytes
    )
    response = await _stub().GetFile(request, timeout=10)
    if not response.found:
        return None
    return {"text": response.text, "truncated": response.truncated}


async def ingest_repo(repo_path: str, collection: str | None = None, include_globs: list[str] | None = None) -> dict:
    request = retrieval_pb2.IngestRequest(
        repo_path=repo_path,
        collection=collection or settings.default_collection,
        include_globs=include_globs or [],
    )
    response = await _stub().IngestRepo(request, timeout=600)
    return {
        "files_indexed": response.files_indexed,
        "chunks_indexed": response.chunks_indexed,
        "files_changed": response.files_changed,
        "files_removed": response.files_removed,
        "chunks_embedded": response.chunks_embedded,
    }


async def health() -> dict:
    try:
        response = await _stub().Health(retrieval_pb2.HealthRequest(), timeout=3)
        return {"ok": response.ok, "vector_store_status": response.vector_store_status}
    except grpc.aio.AioRpcError as exc:
        return {"ok": False, "vector_store_status": str(exc)}
