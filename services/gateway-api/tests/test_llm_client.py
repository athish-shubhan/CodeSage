import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm_client import build_prompt  # noqa: E402


def test_build_prompt_includes_citations_for_each_chunk():
    chunks = [
        {"source_path": "app/main.py", "start_line": 10, "end_line": 20, "text": "def foo(): ..."},
        {"source_path": "app/auth.py", "start_line": 1, "end_line": 5, "text": "import jwt"},
    ]

    prompt = build_prompt("How does auth work?", chunks)

    assert "app/main.py:10-20" in prompt
    assert "app/auth.py:1-5" in prompt
    assert "How does auth work?" in prompt


def test_build_prompt_handles_no_context_gracefully():
    prompt = build_prompt("What is this?", [])

    assert "no matching context found" in prompt
    assert "What is this?" in prompt


def _sse_client(lines):
    """httpx.AsyncClient whose transport answers every request with these SSE lines."""
    import httpx

    body = "".join(f"{line}\n\n" for line in lines).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    real = httpx.AsyncClient
    return lambda **kw: real(transport=transport, **kw)


def test_stream_chat_skips_chunks_with_no_choices():
    import asyncio
    import json
    from unittest.mock import patch

    from app import llm_client

    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Hel"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "lo"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}),
        "data: [DONE]",
    ]

    async def collect():
        return [t async for t in llm_client.stream_chat("hi")]

    with patch("app.llm_client.httpx.AsyncClient", new=_sse_client(lines)):
        assert asyncio.run(collect()) == ["Hel", "lo"]


def _client_returning(body, status=200):
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    real = httpx.AsyncClient
    return lambda **kw: real(transport=transport, **kw)


import pytest  # noqa: E402


@pytest.mark.parametrize("body", [b'{"choices": []}', b'{"error": "model not loaded"}', b"<html>bad gateway</html>", b"[1]"])
def test_agent_maps_a_malformed_completion_to_502(body):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.auth import create_access_token
    from app.main import app

    with patch("app.llm_client.httpx.AsyncClient", new=_client_returning(body)):
        resp = TestClient(app, raise_server_exceptions=False).post(
            "/agent", headers={"Authorization": f"Bearer {create_access_token('admin')}"}, json={"task": "hi"}
        )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "LLM backend unavailable (malformed response)"


@pytest.mark.parametrize("line", ["data: <html>oops</html>", 'data: {"error": {"message": "context length exceeded"}}'])
def test_chat_maps_a_malformed_stream_chunk_to_502(line):
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app.auth import create_access_token
    from app.main import app

    with patch("app.llm_client.httpx.AsyncClient", new=_sse_client([line])), patch(
        "app.routers.chat.rag_client.search", new=AsyncMock(return_value=[])
    ):
        resp = TestClient(app, raise_server_exceptions=False).post(
            "/chat", headers={"Authorization": f"Bearer {create_access_token('admin')}"}, json={"question": "hi"}
        )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "LLM backend unavailable (malformed response)"
