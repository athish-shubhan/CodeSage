"""Size bounds on what one request can ask the gateway to send onward."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": f"Bearer {create_access_token('admin')}"}
LIMIT = settings.max_question_chars


@pytest.mark.parametrize(
    "body",
    [{"question": "x" * (LIMIT + 1)}, {"question": "hi", "top_k": 0}, {"question": "hi", "top_k": 51}],
)
def test_chat_rejects_oversized_requests_before_any_downstream_call(body):
    search = AsyncMock(return_value=[])
    with patch("app.routers.chat.rag_client.search", new=search):
        resp = client.post("/chat", headers=AUTH, json=body)
    assert resp.status_code == 422
    search.assert_not_called()


def test_chat_accepts_a_question_at_the_limit():
    async def tokens(prompt):
        yield "ok"

    with patch("app.routers.chat.rag_client.search", new=AsyncMock(return_value=[])), patch(
        "app.routers.chat.stream_chat", new=tokens
    ):
        resp = client.post("/chat", headers=AUTH, json={"question": "x" * LIMIT, "top_k": 50})
    assert resp.status_code == 200 and resp.json()["answer"] == "ok"


def test_agent_rejects_an_oversized_task():
    with patch("app.routers.agent.run_agent", new=AsyncMock()) as run:
        resp = client.post("/agent", headers=AUTH, json={"task": "x" * (LIMIT + 1)})
    assert resp.status_code == 422
    run.assert_not_called()


def test_websocket_rejects_an_oversized_question_and_stays_open():
    with patch("app.routers.ws.rag_client.search", new=AsyncMock(return_value=[])) as search:
        with client.websocket_connect(f"/ws/chat?token={create_access_token('admin')}") as ws:
            ws.send_json({"question": "x" * (LIMIT + 1)})
            frame = ws.receive_json()
    assert frame["type"] == "error" and str(LIMIT) in frame["detail"]
    search.assert_not_called()
