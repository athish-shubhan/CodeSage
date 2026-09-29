"""Hierarchical context recovery: given a retrieved chunk, pull more
surrounding lines from its source file, rather than tracking a full
repo/module/class tree. A chunk already carries source_path/start_line/
end_line; expansion just re-reads that region of the file with padding.
Deliberately shallow; see docs/architecture.md for why a full hierarchy
wasn't built.
"""
from __future__ import annotations

import os

_repo_roots: dict[str, str] = {}


def set_repo_root(collection: str, repo_path: str) -> None:
    _repo_roots[collection] = repo_path


def expand(collection: str, source_path: str, start_line: int, end_line: int, extra_lines: int = 20) -> str | None:
    """Returns the widened text block, or None if the repo root/file is
    unknown or source_path would escape the repo root."""
    root = _repo_roots.get(collection)
    if not root:
        return None

    full = os.path.normpath(os.path.join(root, source_path))
    if not full.startswith(os.path.normpath(root) + os.sep):
        return None

    try:
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return None

    lo = max(0, start_line - 1 - extra_lines)
    hi = min(len(lines), end_line + extra_lines)
    return "".join(lines[lo:hi])


def read_file(collection: str, source_path: str, max_bytes: int = 20_000) -> dict | None:
    """Whole-file read for the agent's get_file tool, bounded so a request
    for a huge file can't blow the LLM's context budget. Returns None if
    the repo root/file is unknown or source_path escapes the repo root."""
    root = _repo_roots.get(collection)
    if not root:
        return None

    full = os.path.normpath(os.path.join(root, source_path))
    if not full.startswith(os.path.normpath(root) + os.sep):
        return None

    try:
        with open(full, "rb") as f:
            data = f.read(max_bytes + 1)
    except OSError:
        return None

    truncated = len(data) > max_bytes
    return {"text": data[:max_bytes].decode("utf-8", errors="ignore"), "truncated": truncated}
