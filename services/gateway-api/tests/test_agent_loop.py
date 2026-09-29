import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop import MAX_STEPS, MAX_TOOL_CALLS, run_agent  # noqa: E402


def _msg(content=None, tool_calls=None):
    m = {"role": "assistant"}
    if content is not None:
        m["content"] = content
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    return m


def _tool_call(name, args="{}", call_id="c1"):
    return {"id": call_id, "function": {"name": name, "arguments": args}}


@pytest.mark.asyncio
async def test_answers_immediately_when_no_tool_call_needed():
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(return_value=_msg(content="42"))):
        state = await run_agent("what is 6*7")

    assert state.done is True
    assert state.stopped_reason == "done"
    assert state.answer == "42"
    assert state.steps == 1
    assert state.tool_calls == []


@pytest.mark.asyncio
async def test_calls_tool_then_answers():
    responses = [
        _msg(tool_calls=[_tool_call("search_code", '{"query": "auth"}')]),
        _msg(content="Auth is handled in auth.py [auth.py:1-10]"),
    ]
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=responses)), patch(
        "app.agent.loop.call_tool", new=AsyncMock(return_value="[auth.py:1-10]\ndef authenticate(): ...")
    ):
        state = await run_agent("how does auth work")

    assert state.done is True
    assert state.steps == 2
    assert len(state.tool_calls) == 1
    assert state.tool_calls[0].name == "search_code"
    assert "auth.py" in state.answer


@pytest.mark.asyncio
async def test_stops_at_max_steps_if_model_never_finishes():
    always_wants_tool = AsyncMock(return_value=_msg(tool_calls=[_tool_call("search_code")]))
    with patch("app.agent.loop.complete_with_tools", new=always_wants_tool), patch(
        "app.agent.loop.call_tool", new=AsyncMock(return_value="some result")
    ):
        state = await run_agent("an unanswerable loop-inducing task")

    assert state.stopped_reason == "max_steps"
    assert state.steps == MAX_STEPS
    assert state.answer  # never empty, always says something


@pytest.mark.asyncio
async def test_stops_calling_tools_once_max_tool_calls_hit():
    # Each step returns MAX_TOOL_CALLS+2 tool calls in one batch, forcing the
    # per-batch cap to kick in before MAX_STEPS would.
    many_calls = [_tool_call("search_code", call_id=str(i)) for i in range(MAX_TOOL_CALLS + 2)]
    responses = [_msg(tool_calls=many_calls)] * MAX_STEPS
    with patch("app.agent.loop.complete_with_tools", new=AsyncMock(side_effect=responses)), patch(
        "app.agent.loop.call_tool", new=AsyncMock(return_value="result")
    ):
        state = await run_agent("task that requests too many tools")

    assert len(state.tool_calls) == MAX_TOOL_CALLS  # never exceeds the cap
