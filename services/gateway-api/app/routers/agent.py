from dataclasses import asdict

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agent.loop import run_agent
from app.auth import current_user
from app.config import settings

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    task: str = Field(max_length=settings.max_question_chars)


class UnsupportedIdentifier(BaseModel):
    identifier: str  # a code name or path the answer attributes to the citations below
    citations: list[str]  # "path:start-end"; none of their tool text contains the identifier


class Citations(BaseModel):
    grounded: list[str]  # "path:start-end" backed by a tool result in this run
    ungrounded: list[str]  # cited by the model, never shown to it by a tool (or only as removed text)
    unsupported_identifiers: list[UnsupportedIdentifier] = []


class InjectionFlag(BaseModel):
    tool: str
    rule: str  # which app/agent/untrusted.py rule matched
    text: str  # the removed sentence (truncated)
    source_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class AgentResponse(BaseModel):
    answer: str
    steps: int
    stopped_reason: str
    tool_calls: list[dict]
    citations: Citations
    injection_flags: list[InjectionFlag] = []  # instruction-like text removed from tool results


@router.post("", response_model=AgentResponse)
async def agent(req: AgentRequest, user: str = Depends(current_user)) -> AgentResponse:
    """Bounded multi-step agent: retrieves, inspects, and can call more
    tools before answering, unlike /chat's single retrieve-then-answer
    pass. See app/agent/loop.py for the step/tool-call/timeout bounds."""
    try:
        state = await run_agent(req.task)
    except httpx.HTTPError as exc:
        from app.errors import downstream_http_exception

        raise downstream_http_exception(exc) from exc

    return AgentResponse(
        answer=state.answer or "",
        steps=state.steps,
        stopped_reason=state.stopped_reason or "unknown",
        tool_calls=[asdict(tc) for tc in state.tool_calls],
        citations=Citations(**state.citations, unsupported_identifiers=state.unsupported_identifiers),
        injection_flags=[asdict(f) for f in state.injection_flags],
    )
