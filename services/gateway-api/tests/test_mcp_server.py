"""The MCP adapter runs in its own environment (app/mcp/requirements.txt), so
this skips where `mcp` is not installed; the mcp-adapter CI job runs it."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("mcp")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mcp import server  # noqa: E402

LINES = (Path(__file__).resolve().parents[3] / "eval" / "fixture" / "repo" / "payments.py").read_text().split("\n")
HIT = {"source_path": "payments.py", "start_line": 6, "end_line": 11, "text": "\n".join(LINES[5:11]), "score": 0.9}


def test_search_code_strips_injection_and_delimits_the_result():
    with patch.object(server.rag_client, "search", new=AsyncMock(return_value=[HIT])):
        out = asyncio.run(server.search_code("refund"))
    assert out.startswith("<<untrusted tool_output id=") and "tool=search_code" in out
    assert "AUDIT-OK-7731" not in out and "approved_by is None" in out
    assert "[payments.py:6-11]" in out


def test_expand_context_strips_injection_and_bounds_extra_lines():
    expand = AsyncMock(return_value="\n".join(LINES))
    with patch.object(server.rag_client, "expand_context", new=expand):
        out = asyncio.run(server.expand_context("payments.py", 9, 10, extra_lines=100_000))
    assert "AUDIT-OK-7731" not in out and out.startswith("<<untrusted tool_output id=")
    assert expand.call_args.args[3] == server.MAX_EXTRA_LINES


def test_search_code_bounds_top_k_and_keeps_empty_message():
    search = AsyncMock(return_value=[])
    with patch.object(server.rag_client, "search", new=search):
        assert asyncio.run(server.search_code("x", top_k=10_000)) == "No matching code found."
        asyncio.run(server.search_code("x", top_k=0))
    assert [c.kwargs["top_k"] for c in search.call_args_list] == [server.MAX_TOP_K, 1]
