"""gRPC transport for the retrieval pipeline (pipeline.py): request
parsing, metrics, and proto conversion only.

This is the "edge-friendly" half of the RAG pipeline: it can run on a GPU box
close to the data while the gateway-api stays on a cheap cloud VM, talking to
this service over gRPC.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent import futures

import grpc
from prometheus_client import start_http_server, Counter, Histogram

import retrieval_pb2
import retrieval_pb2_grpc
import context_expand
import pipeline
import vector_store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("retrieval-service")

GRPC_PORT = int(os.environ.get("GRPC_PORT", "50051"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9101"))
DEFAULT_COLLECTION = os.environ.get("DEFAULT_COLLECTION", "codebase")
DEFAULT_MAX_CONTEXT_TOKENS = int(os.environ.get("DEFAULT_MAX_CONTEXT_TOKENS", "3000"))

SEARCH_REQUESTS = Counter("retrieval_search_requests_total", "Total Search RPCs")
SEARCH_LATENCY = Histogram("retrieval_search_latency_seconds", "Search RPC latency")
INGEST_REQUESTS = Counter("retrieval_ingest_requests_total", "Total IngestRepo RPCs")
CHUNKS_EMBEDDED = Counter("retrieval_ingest_chunks_embedded_total", "Chunks embedded by IngestRepo")
RERANK_REQUESTS = Counter("retrieval_rerank_requests_total", "Search RPCs that used the reranker")


class RetrievalServicer(retrieval_pb2_grpc.RetrievalServicer):
    def Search(self, request, context):
        SEARCH_REQUESTS.inc()
        if request.use_reranker:
            RERANK_REQUESTS.inc()
        with SEARCH_LATENCY.time():
            result = pipeline.search(
                collection=request.collection or DEFAULT_COLLECTION,
                query=request.query,
                top_k=request.top_k or 5,
                max_tokens=request.max_context_tokens or DEFAULT_MAX_CONTEXT_TOKENS,
                strategy=request.strategy or "dense",
                use_reranker=request.use_reranker,
            )

        chunks = [
            retrieval_pb2.Chunk(
                text=h["text"],
                source_path=h["source_path"],
                start_line=h["start_line"],
                end_line=h["end_line"],
                score=h.get("fusion_score", 0.0),
            )
            for h in result["chunks"]
        ]
        trace_spans = [
            retrieval_pb2.TraceSpan(stage=s["stage"], ms=s["ms"], meta_json=json.dumps(s["meta"]))
            for s in result["trace"]
        ]
        return retrieval_pb2.SearchResponse(
            chunks=chunks,
            context_tokens=result["context_tokens"],
            lexical_weight=result["lexical_weight"],
            trace=trace_spans,
        )

    def IngestRepo(self, request, context):
        INGEST_REQUESTS.inc()
        result = pipeline.ingest(
            request.collection or DEFAULT_COLLECTION, request.repo_path, list(request.include_globs) or None
        )
        CHUNKS_EMBEDDED.inc(result.chunks_embedded)
        return retrieval_pb2.IngestResponse(
            files_indexed=result.files_seen,
            chunks_indexed=result.chunks_total,
            files_changed=result.files_changed,
            files_removed=result.files_removed,
            chunks_embedded=result.chunks_embedded,
        )

    def ExpandContext(self, request, context):
        collection = request.collection or DEFAULT_COLLECTION
        pipeline.restore(collection)
        text = context_expand.expand(
            collection,
            request.source_path,
            request.start_line,
            request.end_line,
            request.extra_lines or 20,
        )
        return retrieval_pb2.ExpandContextResponse(text=text or "", found=text is not None)

    def GetFile(self, request, context):
        collection = request.collection or DEFAULT_COLLECTION
        pipeline.restore(collection)
        result = context_expand.read_file(collection, request.source_path, request.max_bytes or 20_000)
        if result is None:
            return retrieval_pb2.GetFileResponse(found=False)
        return retrieval_pb2.GetFileResponse(text=result["text"], found=True, truncated=result["truncated"])

    def Health(self, request, context):
        status = vector_store.health()
        return retrieval_pb2.HealthResponse(ok=status == "ok", vector_store_status=status)


def serve() -> None:
    start_http_server(METRICS_PORT)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    retrieval_pb2_grpc.add_RetrievalServicer_to_server(RetrievalServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    log.info("retrieval-service listening on :%d (metrics on :%d)", GRPC_PORT, METRICS_PORT)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
