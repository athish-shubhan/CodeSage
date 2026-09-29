from dataclasses import asdict

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agent.loop import run_agent
from app.auth import current_user

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    task: str


class AgentResponse(BaseModel):
    answer: str
    steps: int
    stopped_reason: str
    tool_calls: list[dict]


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
    )
