import json

import grpc
import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, WebSocketException, status

from app import rag_client
from app.auth import decode_token
from app.llm_client import build_prompt, stream_chat

router = APIRouter(tags=["chat"])


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
            payload = json.loads(raw)
            question = payload.get("question", "")

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
