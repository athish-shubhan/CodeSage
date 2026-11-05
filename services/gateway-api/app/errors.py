"""Translates downstream failures (gRPC, HTTP to the LLM backend) into clean
502/503 responses instead of leaking a raw traceback to the client.

The client gets the category (which dependency, gRPC status, HTTP status,
timeout) and the server log gets the full error. gRPC details and httpx
messages carry internal addresses ("ipv4:10.42.7.19:50051", the LLM's
in-cluster URL) that a caller has no use for.
"""
from __future__ import annotations

import logging

import grpc
import httpx
from fastapi import HTTPException, status

from app.llm_client import MalformedLLMResponse

log = logging.getLogger("gateway-api")


def public_detail(exc: Exception) -> str:
    """What a client is told about a downstream failure."""
    if isinstance(exc, grpc.aio.AioRpcError):
        if exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
            # Our own validation message about the caller's request (repo_path), safe to return.
            return exc.details()
        return f"retrieval-service unavailable ({exc.code().name})"
    if isinstance(exc, MalformedLLMResponse):
        return "LLM backend unavailable (malformed response)"
    if isinstance(exc, httpx.TimeoutException):
        return "LLM backend unavailable (timed out)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"LLM backend unavailable (HTTP {exc.response.status_code})"
    if isinstance(exc, httpx.HTTPError):
        return f"LLM backend unavailable ({type(exc).__name__})"
    raise exc


def downstream_http_exception(exc: Exception) -> HTTPException:
    detail = public_detail(exc)
    log.warning("downstream failure: %s: %r", detail, exc)
    if isinstance(exc, grpc.aio.AioRpcError) and exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
        # The request itself was refused (a repo_path that is not a directory,
        # or outside INGEST_ALLOWED_ROOTS): the caller's to fix, not an outage.
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if isinstance(exc, grpc.aio.AioRpcError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
