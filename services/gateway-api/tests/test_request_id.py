import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import rag_client, request_id  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_a_valid_client_id_is_echoed():
    assert client.get("/livez", headers={"X-Request-ID": "abc-123.x:y"}).headers["x-request-id"] == "abc-123.x:y"


@pytest.mark.parametrize("given", [None, "has spaces", "x" * 200, "<script>", "a;b"])
def test_a_missing_or_unsafe_id_is_replaced(given):
    headers = {"X-Request-ID": given} if given else {}
    rid = client.get("/livez", headers=headers).headers["x-request-id"]
    assert rid != given and len(rid) == 32


def test_the_id_reaches_the_audit_log_and_the_response(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "agent_audit_log", str(log))
    auth = {"Authorization": f"Bearer {create_access_token('admin')}", "X-Request-ID": "req-audit-7"}
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(return_value={"role": "assistant", "content": "hi"})):
        body = client.post("/agent", headers=auth, json={"task": "x"}).json()
    assert body["request_id"] == "req-audit-7"
    assert json.loads(log.read_text())["request_id"] == "req-audit-7"


@pytest.mark.asyncio
async def test_grpc_calls_carry_the_id_as_metadata():
    sent = {}

    class Stub:
        async def Search(self, request, timeout=None, metadata=None):
            sent["metadata"] = metadata
            return type("R", (), {"chunks": []})()

    token = request_id._current.set("req-grpc-9")
    try:
        with patch.object(rag_client, "_stub", new=lambda: Stub()):
            await rag_client.search("q")
    finally:
        request_id._current.reset(token)
    assert sent["metadata"] == (("x-request-id", "req-grpc-9"),)


def test_log_lines_carry_the_id():
    import logging

    record = logging.LogRecord("gateway-api", logging.WARNING, __file__, 1, "msg", None, None)
    token = request_id._current.set("req-log-1")
    try:
        request_id.RequestIdFilter().filter(record)
    finally:
        request_id._current.reset(token)
    assert record.request_id == "req-log-1"
