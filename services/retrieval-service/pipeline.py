"""Search and ingest logic, independent of gRPC. server.py is a thin
transport over these two functions, which keeps them testable against an
embedded Qdrant with no network and no generated stubs.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

import bm25_index
import context_expand
import vector_store
from chunking import chunk_file, iter_source_files
from embeddings import embed, embedding_dim
from fusion import assemble_context, dedupe_overlapping, reciprocal_rank_fusion
from query_classifier import lexical_weight
from tracing import Trace

log = logging.getLogger("retrieval-service")

CANDIDATE_K = 20  # each of dense/lexical fetches this many before fusion narrows it down
RERANK_CANDIDATES = CANDIDATE_K * 2


class Cancelled(Exception):
    """The caller went away (deadline passed or client disconnected)."""


def _always_active() -> bool:
    return True


@dataclass
class IngestResult:
    files_seen: int
    files_changed: int
    files_removed: int
    chunks_embedded: int
    chunks_total: int


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def ingest(collection: str, repo_path: str, include_globs: list[str] | None = None) -> IngestResult:
    """Incremental, idempotent ingest. Only files whose content hash changed
    since the last ingest are re-chunked and re-embedded; files that
    disappeared from the repo have their chunks deleted. Embedding is the
    expensive step, so an unchanged re-ingest does no embedding at all."""
    current = {rel: (full, _sha256(full)) for full, rel in iter_source_files(repo_path, include_globs)}

    existing = vector_store.all_payloads(collection)
    indexed_hash = {p["source_path"]: p.get("file_hash") for p in existing}

    changed = [rel for rel, (_, digest) in current.items() if indexed_hash.get(rel) != digest]
    # With include_globs, files outside the globs weren't scanned, so only a
    # full ingest can conclude that an indexed file was deleted.
    removed = [] if include_globs else sorted(set(indexed_hash) - set(current))

    vector_store.delete_files(collection, [p for p in changed + removed if p in indexed_hash])

    payloads = []
    for rel in changed:
        full, digest = current[rel]
        for c in chunk_file(full, rel):
            payloads.append(
                {
                    "text": c.text,
                    "source_path": c.source_path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "file_hash": digest,
                    "repo_root": repo_path,
                }
            )

    if payloads:
        vector_store.ensure_collection(collection, embedding_dim())
        vector_store.upsert(collection, embed([p["text"] for p in payloads]), payloads)

    # The lexical index is cheap to rebuild whole and must reflect deletes too.
    all_chunks = vector_store.all_payloads(collection)
    bm25_index.build_index(collection, all_chunks)
    context_expand.set_repo_root(collection, repo_path)

    result = IngestResult(
        files_seen=len(current),
        # Empty files yield no chunks, so they never get a stored hash and look
        # "new" on every ingest; count only files whose index entries changed.
        files_changed=len({p["source_path"] for p in payloads} | {p for p in changed if p in indexed_hash}),
        files_removed=len(removed),
        chunks_embedded=len(payloads),
        chunks_total=len(all_chunks),
    )
    log.info("ingest %s: %s", collection, result)
    return result


def restore(collection: str) -> None:
    """Rebuilds the in-memory BM25 index and repo root for a collection from
    Qdrant payloads. Needed after a restart: Qdrant persists, these don't,
    and without this lexical search silently returns nothing and
    expand_context/get_file fail until someone re-ingests."""
    if bm25_index.has_index(collection):
        return
    payloads = vector_store.all_payloads(collection)
    if not payloads:
        return
    bm25_index.build_index(collection, payloads)
    if root := payloads[0].get("repo_root"):
        context_expand.set_repo_root(collection, root)
    log.info("restored lexical index for %s (%d chunks)", collection, len(payloads))


def search(
    collection: str,
    query: str,
    top_k: int = 5,
    max_tokens: int = 3000,
    strategy: str = "dense",
    use_reranker: bool = False,
    min_score: float = 0.0,
    is_active: Callable[[], bool] = _always_active,
) -> dict:
    """Returns {chunks, context_tokens, lexical_weight, top_dense_score,
    abstained, trace}.

    min_score > 0 makes the search abstain, returning no chunks, when the best
    dense cosine similarity is below it: the question most likely has no
    answer in this corpus, and "closest available" chunks would only invite
    the model to answer from unrelated code. See docs/evaluation.md for how
    the threshold was measured.

    is_active is checked before each expensive stage (embedding, reranking).
    The gRPC server passes context.is_active, so a request whose client
    deadline has already passed stops instead of finishing work nobody will
    read; without this, abandoned reranks kept the CPU busy and made every
    later request miss its deadline too.

    Default strategy is dense-only, not hybrid: eval/ablation.py measured
    hybrid fusion tying dense on Recall@5 and losing on MRR on this corpus
    (docs/evaluation.md). Hybrid and reranking stay selectable for corpora
    where they measure better."""
    trace = Trace()
    restore(collection)

    with trace.step("classify") as meta:
        lex_weight = lexical_weight(query)
        meta["lexical_weight"] = round(lex_weight, 3)

    with trace.step("dense_search") as meta:
        dense_hits = []
        if strategy in ("hybrid", "dense"):
            if not is_active():
                raise Cancelled()
            [query_vec] = embed([query])
            dense_hits = vector_store.search(collection, query_vec, CANDIDATE_K)
        meta["hits"] = len(dense_hits)
    top_dense_score = dense_hits[0]["score"] if dense_hits else 0.0

    if min_score > 0 and strategy != "lexical" and top_dense_score < min_score:
        return {
            "chunks": [],
            "context_tokens": 0,
            "lexical_weight": lex_weight,
            "top_dense_score": top_dense_score,
            "abstained": True,
            "trace": trace.as_dict(),
        }

    with trace.step("lexical_search") as meta:
        lexical_hits = []
        if strategy in ("hybrid", "lexical"):
            lexical_hits = bm25_index.search(collection, query, CANDIDATE_K)
        meta["hits"] = len(lexical_hits)

    with trace.step("fuse_dedupe"):
        fused = dedupe_overlapping(reciprocal_rank_fusion(dense_hits, lexical_hits, lex_weight))

    if use_reranker:
        with trace.step("rerank") as meta:
            from reranker import rerank

            fused = rerank(query, fused[:RERANK_CANDIDATES], top_k, is_active)
            meta["candidates"] = len(fused)

    with trace.step("assemble") as meta:
        selected, tokens_used = assemble_context(fused, max_tokens, max_chunks=top_k)
        meta["chunks"] = len(selected)
        meta["tokens"] = tokens_used

    return {
        "chunks": selected,
        "context_tokens": tokens_used,
        "lexical_weight": lex_weight,
        "top_dense_score": top_dense_score,
        "abstained": False,
        "trace": trace.as_dict(),
    }
