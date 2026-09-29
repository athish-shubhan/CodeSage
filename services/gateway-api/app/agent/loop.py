"""Bounded agent loop: understand task -> call tool(s) -> inspect results ->
retrieve more if needed -> final answer. Native Python, no LangGraph. A
handful of tools and a small step cap don't need a graph framework's state
machine; see docs/architecture.md for the full reasoning behind that call.

Bounded by MAX_STEPS (LLM round-trips), MAX_TOOL_CALLS (total tool
invocations), and TIMEOUT_S (wall clock). Any bound being hit ends the loop
with an explicit "insufficient information" answer instead of silently
truncating or looping forever.
"""
from __future__ import annotations

import json
import time

from app.agent.model_router import pick_model
from app.agent.state import AgentState, ToolCallRecord
from app.agent.tools import TOOL_SCHEMAS, call_tool
from app.llm_client import complete_with_tools
from app.metrics import AGENT_STEPS, AGENT_STOP_REASON, AGENT_TOOL_CALLS

SYSTEM_PROMPT = (
    "You are CodeSage, a coding assistant with tools to search and read a codebase. "
    "Use search_code first for any question about the code. Use expand_context or get_file "
    "only when search_code's results aren't enough. Once you have enough information, answer "
    "directly with citations in [path:start-end] format. Do not call more tools than necessary."
)

MAX_STEPS = 4
MAX_TOOL_CALLS = 6
TIMEOUT_S = 60


def _parse_args(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _finish(state: AgentState, reason: str, answer: str, done: bool = False) -> AgentState:
    state.stopped_reason, state.answer, state.done = reason, answer, done
    AGENT_STEPS.observe(state.steps)
    AGENT_STOP_REASON.labels(reason=reason).inc()
    return state


async def run_agent(task: str) -> AgentState:
    state = AgentState(
        task=task,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task}],
    )
    model = pick_model(task)
    start = time.monotonic()

    while state.steps < MAX_STEPS:
        if time.monotonic() - start > TIMEOUT_S:
            return _finish(state, "timeout", "I ran out of time gathering information for this task.")

        state.steps += 1
        allow_tools = len(state.tool_calls) < MAX_TOOL_CALLS
        message = await complete_with_tools(state.messages, tools=TOOL_SCHEMAS if allow_tools else None, model=model)
        state.messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return _finish(state, "done", message.get("content") or "", done=True)

        for tc in tool_calls:
            if len(state.tool_calls) >= MAX_TOOL_CALLS:
                break
            name = tc["function"]["name"]
            raw_args = _parse_args(tc["function"].get("arguments"))
            AGENT_TOOL_CALLS.labels(tool=name).inc()
            result = await call_tool(name, raw_args)
            state.tool_calls.append(ToolCallRecord(name=name, args=raw_args, result=result))
            state.messages.append({"role": "tool", "tool_call_id": tc.get("id", name), "content": result})

    return _finish(
        state, "max_steps", "I couldn't gather enough information within the step limit to answer confidently."
    )
