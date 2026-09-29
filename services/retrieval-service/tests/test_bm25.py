import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bm25_index  # noqa: E402

CHUNKS = [
    {"text": "def authenticate(username, password): return username == 'admin'", "source_path": "auth.py"},
    {"text": "GATEWAY_JWT_SECRET is read from the environment at startup", "source_path": "config.py"},
    {"text": "the quick brown fox jumps over the lazy dog", "source_path": "unrelated.md"},
]


def test_exact_identifier_query_ranks_matching_chunk_first():
    bm25_index.build_index("t1", CHUNKS)

    hits = bm25_index.search("t1", "GATEWAY_JWT_SECRET", top_k=3)

    assert hits[0]["source_path"] == "config.py"
    assert hits[0]["bm25_score"] > 0


def test_search_on_unknown_collection_returns_empty():
    assert bm25_index.search("nonexistent", "query", top_k=5) == []


def test_build_index_with_empty_chunks_clears_collection():
    bm25_index.build_index("t2", CHUNKS)
    assert bm25_index.search("t2", "authenticate", top_k=3) != []

    bm25_index.build_index("t2", [])
    assert bm25_index.search("t2", "authenticate", top_k=3) == []
