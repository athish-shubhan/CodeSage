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
