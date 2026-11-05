import asyncio
import json
from dataclasses import asdict

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.loop import run_agent
from app.auth import current_user
from app.config import settings
from app.errors import downstream_http_exception, log, public_detail
from app.models import Citations, InjectionFlag

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    task: str = Field(max_length=settings.max_question_chars)


class AgentResponse(BaseModel):
    answer: str
    steps: int
    stopped_reason: str
    tool_calls: list[dict]
    citations: Citations
    injection_flags: list[InjectionFlag] = []  # instruction-like text removed from tool results


def _response(state) -> AgentResponse:
    return AgentResponse(
        answer=state.answer or "",
        steps=state.steps,
        stopped_reason=state.stopped_reason or "unknown",
        tool_calls=[asdict(tc) for tc in state.tool_calls],
        citations=Citations(**state.citations, unsupported_identifiers=state.unsupported_identifiers),
        injection_flags=[asdict(f) for f in state.injection_flags],
    )


@router.post("", response_model=AgentResponse)
async def agent(req: AgentRequest, user: str = Depends(current_user)) -> AgentResponse:
    """Bounded multi-step agent: retrieves, inspects, and can call more
    tools before answering, unlike /chat's single retrieve-then-answer
    pass. See app/agent/loop.py for the step/tool-call/timeout bounds."""
    try:
        state = await run_agent(req.task)
    except httpx.HTTPError as exc:
        raise downstream_http_exception(exc) from exc
    return _response(state)


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def agent_stream(req: AgentRequest, user: str = Depends(current_user)) -> StreamingResponse:
    """The same agent run as POST /agent, as server-sent events while it works:
    `step`, `tool_call` and `tool_result` as they happen, then one
    `answer` event carrying the full AgentResponse (or one `error` event). A
    run can take up to the 60 s deadline, and this shows the client what it is
    doing meanwhile. If the client disconnects, the run is cancelled."""
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def run() -> None:
        try:
            state = await run_agent(req.task, on_event=queue.put)
            await queue.put({"type": "answer", **_response(state).model_dump()})
        except httpx.HTTPError as exc:
            detail = public_detail(exc)
            log.warning("downstream failure on /agent/stream: %s: %r", detail, exc)
            await queue.put({"type": "error", "detail": detail})
        except Exception:
            log.exception("agent run failed on /agent/stream")
            await queue.put({"type": "error", "detail": "internal error"})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(run())
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            if not task.done():
                task.cancel()  # the client went away; stop spending LLM and tool calls on it

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
