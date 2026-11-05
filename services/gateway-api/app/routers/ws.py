import json

import grpc
import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, WebSocketException, status

from app import rag_client
from app.auth import decode_token
from app.config import settings
from app.llm_client import build_prompt, stream_chat

router = APIRouter(tags=["chat"])


def _question(raw: str) -> str | None:
    """The question in a client frame, or None if the frame is not a JSON
    object carrying a non-empty one within the size limit /chat also applies."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    question = payload.get("question") if isinstance(payload, dict) else None
    ok = isinstance(question, str) and question.strip() and len(question) <= settings.max_question_chars
    return question if ok else None


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Streaming chat over WebSocket. Auth token is passed as a query param
    (`?token=...`) since browser WebSocket clients can't set auth headers."""
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="missing token")
    try:
        decode_token(token)
    except HTTPException as exc:
        # decode_token raises an HTTP-flavored exception; there's no HTTP
        # response cycle on a WebSocket, so translate it to a close frame.
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=exc.detail) from exc

    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            # The handshake token is re-checked on every message: a socket can
            # stay open for hours, and should not outlive the token's expiry.
            try:
                decode_token(token)
            except HTTPException as exc:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=exc.detail)
                return
            question = _question(raw)
            if question is None:
                # One bad frame is the client's error to fix, not a reason to drop the connection.
                await websocket.send_json(
                    {"type": "error", "detail": 'expected a JSON object like {"question": "..."} '
                     f"with at most {settings.max_question_chars} characters"}
                )
                continue

            try:
                sources = await rag_client.search(question)
                await websocket.send_json({"type": "sources", "sources": sources})

                prompt = build_prompt(question, sources)
                async for token_text in stream_chat(prompt):
                    await websocket.send_json({"type": "token", "text": token_text})
            except (grpc.aio.AioRpcError, httpx.HTTPError) as exc:
                await websocket.send_json({"type": "error", "detail": str(exc)})
                continue

            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
