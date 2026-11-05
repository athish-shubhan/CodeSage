import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grpc  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _token() -> str:
    resp = client.post("/token", data={"username": "admin", "password": "admin"})
    return resp.json()["access_token"]


def test_chat_returns_503_not_500_when_retrieval_service_unreachable():
    token = _token()
    error = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="retrieval-service down",
    )
    with patch("app.routers.chat.rag_client.search", new=AsyncMock(side_effect=error)):
        resp = client.post("/chat", headers={"Authorization": f"Bearer {token}"}, json={"question": "hi"})

    assert resp.status_code == 503
    assert "retrieval-service" in resp.json()["detail"]


def test_chat_requires_auth():
    resp = client.post("/chat", json={"question": "hi"})
    assert resp.status_code == 401


def test_ingest_refused_by_retrieval_is_a_400_not_an_outage():
    error = grpc.aio.AioRpcError(
        grpc.StatusCode.INVALID_ARGUMENT,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="repo_path is outside INGEST_ALLOWED_ROOTS: '/etc'",
    )
    with patch("app.routers.ingest.rag_client.ingest_repo", new=AsyncMock(side_effect=error)):
        resp = client.post("/ingest", headers={"Authorization": f"Bearer {_token()}"}, json={"repo_path": "/etc"})
    assert resp.status_code == 400
    assert "INGEST_ALLOWED_ROOTS" in resp.json()["detail"]


INTERNAL_RPC = grpc.aio.AioRpcError(
    grpc.StatusCode.UNAVAILABLE,
    initial_metadata=grpc.aio.Metadata(),
    trailing_metadata=grpc.aio.Metadata(),
    details="failed to connect to all addresses; last error: UNKNOWN: ipv4:10.42.7.19:50051: Connection refused",
)


def _llm_500():
    import httpx

    url = "http://ollama.internal.svc:11434/v1/chat/completions"
    req = httpx.Request("POST", url)
    return httpx.HTTPStatusError(f"Server error for url '{url}'", request=req, response=httpx.Response(500, request=req))


def test_errors_name_the_dependency_but_not_its_address(caplog):
    with caplog.at_level("WARNING", logger="gateway-api"), patch(
        "app.routers.chat.rag_client.search", new=AsyncMock(side_effect=INTERNAL_RPC)
    ):
        resp = client.post("/chat", headers={"Authorization": f"Bearer {_token()}"}, json={"question": "hi"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "retrieval-service unavailable (UNAVAILABLE)"
    assert "10.42.7.19" in caplog.text  # the operator still gets it, in the server log


def test_llm_errors_do_not_echo_the_backend_url():
    async def fails(prompt):
        raise _llm_500()
        yield

    with patch("app.routers.chat.rag_client.search", new=AsyncMock(return_value=[])), patch(
        "app.routers.chat.stream_chat", new=fails
    ):
        resp = client.post("/chat", headers={"Authorization": f"Bearer {_token()}"}, json={"question": "hi"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "LLM backend unavailable (HTTP 500)"


def test_websocket_errors_do_not_echo_internal_addresses():
    with patch("app.routers.ws.rag_client.search", new=AsyncMock(side_effect=INTERNAL_RPC)):
        with client.websocket_connect(f"/ws/chat?token={_token()}") as ws:
            ws.send_json({"question": "hi"})
            frame = ws.receive_json()
    assert frame == {"type": "error", "detail": "retrieval-service unavailable (UNAVAILABLE)"}
