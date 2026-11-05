import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_ws_chat_rejects_missing_token():
    """Guards against the bug where decode_token's HTTPException wasn't
    translated to a WS close frame and instead crashed the connection."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/chat"):
            pass
    assert exc_info.value.code == 1008
    assert "missing token" in exc_info.value.reason


def test_ws_chat_rejects_invalid_token():
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/chat?token=not-a-real-jwt"):
            pass
    assert exc_info.value.code == 1008
    assert "Invalid or expired token" in exc_info.value.reason


def _ws(token=None):
    from app.auth import create_access_token

    return client.websocket_connect(f"/ws/chat?token={token or create_access_token('admin')}")


async def _fake_stream(prompt):
    for t in ("hel", "lo"):
        yield t


def test_bad_frames_get_an_error_and_the_socket_stays_usable():
    from unittest.mock import AsyncMock, patch

    with patch("app.routers.ws.rag_client.search", new=AsyncMock(return_value=[])), patch(
        "app.routers.ws.stream_chat", new=_fake_stream
    ):
        with _ws() as ws:
            for bad in ("not json", "[1, 2]", '{"question": 5}', '{"question": "  "}', "{}"):
                ws.send_text(bad)
                assert ws.receive_json()["type"] == "error"
            ws.send_json({"question": "hi"})
            frames = [ws.receive_json() for _ in range(4)]
    assert [f["type"] for f in frames] == ["sources", "token", "token", "done"]


def test_socket_is_closed_once_its_token_expires():
    """The token is valid at the handshake and expired by the next message."""
    from unittest.mock import patch

    from fastapi import HTTPException

    expired = HTTPException(status_code=401, detail="Invalid or expired token")
    with patch("app.routers.ws.decode_token", side_effect=["admin", expired]):
        with _ws() as ws:
            ws.send_json({"question": "hi"})
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
    assert exc_info.value.code == 1008
    assert exc_info.value.reason == "Invalid or expired token"
