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
