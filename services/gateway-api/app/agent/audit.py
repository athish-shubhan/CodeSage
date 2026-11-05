"""Append-only audit log for /agent runs: one JSON line per run, written to
GATEWAY_AGENT_AUDIT_LOG. Off by default (empty path).

What a line holds is enough to answer "what did the agent do, and was its
answer backed by anything" after the fact: the model, every tool call with
its arguments, why the run stopped, its citation verdicts, and what the
injection guard removed. The task itself is stored as a SHA-256, not as
text, so the log can be kept without keeping users' questions verbatim. Tool
arguments (search queries) are stored as-is and can echo the task; treat the
file as sensitive.

Writing fails open: a full disk or bad path is logged and counted
(agent_audit_write_failures_total) but does not fail the request.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone

from app.agent.state import AgentState
from app.config import settings
from app.metrics import AGENT_AUDIT_WRITE_FAILURES

logger = logging.getLogger(__name__)
_lock = threading.Lock()  # one writer at a time, so concurrent runs never interleave a line


def entry(state: AgentState, model: str, duration_s: float, error: str | None = None) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "request_id": state.request_id,
        "task_sha256": hashlib.sha256(state.task.encode("utf-8")).hexdigest(),
        "model": model,
        "steps": state.steps,
        "stopped_reason": "error" if error else state.stopped_reason,
        "error": error,
        "duration_ms": round(duration_s * 1000, 1),
        "tool_calls": [{"name": tc.name, "args": tc.args} for tc in state.tool_calls],
        "citations": {
            "grounded": state.citations.get("grounded", []),
            "ungrounded": state.citations.get("ungrounded", []),
            "unsupported_identifiers": state.unsupported_identifiers,
        },
        "injection_flags": [asdict(f) for f in state.injection_flags],
        "repairs": state.repairs,
    }


def _append(path: str, line: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with _lock, open(path, "a", encoding="utf-8") as f:
        f.write(line)


async def record(state: AgentState, model: str, duration_s: float, error: str | None = None) -> None:
    path = settings.agent_audit_log
    if not path:
        return
    line = json.dumps(entry(state, model, duration_s, error), ensure_ascii=False, sort_keys=True) + "\n"
    try:
        await asyncio.to_thread(_append, path, line)
    except Exception:  # never fail the request over the audit trail
        AGENT_AUDIT_WRITE_FAILURES.inc()
        logger.warning("could not write agent audit log to %s", path, exc_info=True)
