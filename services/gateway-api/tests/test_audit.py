import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import audit  # noqa: E402
from app.agent.loop import run_agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.metrics import AGENT_AUDIT_WRITE_FAILURES  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[3] / "eval" / "fixture" / "repo" / "payments.py").read_text()


def _script(*replies):
    return patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=list(replies)))


def _tool_turn(name, args):
    return {"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_audit_log_is_off_by_default():
    assert settings.agent_audit_log == ""


@pytest.mark.asyncio
async def test_disabled_audit_log_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with _script({"role": "assistant", "content": "hi"}):
        await run_agent("anything")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_each_run_appends_one_json_line(tmp_path, monkeypatch):
    log = tmp_path / "logs" / "agent.jsonl"  # parent directory is created on demand
    monkeypatch.setattr(settings, "agent_audit_log", str(log))
    replies = [
        _tool_turn("get_file", {"source_path": "payments.py"}),
        {"role": "assistant", "content": "`refund_payment` skips approval [payments.py:9-10]. See [payments.py:8]. `issue_refund` is here [payments.py:9]."},
    ]
    with _script(*replies), patch("app.agent.loop.call_tool", new=AsyncMock(return_value=FIXTURE)):
        await run_agent("Is refund_payment safe?")
    with _script({"role": "assistant", "content": "no idea"}):
        await run_agent("second task")

    first, second = _lines(log)
    assert first["task_sha256"] == hashlib.sha256(b"Is refund_payment safe?").hexdigest()
    assert "Is refund_payment safe?" not in log.read_text()  # the task is stored only as a hash
    assert first["model"] == settings.llm_model
    assert first["stopped_reason"] == "done" and first["steps"] == 2 and first["error"] is None
    assert first["tool_calls"] == [{"name": "get_file", "args": {"source_path": "payments.py"}}]
    assert first["citations"]["grounded"] == ["payments.py:9-10", "payments.py:9-9"]
    assert first["citations"]["ungrounded"] == ["payments.py:8-8"]  # the removed injection line
    assert first["citations"]["unsupported_identifiers"] == [
        {"identifier": "issue_refund", "citations": ["payments.py:9-9"]}
    ]
    assert [(f["rule"], f["start_line"]) for f in first["injection_flags"]] == [
        ("addressed_to_ai", 7),
        ("ignore_instructions", 8),
    ]
    assert first["duration_ms"] >= 0 and first["ts"].endswith("+00:00")
    assert second["steps"] == 1 and second["tool_calls"] == [] and second["injection_flags"] == []


@pytest.mark.asyncio
async def test_a_run_that_raises_is_still_logged(tmp_path, monkeypatch):
    log = tmp_path / "agent.jsonl"
    monkeypatch.setattr(settings, "agent_audit_log", str(log))
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=RuntimeError("backend down"))):
        with pytest.raises(RuntimeError):
            await run_agent("task")
    (line,) = _lines(log)
    assert line["stopped_reason"] == "error" and line["error"] == "RuntimeError" and line["steps"] == 1


@pytest.mark.asyncio
async def test_unwritable_audit_log_does_not_fail_the_run(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(settings, "agent_audit_log", str(blocker / "agent.jsonl"))
    before = AGENT_AUDIT_WRITE_FAILURES._value.get()
    with _script({"role": "assistant", "content": "fine"}):
        state = await run_agent("task")
    assert state.answer == "fine"
    assert AGENT_AUDIT_WRITE_FAILURES._value.get() == before + 1


def test_entry_is_json_serializable_for_an_unfinished_state():
    from app.agent.state import AgentState

    json.dumps(audit.entry(AgentState(task="t"), "m", 0.0, "CancelledError"))
