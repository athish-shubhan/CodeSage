"""gRPC client for the retrieval-service (the RAG lookup + ingest boundary)."""
from __future__ import annotations

import grpc

import retrieval_pb2
import retrieval_pb2_grpc
from app.config import settings


def _channel() -> grpc.aio.Channel:
    return grpc.aio.insecure_channel(settings.retrieval_grpc_target)


async def search(
    query: str,
    top_k: int | None = None,
    collection: str | None = None,
    use_reranker: bool = False,
    strategy: str = "dense",  # see docs/evaluation.md: hybrid fusion measured no better than dense-only on this corpus
) -> list[dict]:
    async with _channel() as channel:
        stub = retrieval_pb2_grpc.RetrievalStub(channel)
        request = retrieval_pb2.SearchRequest(
            query=query,
            top_k=top_k or settings.top_k,
            collection=collection or settings.default_collection,
            use_reranker=use_reranker,
            strategy=strategy,
        )
        response = await stub.Search(request, timeout=10)
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
    async with _channel() as channel:
        stub = retrieval_pb2_grpc.RetrievalStub(channel)
        request = retrieval_pb2.ExpandContextRequest(
            collection=collection or settings.default_collection,
            source_path=source_path,
            start_line=start_line,
            end_line=end_line,
            extra_lines=extra_lines,
        )
        response = await stub.ExpandContext(request, timeout=10)
        return response.text if response.found else None


async def get_file(source_path: str, max_bytes: int = 20_000, collection: str | None = None) -> dict | None:
    async with _channel() as channel:
        stub = retrieval_pb2_grpc.RetrievalStub(channel)
        request = retrieval_pb2.GetFileRequest(
            collection=collection or settings.default_collection, source_path=source_path, max_bytes=max_bytes
        )
        response = await stub.GetFile(request, timeout=10)
        if not response.found:
            return None
        return {"text": response.text, "truncated": response.truncated}


async def ingest_repo(repo_path: str, collection: str | None = None, include_globs: list[str] | None = None) -> dict:
    async with _channel() as channel:
        stub = retrieval_pb2_grpc.RetrievalStub(channel)
        request = retrieval_pb2.IngestRequest(
            repo_path=repo_path,
            collection=collection or settings.default_collection,
            include_globs=include_globs or [],
        )
        response = await stub.IngestRepo(request, timeout=600)
        return {"files_indexed": response.files_indexed, "chunks_indexed": response.chunks_indexed}


async def health() -> dict:
    async with _channel() as channel:
        stub = retrieval_pb2_grpc.RetrievalStub(channel)
        try:
            response = await stub.Health(retrieval_pb2.HealthRequest(), timeout=3)
            return {"ok": response.ok, "vector_store_status": response.vector_store_status}
        except grpc.aio.AioRpcError as exc:
            return {"ok": False, "vector_store_status": str(exc)}
