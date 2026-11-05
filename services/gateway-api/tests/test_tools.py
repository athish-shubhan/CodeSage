import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import tools  # noqa: E402
from app.agent.citations import TRUNCATED_RE  # noqa: E402


def _get_file(rpc_result):
    with patch("app.rag_client.get_file", new=AsyncMock(return_value=rpc_result)):
        return asyncio.run(tools.get_file(tools.GetFileArgs(source_path="big.py")))


def test_truncated_read_says_where_it_was_cut():
    text = "".join(f"line {i}\n" for i in range(1, 1001))[:5000]
    out = _get_file({"text": text, "truncated": True})
    shown = text.count("\n") + 1
    assert out.startswith(text)
    assert out.endswith(f"(truncated after line {shown}; use expand_context to read further)")
    assert int(TRUNCATED_RE.search(out).group(1)) == shown


def test_complete_read_is_returned_unchanged():
    assert _get_file({"text": "a = 1\n", "truncated": False}) == "a = 1\n"
    assert _get_file(None) == "File not found: big.py"
