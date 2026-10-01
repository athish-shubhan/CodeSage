"""Bounded agent loop: understand task -> call tool(s) -> inspect results ->
retrieve more if needed -> final answer. Native Python, no LangGraph. A
handful of tools and a small step cap don't need a graph framework's state
machine; see docs/adr/0003-native-agent-loop.md.

Bounded by MAX_STEPS (LLM round-trips), MAX_TOOL_CALLS (total tool
invocations), and TIMEOUT_S, a hard wall-clock deadline over the whole run
that also cancels an in-flight LLM or tool call. Any bound being hit ends
the loop with an explicit "insufficient information" answer instead of
silently truncating or looping forever.
"""
from __future__ import annotations

import asyncio
import json

from app.agent import citations
from app.agent.model_router import pick_model
from app.agent.state import AgentState, ToolCallRecord
from app.agent.tools import TOOL_SCHEMAS, call_tool
from app.llm_client import complete_with_tools
from app.metrics import AGENT_CITATIONS, AGENT_STEPS, AGENT_STOP_REASON, AGENT_TOOL_CALLS

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
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return args if isinstance(args, dict) else {}


def _finish(state: AgentState, reason: str, answer: str, done: bool = False) -> AgentState:
    state.stopped_reason, state.answer, state.done = reason, answer, done
    state.citations = citations.check(answer, state.tool_calls)
    AGENT_STEPS.observe(state.steps)
    AGENT_STOP_REASON.labels(reason=reason).inc()
    AGENT_CITATIONS.labels(grounded="true").inc(len(state.citations["grounded"]))
    AGENT_CITATIONS.labels(grounded="false").inc(len(state.citations["ungrounded"]))
    return state


async def _run_tools(state: AgentState, tool_calls: list[dict]) -> None:
    """Runs this step's tool calls concurrently (they are independent
    read-only lookups) and answers every tool_call id, including ones
    skipped for exceeding MAX_TOOL_CALLS. OpenAI-compatible servers reject
    a transcript where an assistant tool_call has no matching tool message."""
    budget = MAX_TOOL_CALLS - len(state.tool_calls)
    admitted, skipped = tool_calls[:budget], tool_calls[budget:]

    parsed = [(tc["function"]["name"], _parse_args(tc["function"].get("arguments"))) for tc in admitted]
    results = await asyncio.gather(*(call_tool(name, args) for name, args in parsed))

    for tc, (name, args), result in zip(admitted, parsed, results):
        AGENT_TOOL_CALLS.labels(tool=name).inc()
        state.tool_calls.append(ToolCallRecord(name=name, args=args, result=result))
        state.messages.append({"role": "tool", "tool_call_id": tc.get("id", name), "content": result})
    for tc in skipped:
        state.messages.append(
            {"role": "tool", "tool_call_id": tc.get("id", ""), "content": "Skipped: tool-call budget exhausted."}
        )


async def run_agent(task: str) -> AgentState:
    state = AgentState(
        task=task,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task}],
    )
    model = pick_model(task)

    try:
        async with asyncio.timeout(TIMEOUT_S):
            while state.steps < MAX_STEPS:
                state.steps += 1
                allow_tools = len(state.tool_calls) < MAX_TOOL_CALLS
                message = await complete_with_tools(
                    state.messages, tools=TOOL_SCHEMAS if allow_tools else None, model=model
                )
                state.messages.append(message)

                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return _finish(state, "done", message.get("content") or "", done=True)
                await _run_tools(state, tool_calls)
    except TimeoutError:
        return _finish(state, "timeout", "I ran out of time gathering information for this task.")

    return _finish(
        state, "max_steps", "I couldn't gather enough information within the step limit to answer confidently."
    )
