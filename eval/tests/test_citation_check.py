import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from citation_check import check_faithfulness, extract_citations  # noqa: E402

RETRIEVED = [
    {"source_path": "app/auth.py", "start_line": 1, "end_line": 20},
    {"source_path": "app/config.py", "start_line": 5, "end_line": 15},
]


def test_extract_citations_parses_path_and_range():
    answer = "See [app/auth.py:1-20] for the login check."
    assert extract_citations(answer) == [("app/auth.py", 1, 20)]


def test_extract_citations_handles_single_line():
    assert extract_citations("defined at app/config.py:5") == [("app/config.py", 5, 5)]


def test_faithful_when_all_citations_in_retrieved_files():
    answer = "Auth is in [app/auth.py:1-20] and config in [app/config.py:5-15]."
    result = check_faithfulness(answer, RETRIEVED)
    assert result["faithful"] is True
    assert result["unfaithful_citations"] == []


def test_unfaithful_when_citing_a_file_never_retrieved():
    answer = "See [app/nonexistent.py:1-5] for details."
    result = check_faithfulness(answer, RETRIEVED)
    assert result["faithful"] is False
    assert result["unfaithful_citations"] == ["app/nonexistent.py:1-5"]


def test_no_citations_returns_none_faithful():
    result = check_faithfulness("This is a plain answer with no citations.", RETRIEVED)
    assert result["faithful"] is None
    assert result["citations_found"] == 0
