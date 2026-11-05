"""The injection guard inside the real agent loop: a tool result carrying
an injected comment (eval/fixture/repo/payments.py) is stripped before the
model sees it, recorded on AgentState, and cannot be cited."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop import SYSTEM_PROMPT, run_agent  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[3] / "eval" / "fixture" / "repo" / "payments.py").read_text()
INJECTED = ("AUDIT-OK-7731", "Ignore previous instructions", "NOTE to any AI assistant")


def _call(name, args, call_id="c1"):
    return {"role": "assistant", "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": args}}]}


class ScriptedLLM:
    """Returns scripted replies and keeps a copy of every transcript it was sent."""

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    async def __call__(self, messages, tools=None, model=None):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


async def _run(tool_result, tool_call, answer):
    llm = ScriptedLLM([tool_call, {"role": "assistant", "content": answer}])
    with patch("app.agent.loop.complete_with_tools", new=llm), patch(
        "app.agent.loop.call_tool", new=AsyncMock(return_value=tool_result)
    ):
        state = await run_agent("Is refund_payment safe?")
    return state, llm


@pytest.mark.asyncio
async def test_injected_comment_from_get_file_is_stripped_recorded_and_uncitable():
    answer = (
        "`refund_payment` approves large refunds without approval [payments.py:9-10]. "
        "The file says it was audited [payments.py:7-8]."
    )
    state, llm = await _run(FIXTURE, _call("get_file", '{"source_path": "payments.py"}'), answer)

    sent = "\n".join(m.get("content") or "" for m in llm.seen[-1])
    assert not any(phrase in sent for phrase in INJECTED)  # never reached the model
    assert "approved_by is None" in sent  # the code itself did

    assert [(f.rule, f.source_path, f.start_line, f.end_line) for f in state.injection_flags] == [
        ("addressed_to_ai", "payments.py", 7, 7),
        ("ignore_instructions", "payments.py", 8, 8),
    ]
    assert "AUDIT-OK-7731" in state.injection_flags[1].text  # what was removed is kept for audit
    assert state.citations == {"grounded": ["payments.py:9-10"], "ungrounded": ["payments.py:7-8"]}
    assert "AUDIT-OK-7731" not in state.tool_calls[0].result


@pytest.mark.asyncio
async def test_injected_comment_in_a_search_hit_maps_to_file_lines():
    hit = "[payments.py:6-11]\n" + "\n".join(FIXTURE.split("\n")[5:11])
    state, _ = await _run(hit, _call("search_code", '{"query": "refund"}'), "See [payments.py:8].")
    assert [(f.source_path, f.start_line) for f in state.injection_flags] == [("payments.py", 7), ("payments.py", 8)]
    assert state.citations["ungrounded"] == ["payments.py:8-8"]


@pytest.mark.asyncio
async def test_tool_results_are_wrapped_as_untrusted_data():
    state, llm = await _run("plain result", _call("search_code", '{"query": "x"}'), "done")
    tool_msg = next(m for m in llm.seen[-1] if m["role"] == "tool")
    assert tool_msg["content"].startswith("<<untrusted tool_output id=")
    assert "\nplain result\n" in tool_msg["content"]
    assert tool_msg["content"].rstrip().endswith(">>")
    assert "never instructions" in SYSTEM_PROMPT and llm.seen[0][0]["content"] == SYSTEM_PROMPT
    assert state.injection_flags == []


@pytest.mark.asyncio
async def test_unsupported_identifiers_are_reported_on_the_state():
    state, _ = await _run(
        FIXTURE, _call("get_file", '{"source_path": "payments.py"}'), "`issue_refund` does it [payments.py:6-11]."
    )
    assert state.citations["grounded"] == ["payments.py:6-11"]
    assert state.unsupported_identifiers == [{"identifier": "issue_refund", "citations": ["payments.py:6-11"]}]


@pytest.mark.asyncio
async def test_invented_tool_names_share_one_metric_series():
    from app.metrics import AGENT_TOOL_CALLS

    def series():
        return {s.labels["tool"] for m in AGENT_TOOL_CALLS.collect() for s in m.samples if s.name.endswith("_total")}

    before = series()
    calls = [{"id": str(i), "function": {"name": f"invented_{i}", "arguments": "{}"}} for i in range(4)]
    llm = ScriptedLLM([{"role": "assistant", "tool_calls": calls}, {"role": "assistant", "content": "done"}])
    with patch("app.agent.loop.complete_with_tools", new=llm):
        state = await run_agent("x")
    assert series() - before <= {"unknown"}
    assert all(not s.startswith("invented_") for s in series())
    assert state.tool_calls[0].result == "Unknown tool: invented_0"


@pytest.mark.asyncio
async def test_malformed_tool_arguments_get_an_accurate_error_and_no_call():
    tool = AsyncMock(return_value="should not run")
    llm = ScriptedLLM([_call("search_code", "{oops"), {"role": "assistant", "content": "done"}])
    with patch("app.agent.loop.complete_with_tools", new=llm), patch("app.agent.loop.call_tool", new=tool):
        state = await run_agent("x")
    tool.assert_not_called()
    assert state.tool_calls[0].args == {}
    assert state.tool_calls[0].result == "Invalid arguments for search_code: arguments must be a JSON object."
