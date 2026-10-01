"""Ingest/search behaviour against a real embedded Qdrant (no server, no
mocks of the vector store). Only the embedding model is replaced, with a
deterministic hashed bag-of-words embedder, so these run without torch."""
import hashlib
import math
import os
import re
import sys
from pathlib import Path

import pytest

os.environ["QDRANT_URL"] = ":memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bm25_index  # noqa: E402
import context_expand  # noqa: E402
import pipeline  # noqa: E402
import vector_store  # noqa: E402

DIM = 64
COLLECTION = "test"


def fake_embed(texts):
    vectors = []
    for text in texts:
        v = [0.0] * DIM
        for token in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(token.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / norm for x in v])
    return vectors


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    vector_store._client = None
    bm25_index._indexes.clear()
    context_expand._repo_roots.clear()
    calls = []

    def counting_embed(texts):
        calls.append(len(texts))
        return fake_embed(texts)

    monkeypatch.setattr(pipeline, "embed", counting_embed)
    monkeypatch.setattr(pipeline, "embedding_dim", lambda: DIM)
    return calls


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "auth.py").write_text("def verify_token(token):\n    return token == 'secret'\n")
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    (tmp_path / "README.md").write_text("# Demo\nA tiny repo for ingestion tests.\n")
    (tmp_path / "__init__.py").write_text("")  # yields no chunks; must not count as changed every time
    return tmp_path


def test_reingesting_unchanged_repo_embeds_nothing_and_adds_no_duplicates(repo, fresh_state):
    first = pipeline.ingest(COLLECTION, str(repo))
    assert first.files_changed == 3 and first.chunks_embedded == first.chunks_total > 0

    second = pipeline.ingest(COLLECTION, str(repo))
    assert second.files_changed == 0
    assert second.chunks_embedded == 0
    assert second.chunks_total == first.chunks_total
    assert vector_store.get_client().count(COLLECTION).count == first.chunks_total
    assert fresh_state == [first.chunks_embedded]  # one embed call total, from the first ingest


def test_modified_file_is_the_only_one_reembedded(repo):
    first = pipeline.ingest(COLLECTION, str(repo))
    (repo / "auth.py").write_text("def verify_token(token):\n    return hmac_compare(token)\n")

    second = pipeline.ingest(COLLECTION, str(repo))
    assert second.files_changed == 1
    assert second.chunks_total == first.chunks_total
    texts = [p["text"] for p in vector_store.all_payloads(COLLECTION) if p["source_path"] == "auth.py"]
    assert texts and all("hmac_compare" in t for t in texts)  # old version's chunks are gone


def test_deleted_file_chunks_are_removed(repo):
    pipeline.ingest(COLLECTION, str(repo))
    (repo / "README.md").unlink()

    result = pipeline.ingest(COLLECTION, str(repo))
    assert result.files_removed == 1
    paths = {p["source_path"] for p in vector_store.all_payloads(COLLECTION)}
    assert "README.md" not in paths
    assert all(h["source_path"] != "README.md" for h in bm25_index.search(COLLECTION, "tiny repo ingestion", 5))


def test_glob_scoped_ingest_does_not_treat_unscanned_files_as_deleted(repo):
    pipeline.ingest(COLLECTION, str(repo))
    result = pipeline.ingest(COLLECTION, str(repo), include_globs=["auth.py"])
    assert result.files_removed == 0
    assert {"auth.py", "math_utils.py", "README.md"} <= {p["source_path"] for p in vector_store.all_payloads(COLLECTION)}


def test_restart_recovers_lexical_index_and_repo_root_from_qdrant(repo):
    pipeline.ingest(COLLECTION, str(repo))
    # Simulate a process restart: in-memory state is lost, Qdrant is not.
    bm25_index._indexes.clear()
    context_expand._repo_roots.clear()

    result = pipeline.search(COLLECTION, "verify_token", top_k=3, strategy="lexical")
    assert result["chunks"] and result["chunks"][0]["source_path"] == "auth.py"
    assert context_expand.read_file(COLLECTION, "auth.py")["text"].startswith("def verify_token")


def test_search_on_missing_collection_returns_empty():
    result = pipeline.search("never_ingested", "anything", strategy="hybrid")
    assert result["chunks"] == [] and result["context_tokens"] == 0


@pytest.mark.parametrize("strategy", ["dense", "lexical", "hybrid"])
def test_search_token_count_matches_returned_chunks(repo, strategy):
    pipeline.ingest(COLLECTION, str(repo))
    result = pipeline.search(COLLECTION, "add two numbers", top_k=1, strategy=strategy)
    assert len(result["chunks"]) == 1
    assert result["context_tokens"] == max(1, len(result["chunks"][0]["text"]) // 4)
    assert [s["stage"] for s in result["trace"]] == ["classify", "dense_search", "lexical_search", "fuse_dedupe", "assemble"]


def test_min_score_abstains_only_when_best_dense_hit_is_below_it(repo):
    pipeline.ingest(COLLECTION, str(repo))
    query = "def add(a, b): return a + b"
    score = pipeline.search(COLLECTION, query)["top_dense_score"]
    assert score > 0

    kept = pipeline.search(COLLECTION, query, min_score=score - 0.01)
    assert kept["chunks"] and not kept["abstained"]

    dropped = pipeline.search(COLLECTION, query, min_score=score + 0.01)
    assert dropped["abstained"] and dropped["chunks"] == [] and dropped["context_tokens"] == 0

    lexical = pipeline.search(COLLECTION, query, strategy="lexical", min_score=0.99)
    assert lexical["chunks"]  # no dense score to judge by, so lexical-only never abstains


def test_generated_files_are_not_indexed(repo):
    (repo / "api_pb2.py").write_text("# Generated by the protocol buffer compiler.  DO NOT EDIT!\nX = 1\n")
    pipeline.ingest(COLLECTION, str(repo))
    assert "api_pb2.py" not in {p["source_path"] for p in vector_store.all_payloads(COLLECTION)}


def test_search_stops_before_embedding_when_caller_is_gone(repo, fresh_state):
    pipeline.ingest(COLLECTION, str(repo))
    embeds_before = len(fresh_state)
    with pytest.raises(pipeline.Cancelled):
        pipeline.search(COLLECTION, "add", is_active=lambda: False)
    assert len(fresh_state) == embeds_before
