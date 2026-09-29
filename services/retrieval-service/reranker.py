"""Optional cross-encoder reranking, OFF by default.

A cross-encoder scores (query, chunk) pairs jointly rather than comparing
independently-embedded vectors, which is usually a real quality bump, but
it costs a model load and a forward pass per candidate. Whether that trade
is worth it on this corpus is an empirical question, not an assumption:
eval/ablation.py measures it with the reranker on vs. off and the report
says which won. Wire this in by default only if that measurement supports
it (see docs/evaluation.md).
"""
from __future__ import annotations

import os

_MODEL_NAME = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder

        _model = CrossEncoder(_MODEL_NAME)
    return _model


def rerank(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Re-scores `chunks` against `query` with a cross-encoder and returns
    the top_k, replacing `fusion_score` with the reranker's score."""
    if not chunks:
        return []
    model = _get_model()
    pairs = [(query, c["text"]) for c in chunks]
    scores = model.predict(pairs)
    reranked = [{**c, "fusion_score": float(s)} for c, s in zip(chunks, scores)]
    reranked.sort(key=lambda c: c["fusion_score"], reverse=True)
    return reranked[:top_k]
