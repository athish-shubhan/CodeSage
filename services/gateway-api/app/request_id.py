"""One id per request, from the client's X-Request-ID or generated here,
carried through the gateway's logs, the audit log, every gRPC call to
retrieval-service (as `x-request-id` metadata, which it logs too), and back
to the client in the response header. One id then finds a request's lines in
every service's logs.
"""
from __future__ import annotations

import contextvars
import logging
import re
import uuid

HEADER = "x-request-id"
_VALID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def get() -> str | None:
    return _current.get()


def accept(candidate: str | None) -> str:
    """The client's id if it is a sane token (it ends up in log lines), else a new one."""
    return candidate if candidate and _VALID.fullmatch(candidate) else uuid.uuid4().hex


class RequestIdMiddleware:
    """Pure ASGI, so it covers WebSocket handshakes as well as HTTP, and the
    contextvar it sets is visible to the handler (same task)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        rid = accept(headers.get(HEADER.encode(), b"").decode("latin-1") or None)
        token = _current.set(rid)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (HEADER.encode(), rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _current.reset(token)


class RequestIdFilter(logging.Filter):
    """Adds %(request_id)s to every record ("-" outside a request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _current.get() or "-"
        return True


def configure_logging() -> None:
    """Gateway log lines carry the request id. Installs one handler on the
    "gateway-api" and "app" loggers; idempotent."""
    for name in ("gateway-api", "app"):
        logger = logging.getLogger(name)
        if any(isinstance(f, RequestIdFilter) for h in logger.handlers for f in h.filters):
            continue
        handler = logging.StreamHandler()
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
