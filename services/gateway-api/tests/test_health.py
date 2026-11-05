import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
UP = {"ok": True, "vector_store_status": "ok"}
DOWN = {"ok": False, "vector_store_status": "unreachable: connection refused"}


@pytest.mark.parametrize(
    "llm_ok, retrieval, status",
    [(True, UP, 200), (False, UP, 503), (True, DOWN, 503), (False, DOWN, 503)],
)
def test_readiness_status_code_follows_dependencies(llm_ok, retrieval, status):
    with patch("app.main.llm_client.health", new=AsyncMock(return_value=llm_ok)), patch(
        "app.main.rag_client.health", new=AsyncMock(return_value=retrieval)
    ):
        resp = client.get("/healthz")
    assert resp.status_code == status
    body = resp.json()
    assert body["ready"] is (status == 200)
    assert body["llm_status"] == ("ok" if llm_ok else "unreachable") and body["retrieval"] == retrieval


def test_liveness_ignores_dependencies():
    with patch("app.main.llm_client.health", new=AsyncMock(return_value=False)):
        assert client.get("/livez").status_code == 200
