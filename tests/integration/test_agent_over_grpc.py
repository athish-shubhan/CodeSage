"""Gateway and retrieval-service together, over real gRPC.

Starts the real retrieval-service servicer on a local port (embedded
Qdrant, stand-in embedder), ingests the fixture repo through the gateway's
own gRPC client, then runs the gateway's agent loop with a scripted LLM.
Only the LLM and the embedding model are fake; every tool call crosses the
real proto contract.

Run from the repo root after generating stubs into both service dirs:
    python -m pytest tests/integration -q
"""
import hashlib
import os
import sys
from concurrent import futures
from pathlib import Path
from unittest.mock import AsyncMock, patch

import grpc
import pytest
import pytest_asyncio

os.environ["QDRANT_URL"] = ":memory:"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "retrieval-service"))
sys.path.insert(0, str(ROOT / "services" / "gateway-api"))

import pipeline  # noqa: E402
import retrieval_pb2_grpc  # noqa: E402
from server import RetrievalServicer  # noqa: E402

from app import rag_client  # noqa: E402
from app.agent.loop import run_agent  # noqa: E402

pytestmark = pytest.mark.asyncio

FIXTURE_REPO = str(ROOT / "eval" / "fixture" / "repo")
DIM = 64


def stand_in_embed(texts):
    vectors = []
    for text in texts:
        v = [0.0] * DIM
        for token in text.lower().replace("_", " ").split():
            v[int(hashlib.md5(token.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        vectors.append([x / norm for x in v])
    return vectors


@pytest.fixture(scope="module")
def retrieval_server():
    pipeline.embed = stand_in_embed
    pipeline.embedding_dim = lambda: DIM
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    retrieval_pb2_grpc.add_RetrievalServicer_to_server(RetrievalServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield f"127.0.0.1:{port}"
    server.stop(None)


@pytest_asyncio.fixture
async def gateway(retrieval_server, monkeypatch):
    await rag_client.close()
    monkeypatch.setattr(rag_client.settings, "retrieval_grpc_target", retrieval_server)
    monkeypatch.setattr(rag_client.settings, "default_collection", "integration")
    yield
    await rag_client.close()


def _call(name, args, call_id):
    return {"id": call_id, "function": {"name": name, "arguments": args}}


async def test_ingest_is_idempotent_over_grpc(gateway):
    first = await rag_client.ingest_repo(FIXTURE_REPO)
    second = await rag_client.ingest_repo(FIXTURE_REPO)
    assert first["chunks_embedded"] == first["chunks_indexed"] > 0
    assert second["chunks_embedded"] == 0
    assert second["chunks_indexed"] == first["chunks_indexed"]


async def test_agent_tools_run_over_grpc_and_citations_are_checked(gateway):
    await rag_client.ingest_repo(FIXTURE_REPO)

    script = [
        {"role": "assistant", "tool_calls": [_call("search_code", '{"query": "WIDGET_API_TOKEN_HEADER", "top_k": 3}', "1")]},
        {"role": "assistant", "tool_calls": [_call("get_file", '{"source_path": "auth.py"}', "2")]},
        {"role": "assistant", "content": "The header is defined in [auth.py:5-5]; see also [billing.py:1-4]."},
    ]
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=script)):
        state = await run_agent("What is WIDGET_API_TOKEN_HEADER?")

    assert state.stopped_reason == "done"
    search, get_file = state.tool_calls
    assert "[auth.py:" in search.result and "WIDGET_API_TOKEN_HEADER" in search.result
    assert get_file.result.startswith('"""Tiny fixture module')
    assert state.citations == {"grounded": ["auth.py:5-5"], "ungrounded": ["billing.py:1-4"]}


async def test_path_traversal_is_refused_over_grpc(gateway):
    await rag_client.ingest_repo(FIXTURE_REPO)
    assert await rag_client.get_file("../../../README.md") is None
