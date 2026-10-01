"""Lexical (BM25) search, in-memory, one index per collection.

Dense embeddings under-rank exact identifiers (env var names, exception
classes, config keys) because a bi-encoder compresses "GATEWAY_LLM_BASE_URL"
into the same semantic neighbourhood as any other config-sounding text. BM25
matches the literal tokens, which is exactly what an exact-identifier query
needs. Kept in-process (no new service/infra): the corpus is small enough
that an in-memory numpy index rebuilt on each ingest is simpler and faster
than standing up a real search engine. Not durable on its own: after a
restart pipeline.restore() rebuilds it from the chunk payloads in Qdrant.
"""
from __future__ import annotations

import bm25s

_indexes: dict[str, tuple[bm25s.BM25, list[dict]]] = {}


def build_index(collection: str, chunks: list[dict]) -> None:
    """chunks: list of {text, source_path, start_line, end_line}."""
    if not chunks:
        _indexes.pop(collection, None)
        return
    tokens = bm25s.tokenize([c["text"] for c in chunks], stopwords="en", show_progress=False)
    retriever = bm25s.BM25()
    retriever.index(tokens, show_progress=False)
    _indexes[collection] = (retriever, chunks)


def has_index(collection: str) -> bool:
    return collection in _indexes


def search(collection: str, query: str, top_k: int) -> list[dict]:
    if collection not in _indexes:
        return []
    retriever, chunks = _indexes[collection]
    k = min(top_k, len(chunks))
    if k == 0:
        return []
    query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
    results, scores = retriever.retrieve(query_tokens, k=k, corpus=chunks, show_progress=False)
    return [{**hit, "bm25_score": float(score)} for hit, score in zip(results[0], scores[0])]
