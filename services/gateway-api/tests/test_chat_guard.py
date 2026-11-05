"""/chat and /ws/chat get the agent layer's injection guard and citation
checks: retrieved text is sanitized and delimited before the prompt, and the
answer is checked against what the model was shown."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token  # noqa: E402
from app.chat_guard import sanitize_sources  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
TOKEN = create_access_token("admin")
LINES = (Path(__file__).resolve().parents[3] / "eval" / "fixture" / "repo" / "payments.py").read_text().split("\n")
HIT = {"source_path": "payments.py", "start_line": 6, "end_line": 11, "text": "\n".join(LINES[5:11]), "score": 0.9}
ANSWER = "Large refunds skip approval in `refund_payment` [payments.py:9-10]. It was audited [payments.py:7-8]. See `issue_refund` [payments.py:9]."


def _llm(seen):
    async def stream(prompt):
        seen.append(prompt)
        for part in (ANSWER[:40], ANSWER[40:]):
            yield part

    return stream


def test_sanitize_sources_maps_removals_to_file_lines_and_keeps_the_original():
    clean, flags = sanitize_sources([HIT])
    assert [(f.tool, f.source_path, f.start_line, f.end_line) for f in flags] == [
        ("retrieval", "payments.py", 7, 7),
        ("retrieval", "payments.py", 8, 8),
    ]
    assert "AUDIT-OK-7731" not in clean[0]["text"] and "AUDIT-OK-7731" in HIT["text"]
    assert len(clean[0]["text"].split("\n")) == len(HIT["text"].split("\n"))


def test_chat_strips_injection_from_the_prompt_and_checks_the_answer():
    seen = []
    with patch("app.routers.chat.rag_client.search", new=AsyncMock(return_value=[HIT])), patch(
        "app.routers.chat.stream_chat", new=_llm(seen)
    ):
        resp = client.post("/chat", headers={"Authorization": f"Bearer {TOKEN}"}, json={"question": "safe?"})

    assert resp.status_code == 200
    (prompt,) = seen
    assert "AUDIT-OK-7731" not in prompt and "NOTE to any AI assistant" not in prompt
    assert "<<untrusted tool_output id=" in prompt and "approved_by is None" in prompt
    body = resp.json()
    assert body["sources"] == [HIT]  # the caller still sees what was retrieved
    assert body["citations"] == {
        "grounded": ["payments.py:9-10", "payments.py:9-9"],
        "ungrounded": ["payments.py:7-8"],
        "unsupported_identifiers": [{"identifier": "issue_refund", "citations": ["payments.py:9-9"]}],
    }
    assert [(f["rule"], f["start_line"]) for f in body["injection_flags"]] == [
        ("addressed_to_ai", 7),
        ("ignore_instructions", 8),
    ]


def test_websocket_reports_flags_with_sources_and_citations_when_done():
    seen = []
    with patch("app.routers.ws.rag_client.search", new=AsyncMock(return_value=[HIT])), patch(
        "app.routers.ws.stream_chat", new=_llm(seen)
    ):
        with client.websocket_connect(f"/ws/chat?token={TOKEN}") as ws:
            ws.send_json({"question": "safe?"})
            frames = [ws.receive_json() for _ in range(4)]

    sources, _, _, done = frames
    assert "AUDIT-OK-7731" not in seen[0]
    assert sources["type"] == "sources" and [f["start_line"] for f in sources["injection_flags"]] == [7, 8]
    assert done["type"] == "done"
    assert done["citations"]["ungrounded"] == ["payments.py:7-8"]
    assert done["citations"]["unsupported_identifiers"][0]["identifier"] == "issue_refund"


def test_chat_with_no_sources_has_empty_verdicts():
    with patch("app.routers.chat.rag_client.search", new=AsyncMock(return_value=[])), patch(
        "app.routers.chat.stream_chat", new=_llm([])
    ):
        body = client.post("/chat", headers={"Authorization": f"Bearer {TOKEN}"}, json={"question": "x"}).json()
    assert body["injection_flags"] == []
    assert body["citations"]["grounded"] == [] and len(body["citations"]["ungrounded"]) == 3
