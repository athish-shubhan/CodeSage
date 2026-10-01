"""Thin wrapper around Qdrant for upsert, nearest-neighbour search, and the
per-file bookkeeping incremental ingestion needs.

Qdrant is the only durable store in the retrieval-service: the BM25 index
and the repo-root mapping are both rebuilt from the payloads stored here
(see pipeline.py), so a restart loses nothing that matters.
"""
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
        # ":memory:" runs Qdrant embedded in-process; used by tests and offline eval.
        _client = QdrantClient(location=":memory:") if QDRANT_URL == ":memory:" else QdrantClient(url=QDRANT_URL)
    return _client


def point_id(collection: str, payload: dict) -> str:
    """Deterministic ID from (collection, file, line range, file content hash).
    Re-ingesting identical content overwrites the same points instead of
    adding duplicates, which random UUIDs did."""
    key = f"{collection}|{payload['source_path']}|{payload['start_line']}|{payload['end_line']}|{payload['file_hash']}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def ensure_collection(name: str, dim: int) -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        )


def upsert(collection: str, vectors: list[list[float]], payloads: list[dict]) -> None:
    points = [
        qmodels.PointStruct(id=point_id(collection, payload), vector=vec, payload=payload)
        for vec, payload in zip(vectors, payloads)
    ]
    get_client().upsert(collection_name=collection, points=points)


def delete_files(collection: str, source_paths: list[str]) -> None:
    if not source_paths:
        return
    selector = qmodels.FilterSelector(
        filter=qmodels.Filter(must=[qmodels.FieldCondition(key="source_path", match=qmodels.MatchAny(any=source_paths))])
    )
    get_client().delete(collection_name=collection, points_selector=selector)


def all_payloads(collection: str) -> list[dict]:
    """Every chunk payload in the collection, or [] if it doesn't exist."""
    client = get_client()
    payloads: list[dict] = []
    offset = None
    try:
        while True:
            points, offset = client.scroll(
                collection_name=collection, limit=512, offset=offset, with_payload=True, with_vectors=False
            )
            payloads.extend(p.payload for p in points)
            if offset is None:
                return payloads
    except (UnexpectedResponse, ValueError) as exc:
        # Remote Qdrant raises UnexpectedResponse(404), embedded mode ValueError.
        if isinstance(exc, UnexpectedResponse) and exc.status_code != 404:
            raise
        return []


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
    except ValueError:
        return []  # embedded mode's equivalent of the 404 above
    return [{**hit.payload, "score": hit.score} for hit in hits]


def health() -> str:
    try:
        get_client().get_collections()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - surfaced to caller as a status string
        return f"unreachable: {exc}"
