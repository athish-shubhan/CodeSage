import grpc
import httpx
from fastapi import APIRouter, Depends

from app import rag_client
from app.auth import current_user
from app.errors import downstream_http_exception
from app.llm_client import build_prompt, stream_chat
from app.models import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, user: str = Depends(current_user)) -> ChatResponse:
    """Non-streaming REST endpoint: retrieve context, then generate a full answer."""
    try:
        sources = await rag_client.search(req.question, top_k=req.top_k, collection=req.collection)
        prompt = build_prompt(req.question, sources)
        answer = "".join([token async for token in stream_chat(prompt)])
    except (grpc.aio.AioRpcError, httpx.HTTPError) as exc:
        raise downstream_http_exception(exc) from exc
    return ChatResponse(answer=answer, sources=sources)
