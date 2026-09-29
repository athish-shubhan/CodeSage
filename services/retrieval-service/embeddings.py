"""Wraps the sentence-transformers model used to embed code/doc chunks.

Kept as its own module so the model (and quantized/GPU variant) can be
swapped without touching the gRPC server or the vector store code.
"""
from __future__ import annotations

import os

from sentence_transformers import SentenceTransformer

_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
_DEVICE = os.environ.get("EMBEDDING_DEVICE", "cpu")  # set to "cuda" on a GPU edge node

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME, device=_DEVICE)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embedding_dim() -> int:
    return get_model().get_sentence_embedding_dimension()
