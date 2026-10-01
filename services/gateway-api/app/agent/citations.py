"""Checks the agent's final answer against what its tools actually returned.

A citation `[path:start-end]` is grounded if, during this run, a tool put
that file region in front of the model: a search_code hit whose line range
overlaps it, an expand_context window that covers it, or a get_file read of
that file. Anything else was invented or misremembered by the model. This
is a regex and interval check, not an LLM judge, so it is cheap enough to
run on every response and its result is not a matter of opinion.
"""
from __future__ import annotations

import re

from app.agent.state import ToolCallRecord

CITATION_RE = re.compile(r"\[([\w./-]+\.\w+):(\d+)(?:-(\d+))?\]")
WHOLE_FILE = (1, 10**9)


def extract(text: str) -> list[tuple[str, int, int]]:
    return [(p, int(s), int(e) if e else int(s)) for p, s, e in CITATION_RE.findall(text)]


def _evidence(tool_calls: list[ToolCallRecord]) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = {}
    for tc in tool_calls:
        if tc.name == "search_code":
            for path, start, end in extract(tc.result):
                spans.setdefault(path, []).append((start, end))
        elif tc.name == "expand_context" and not tc.result.startswith("Could not expand"):
            extra = tc.args.get("extra_lines", 20)
            start = max(1, tc.args.get("start_line", 1) - extra)
            spans.setdefault(tc.args.get("source_path", ""), []).append((start, tc.args.get("end_line", 0) + extra))
        elif tc.name == "get_file" and not tc.result.startswith("File not found"):
            spans.setdefault(tc.args.get("source_path", ""), []).append(WHOLE_FILE)
    return spans


def check(answer: str, tool_calls: list[ToolCallRecord]) -> dict:
    """Returns {"grounded": [...], "ungrounded": [...]} as "path:start-end" strings."""
    evidence = _evidence(tool_calls)
    grounded, ungrounded = [], []
    for path, start, end in extract(answer):
        ok = any(s <= end and start <= e for s, e in evidence.get(path, []))
        (grounded if ok else ungrounded).append(f"{path}:{start}-{end}")
    return {"grounded": grounded, "ungrounded": ungrounded}
