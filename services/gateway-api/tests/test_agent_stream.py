"""POST /agent/stream: progress events while the agent works, then the answer."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token  # noqa: E402
from app.llm_client import MalformedLLMResponse  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.agent import AgentRequest, agent_stream  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": f"Bearer {create_access_token('admin')}"}
FIXTURE = (Path(__file__).resolve().parents[3] / "eval" / "fixture" / "repo" / "payments.py").read_text()


def _events(text: str) -> list[dict]:
    out = []
    for block in text.strip().split("\n\n"):
        kind, data = block.split("\n", 1)
        event = json.loads(data.removeprefix("data: "))
        assert kind == f"event: {event['type']}"
        out.append(event)
    return out


def _turns(*answers):
    first = {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "get_file", "arguments": '{"source_path": "payments.py"}'}}]}
    return [first, *({"role": "assistant", "content": a} for a in answers)]


def test_stream_reports_progress_then_the_checked_answer():
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=_turns("Skips approval [payments.py:9-10]."))), patch(
        "app.agent.loop.call_tool", new=AsyncMock(return_value=FIXTURE)
    ):
        resp = client.post("/agent/stream", headers=AUTH, json={"task": "safe?"})

    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp.text)
    assert [e["type"] for e in events] == ["step", "tool_call", "tool_result", "step", "answer"]
    assert events[1] == {"type": "tool_call", "name": "get_file", "args": {"source_path": "payments.py"}}
    assert events[2]["injection_flags"] == 2 and events[2]["chars"] > 0
    answer = events[-1]
    assert answer["citations"]["grounded"] == ["payments.py:9-10"]


def test_stream_reports_a_downstream_failure_as_an_error_event():
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=MalformedLLMResponse("bad body"))):
        resp = client.post("/agent/stream", headers=AUTH, json={"task": "x"})
    events = _events(resp.text)
    assert events[-1] == {"type": "error", "detail": "LLM backend unavailable (malformed response)"}


def test_stream_requires_auth():
    assert client.post("/agent/stream", json={"task": "x"}).status_code == 401


def test_a_client_that_disconnects_cancels_the_run():
    cancelled = asyncio.Event()

    async def hangs(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def scenario():
        with patch("app.agent.loop.complete_with_tools", new=hangs):
            resp = await agent_stream(AgentRequest(task="x"), user="admin")
            body = resp.body_iterator
            first = await body.__anext__()  # the run has started
            await body.aclose()  # what Starlette does when the client goes away
            await asyncio.wait_for(cancelled.wait(), timeout=2)
        return first

    assert asyncio.run(scenario()).startswith("event: step")
