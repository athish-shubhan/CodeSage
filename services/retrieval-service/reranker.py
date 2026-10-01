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


BATCH_SIZE = 8


def rerank(query: str, chunks: list[dict], top_k: int, is_active=lambda: True) -> list[dict]:
    """Re-scores `chunks` against `query` with a cross-encoder and returns
    the top_k, replacing `fusion_score` with the reranker's score. Scores in
    small batches and checks is_active between them, so an abandoned request
    stops within one batch instead of finishing the whole candidate pool."""
    if not chunks:
        return []
    from pipeline import Cancelled

    model = _get_model()
    pairs = [(query, c["text"]) for c in chunks]
    scores = []
    for i in range(0, len(pairs), BATCH_SIZE):
        if not is_active():
            raise Cancelled()
        scores.extend(model.predict(pairs[i : i + BATCH_SIZE], show_progress_bar=False))
    reranked = [{**c, "fusion_score": float(s)} for c, s in zip(chunks, scores)]
    reranked.sort(key=lambda c: c["fusion_score"], reverse=True)
    return reranked[:top_k]
