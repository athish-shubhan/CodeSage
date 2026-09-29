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
class AgentState:
    task: str
    messages: list[dict] = field(default_factory=list)  # the LLM conversation for this task
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    done: bool = False
    answer: str | None = None
    stopped_reason: str | None = None  # "done" | "max_steps" | "timeout"
