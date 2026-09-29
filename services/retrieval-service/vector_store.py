"""Thin wrapper around Qdrant for upsert + nearest-neighbour search."""
from __future__ import annotations

import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def ensure_collection(name: str, dim: int) -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        )


def upsert(collection: str, vectors: list[list[float]], payloads: list[dict]) -> None:
    client = get_client()
    points = [
        qmodels.PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload)
        for vec, payload in zip(vectors, payloads)
    ]
    client.upsert(collection_name=collection, points=points)


def search(collection: str, query_vector: list[float], top_k: int) -> list[dict]:
    client = get_client()
    try:
        hits = client.search(collection_name=collection, query_vector=query_vector, limit=top_k)
    except UnexpectedResponse as exc:
        if exc.status_code == 404:
            # Nothing has been ingested into this collection yet, so treat
            # it as "no matches" rather than an error (the common first-run case).
            return []
        raise
    return [{**hit.payload, "score": hit.score} for hit in hits]


def health() -> str:
    try:
        get_client().get_collections()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - surfaced to caller as a status string
        return f"unreachable: {exc}"
