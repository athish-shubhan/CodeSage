import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.citations import check, extract  # noqa: E402
from app.agent.state import ToolCallRecord  # noqa: E402


def test_extract_parses_ranges_and_single_lines():
    assert extract("see [a/b.py:3-9] and [c.yml:4]") == [("a/b.py", 3, 9), ("c.yml", 4, 4)]


def test_search_hit_grounds_only_overlapping_lines():
    calls = [ToolCallRecord("search_code", {"query": "x"}, "[a.py:10-20]\ncode")]
    assert check("[a.py:15-25] [a.py:30-40]", calls) == {"grounded": ["a.py:15-25"], "ungrounded": ["a.py:30-40"]}


def test_expand_context_window_includes_padding():
    args = {"source_path": "a.py", "start_line": 50, "end_line": 60, "extra_lines": 10}
    calls = [ToolCallRecord("expand_context", args, "...text...")]
    assert check("[a.py:41-45]", calls)["grounded"] == ["a.py:41-45"]
    assert check("[a.py:20-30]", calls)["ungrounded"] == ["a.py:20-30"]


def test_get_file_grounds_whole_file_but_not_a_failed_read():
    ok = [ToolCallRecord("get_file", {"source_path": "a.py"}, "contents")]
    missing = [ToolCallRecord("get_file", {"source_path": "a.py"}, "File not found: a.py")]
    assert check("[a.py:900-910]", ok)["grounded"] == ["a.py:900-910"]
    assert check("[a.py:1-2]", missing)["ungrounded"] == ["a.py:1-2"]


def test_answer_without_citations_is_empty_not_an_error():
    assert check("no citations here", []) == {"grounded": [], "ungrounded": []}
