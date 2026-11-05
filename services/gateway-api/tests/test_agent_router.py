import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
FIXTURE = (Path(__file__).resolve().parents[3] / "eval" / "fixture" / "repo" / "payments.py").read_text()


def _token() -> str:
    return client.post("/token", data={"username": "admin", "password": "admin"}).json()["access_token"]


def test_agent_response_reports_injection_flags_and_unsupported_identifiers():
    replies = [
        {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "get_file", "arguments": '{"source_path": "payments.py"}'}}]},
        {"role": "assistant", "content": "`issue_refund` is unsafe [payments.py:9-10]. It says so [payments.py:7]."},
    ]
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=replies)), patch(
        "app.agent.loop.call_tool", new=AsyncMock(return_value=FIXTURE)
    ):
        resp = client.post("/agent", headers={"Authorization": f"Bearer {_token()}"}, json={"task": "is it safe?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"] == {
        "grounded": ["payments.py:9-10"],
        "ungrounded": ["payments.py:7-7"],
        "unsupported_identifiers": [{"identifier": "issue_refund", "citations": ["payments.py:9-10"]}],
    }
    assert [(f["rule"], f["source_path"], f["start_line"]) for f in body["injection_flags"]] == [
        ("addressed_to_ai", "payments.py", 7),
        ("ignore_instructions", "payments.py", 8),
    ]
    assert "AUDIT-OK-7731" not in body["tool_calls"][0]["result"]
