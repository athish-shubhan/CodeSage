"""Translates downstream failures (gRPC, HTTP to the LLM backend) into clean
502/503 responses instead of leaking a raw traceback to the client."""
from __future__ import annotations

import grpc
import httpx
from fastapi import HTTPException, status


def downstream_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, grpc.aio.AioRpcError) and exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
        # The request itself was refused (a repo_path that is not a directory,
        # or outside INGEST_ALLOWED_ROOTS): the caller's to fix, not an outage.
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.details())
    if isinstance(exc, grpc.aio.AioRpcError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"retrieval-service unavailable: {exc.details()}",
        )
    if isinstance(exc, httpx.HTTPError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM backend unavailable: {exc}",
        )
    raise exc
