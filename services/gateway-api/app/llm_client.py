"""Streaming client for a local LLM server.

Deliberately written against the OpenAI-compatible `/v1/chat/completions`
API rather than any one server's native API, because Ollama, vLLM, and
llama.cpp's `llama-server` all implement it. That means this one client
serves all three backends; swapping between them is
`GATEWAY_LLM_BASE_URL` + `GATEWAY_LLM_MODEL`, not a code change:

    Ollama:    GATEWAY_LLM_BASE_URL=http://ollama:11434/v1
    vLLM:      GATEWAY_LLM_BASE_URL=http://vllm:8000/v1
    llama.cpp: GATEWAY_LLM_BASE_URL=http://llamacpp:8080/v1

See docker-compose.vllm.yml / docker-compose.llamacpp.yml for runnable
overrides of each, and docs/architecture.md for the tradeoffs between them.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings

SYSTEM_PROMPT = (
    "You are CodeSage, a coding assistant. Use the retrieved code context below "
    "to answer the user's question precisely, citing file paths and line numbers "
    "when you rely on them. If the context does not contain the answer, say so."
)


def build_prompt(question: str, context_chunks: list[dict]) -> str:
    if not context_chunks:
        context = "(no matching context found)"
    else:
        context = "\n\n".join(
            f"[{c['source_path']}:{c['start_line']}-{c['end_line']}]\n{c['text']}" for c in context_chunks
        )
    return f"# Retrieved context\n{context}\n\n# Question\n{question}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.llm_api_key}"}


async def stream_chat(user_prompt: str) -> AsyncIterator[str]:
    payload = {
        "model": settings.llm_model,
        "stream": True,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    url = f"{settings.llm_base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload, headers=_headers()) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ").strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if token := delta.get("content"):
                    yield token


async def complete_with_tools(messages: list[dict], tools: list[dict] | None = None, model: str | None = None) -> dict:
    """Non-streaming completion, optionally with tool definitions. Returns
    the raw `message` object (may carry `content` and/or `tool_calls`).

    The agent loop needs the whole tool-call list before it can act, so this
    is deliberately non-streaming, unlike `stream_chat`, which is for the
    plain /chat path where partial tokens are useful to the caller."""
    payload = {"model": model or settings.llm_model, "stream": False, "messages": messages}
    if tools:
        payload["tools"] = tools
    url = f"{settings.llm_base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


async def health() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.llm_base_url}/models", headers=_headers())
            return resp.status_code == 200
    except httpx.HTTPError:
        return False
