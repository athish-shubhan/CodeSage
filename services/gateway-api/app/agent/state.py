"""Agent execution state, explicitly separate from conversation history
(the per-session message log a router owns across turns) and from
retrieved context (ephemeral, lives only inside a tool call's result for
this one task). This is just "where is this one task up to."
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    result: str


@dataclass
class InjectionFlag:
    """One instruction-like sentence removed from a tool result before the
    model saw it (see untrusted.py). source_path/lines are None when the
    text was not file content, e.g. an error message."""

    tool: str
    rule: str
    text: str
    source_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None


@dataclass
class AgentState:
    task: str
    messages: list[dict] = field(default_factory=list)  # the LLM conversation for this task
    tool_calls: list[ToolCallRecord] = field(default_factory=list)  # result is what the model saw, after sanitizing
    steps: int = 0
    done: bool = False
    answer: str | None = None
    stopped_reason: str | None = None  # "done" | "max_steps" | "timeout"
    citations: dict = field(default_factory=dict)  # {"grounded": [...], "ungrounded": [...]}, see citations.py
    unsupported_identifiers: list[dict] = field(default_factory=list)  # see citations.unsupported_identifiers
    injection_flags: list[InjectionFlag] = field(default_factory=list)  # what untrusted.py removed, per tool result
    repairs: int = 0  # citation-repair turns used (loop.py, GATEWAY_AGENT_REPAIR_CITATIONS)
