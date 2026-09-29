"""gRPC retrieval service: embeds + indexes a repo, serves hybrid
(dense + lexical) search with fusion, optional reranking, and
token-budgeted context assembly.

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
import bm25_index
import context_expand
from chunking import chunk_repo
from embeddings import embed, embedding_dim
from fusion import assemble_context, dedupe_overlapping, reciprocal_rank_fusion
from query_classifier import lexical_weight
from tracing import Trace
import vector_store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("retrieval-service")

GRPC_PORT = int(os.environ.get("GRPC_PORT", "50051"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9101"))
DEFAULT_COLLECTION = os.environ.get("DEFAULT_COLLECTION", "codebase")
DEFAULT_MAX_CONTEXT_TOKENS = int(os.environ.get("DEFAULT_MAX_CONTEXT_TOKENS", "3000"))
CANDIDATE_K = 20  # each of dense/lexical fetches this many before fusion narrows it down

SEARCH_REQUESTS = Counter("retrieval_search_requests_total", "Total Search RPCs")
SEARCH_LATENCY = Histogram("retrieval_search_latency_seconds", "Search RPC latency")
INGEST_REQUESTS = Counter("retrieval_ingest_requests_total", "Total IngestRepo RPCs")
RERANK_REQUESTS = Counter("retrieval_rerank_requests_total", "Search RPCs that used the reranker")


class RetrievalServicer(retrieval_pb2_grpc.RetrievalServicer):
    def Search(self, request, context):
        SEARCH_REQUESTS.inc()
        collection = request.collection or DEFAULT_COLLECTION
        top_k = request.top_k or 5
        max_tokens = request.max_context_tokens or DEFAULT_MAX_CONTEXT_TOKENS
        trace = Trace()

        with SEARCH_LATENCY.time():
            with trace.step("classify") as meta:
                lex_weight = lexical_weight(request.query)
                meta["lexical_weight"] = round(lex_weight, 3)

            # Default is dense-only, not hybrid: eval/ablation.py measured hybrid
            # fusion tying dense-only on Recall@5 and losing on MRR on this corpus
            # (see docs/evaluation.md). Hybrid and reranking stay available via
            # `strategy`/`use_reranker` for corpora where they measure better.
            strategy = request.strategy or "dense"

            with trace.step("dense_search") as meta:
                dense_hits = []
                if strategy in ("hybrid", "dense"):
                    [query_vec] = embed([request.query])
                    dense_hits = vector_store.search(collection, query_vec, CANDIDATE_K)
                meta["hits"] = len(dense_hits)

            with trace.step("lexical_search") as meta:
                lexical_hits = []
                if strategy in ("hybrid", "lexical"):
                    lexical_hits = bm25_index.search(collection, request.query, CANDIDATE_K)
                meta["hits"] = len(lexical_hits)

            with trace.step("fuse_dedupe"):
                fused = reciprocal_rank_fusion(dense_hits, lexical_hits, lex_weight)
                fused = dedupe_overlapping(fused)

            if request.use_reranker:
                RERANK_REQUESTS.inc()
                with trace.step("rerank") as meta:
                    from reranker import rerank

                    fused = rerank(request.query, fused[: CANDIDATE_K * 2], top_k)
                    meta["candidates"] = len(fused)

            with trace.step("assemble") as meta:
                selected, tokens_used = assemble_context(fused[: max(top_k, CANDIDATE_K)], max_tokens)
                selected = selected[:top_k]
                meta["chunks"] = len(selected)
                meta["tokens"] = tokens_used

        chunks = [
            retrieval_pb2.Chunk(
                text=h["text"],
                source_path=h["source_path"],
                start_line=h["start_line"],
                end_line=h["end_line"],
                score=h.get("fusion_score", 0.0),
            )
            for h in selected
        ]
        trace_spans = [
            retrieval_pb2.TraceSpan(stage=s["stage"], ms=s["ms"], meta_json=json.dumps(s["meta"]))
            for s in trace.as_dict()
        ]
        return retrieval_pb2.SearchResponse(
            chunks=chunks, context_tokens=tokens_used, lexical_weight=lex_weight, trace=trace_spans
        )

    def IngestRepo(self, request, context):
        INGEST_REQUESTS.inc()
        collection = request.collection or DEFAULT_COLLECTION
        globs = list(request.include_globs) or None
        raw_chunks, files_seen = chunk_repo(request.repo_path, globs)
        if not raw_chunks:
            return retrieval_pb2.IngestResponse(files_indexed=files_seen, chunks_indexed=0)

        vector_store.ensure_collection(collection, embedding_dim())
        texts = [c.text for c in raw_chunks]
        vectors = embed(texts)
        payloads = [
            {"text": c.text, "source_path": c.source_path, "start_line": c.start_line, "end_line": c.end_line}
            for c in raw_chunks
        ]
        vector_store.upsert(collection, vectors, payloads)
        bm25_index.build_index(collection, payloads)
        context_expand.set_repo_root(collection, request.repo_path)
        log.info("Indexed %d chunks from %d files into %s", len(raw_chunks), files_seen, collection)
        return retrieval_pb2.IngestResponse(files_indexed=files_seen, chunks_indexed=len(raw_chunks))

    def ExpandContext(self, request, context):
        text = context_expand.expand(
            request.collection,
            request.source_path,
            request.start_line,
            request.end_line,
            request.extra_lines or 20,
        )
        return retrieval_pb2.ExpandContextResponse(text=text or "", found=text is not None)

    def GetFile(self, request, context):
        result = context_expand.read_file(request.collection, request.source_path, request.max_bytes or 20_000)
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
