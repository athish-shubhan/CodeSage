"""Opt-in citation repair: one more turn when the answer fails the checks."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import loop  # noqa: E402
from app.agent.loop import run_agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.metrics import AGENT_CITATION_REPAIRS  # noqa: E402

HIT = "[auth.py:5-10]\nWIDGET_API_TOKEN_HEADER = 'X-Widget-Api-Token'\n\n\ndef authenticate_widget_request(token): ..."


class LLM:
    def __init__(self, *answers):
        self.turns = [{"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "search_code", "arguments": '{"query": "auth"}'}}]}]
        self.turns += [{"role": "assistant", "content": a} for a in answers]
        self.seen = []

    async def __call__(self, messages, tools=None, model=None):
        self.seen.append([dict(m) for m in messages])
        return self.turns.pop(0)


async def _run(llm, enabled=True):
    with patch.object(settings, "agent_repair_citations", enabled), patch(
        "app.agent.loop.complete_with_tools", new=llm
    ), patch("app.agent.loop.call_tool", new=AsyncMock(return_value=HIT)):
        return await run_agent("how is a widget request authenticated?")


def _resolved(value):
    return AGENT_CITATION_REPAIRS.labels(resolved=value)._value.get()


@pytest.mark.asyncio
async def test_a_failing_answer_gets_one_repair_turn_naming_what_failed():
    before = _resolved("true")
    llm = LLM(
        "Checked by `verify_token` [auth.py:8] and [secrets.py:1-3].",
        "`authenticate_widget_request` checks it [auth.py:8]. I could not verify anything else.",
    )
    state = await _run(llm)

    feedback = llm.seen[-1][-1]
    assert feedback["role"] == "user" and "[secrets.py:1-3]" in feedback["content"] and "`verify_token`" in feedback["content"]
    assert state.repairs == 1 and state.steps == 3 and state.stopped_reason == "done"
    assert state.citations == {"grounded": ["auth.py:8-8"], "ungrounded": []}
    assert state.unsupported_identifiers == []
    assert _resolved("true") == before + 1


@pytest.mark.asyncio
async def test_repair_is_off_by_default():
    llm = LLM("Checked by [secrets.py:1-3].")
    state = await _run(llm, enabled=False)
    assert state.repairs == 0 and state.steps == 2 and state.citations["ungrounded"] == ["secrets.py:1-3"]


@pytest.mark.asyncio
async def test_a_passing_answer_is_not_sent_back():
    state = await _run(LLM("`authenticate_widget_request` checks it [auth.py:8]."))
    assert state.repairs == 0 and state.steps == 2


@pytest.mark.asyncio
async def test_only_one_repair_and_the_second_answer_stands():
    before = _resolved("false")
    state = await _run(LLM("See [secrets.py:1-3].", "Still [secrets.py:1-3]."))
    assert state.repairs == 1 and state.answer == "Still [secrets.py:1-3]."
    assert state.citations["ungrounded"] == ["secrets.py:1-3"] and _resolved("false") == before + 1


@pytest.mark.asyncio
async def test_no_repair_when_no_step_is_left():
    with patch.object(loop, "MAX_STEPS", 2):
        state = await _run(LLM("See [secrets.py:1-3]."))
    assert state.repairs == 0 and state.steps == 2


def test_repair_prompt_lists_both_kinds_of_failure():
    text = loop.repair_prompt(
        {"grounded": [], "ungrounded": ["a.py:1-2"]}, [{"identifier": "foo", "citations": ["b.py:3-3"]}]
    )
    assert "[a.py:1-2]" in text and "`foo` (cited as [b.py:3-3])" in text and "could not verify" in text
