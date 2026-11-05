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


# --- citations to removed (instruction-like) text -----------------------

from app.agent.citations import removed_lines, unsupported_identifiers  # noqa: E402
from app.agent.state import InjectionFlag  # noqa: E402


def test_citation_pointing_only_at_removed_lines_is_ungrounded():
    calls = [ToolCallRecord("get_file", {"source_path": "p.py"}, "contents")]
    removed = removed_lines([InjectionFlag("get_file", "ignore_instructions", "...", "p.py", 7, 8)])
    assert removed == {"p.py": {7, 8}}
    result = check("[p.py:7-8] [p.py:8] [p.py:6-9]", calls, removed)
    assert result == {"grounded": ["p.py:6-9"], "ungrounded": ["p.py:7-8", "p.py:8-8"]}


def test_removed_lines_of_another_file_do_not_matter():
    calls = [ToolCallRecord("search_code", {"query": "x"}, "[a.py:1-10]\ncode")]
    assert check("[a.py:3-4]", calls, {"b.py": {3, 4}})["grounded"] == ["a.py:3-4"]


def test_huge_cited_range_over_whole_file_read_is_cheap():
    calls = [ToolCallRecord("get_file", {"source_path": "a.py"}, "x")]
    assert check("[a.py:1-999999999]", calls, {"a.py": {1, 2}})["grounded"] == ["a.py:1-999999999"]


# --- identifiers attributed to a citation -------------------------------

AUTH_HIT = ToolCallRecord(
    "search_code",
    {"query": "auth"},
    '[auth.py:5-10]\nWIDGET_API_TOKEN_HEADER = "X-Widget-Api-Token"\n\n\n'
    "def authenticate_widget_request(token: str) -> bool:\n"
    '    return token == "widget-secret-token"\n',
)


def test_identifiers_present_in_cited_text_are_supported():
    answer = (
        "`authenticate_widget_request()` compares the token [auth.py:8-9]. "
        'The header name is `"X-Widget-Api-Token"`, stored in WIDGET_API_TOKEN_HEADER [auth.py:5].'
    )
    assert unsupported_identifiers(answer, [AUTH_HIT]) == []


def test_identifier_missing_from_cited_text_is_reported():
    answer = "Tokens are checked by `verify_token` in [auth.py:8-9]."
    assert unsupported_identifiers(answer, [AUTH_HIT]) == [
        {"identifier": "verify_token", "citations": ["auth.py:8-9"]}
    ]


def test_identifier_must_be_in_the_cited_range_not_anywhere_in_the_run():
    long_file = ToolCallRecord("get_file", {"source_path": "m.py"}, "\n".join(["def clamp(): ..."] + [""] * 30 + ["def lerp(): ..."]))
    assert unsupported_identifiers("`lerp` is at [m.py:1-2].", [long_file]) == [
        {"identifier": "lerp", "citations": ["m.py:1-2"]}
    ]
    assert unsupported_identifiers("`lerp` is at [m.py:32].", [long_file]) == []


def test_trailing_citation_sentence_attaches_to_the_previous_sentence():
    answer = "The check lives in `authenticate_widget_request`. [auth.py:8-9]"
    assert unsupported_identifiers(answer, [AUTH_HIT]) == []
    answer = "The check lives in `check_token`. [auth.py:8-9]"
    assert [u["identifier"] for u in unsupported_identifiers(answer, [AUTH_HIT])] == ["check_token"]


def test_prose_names_paths_and_dotted_names_are_checked():
    answer = (
        "The class AgentState and helper load_config() and module helpers.py and "
        "`app.auth.authenticate_widget_request` are in [auth.py:5-10]."
    )
    found = [u["identifier"] for u in unsupported_identifiers(answer, [AUTH_HIT])]
    assert found == ["helpers.py", "load_config", "AgentState"]


def test_cited_file_path_itself_is_supported_and_prose_words_are_ignored():
    answer = "auth.py handles this, as the README.md notes; it is simple and safe [auth.py:5-10]."
    assert [u["identifier"] for u in unsupported_identifiers(answer, [AUTH_HIT])] == ["README.md"]


def test_identifiers_with_only_ungrounded_citations_are_unsupported():
    answer = "`normalize_vector` is defined in [vector_ops.py:1-8]."
    assert unsupported_identifiers(answer, [AUTH_HIT]) == [
        {"identifier": "normalize_vector", "citations": ["vector_ops.py:1-8"]}
    ]


def test_name_only_in_removed_text_is_unsupported():
    sanitized = ToolCallRecord(
        "get_file", {"source_path": "p.py"}, "def pay():\n    [removed: instruction-like text]\n    return 1"
    )
    assert [u["identifier"] for u in unsupported_identifiers("`AUDIT_OK` is returned [p.py:1-3].", [sanitized])] == [
        "AUDIT_OK"
    ]


def test_sentences_without_citations_are_not_checked():
    assert unsupported_identifiers("`made_up_name` exists somewhere.", [AUTH_HIT]) == []


def test_function_name_is_backed_by_the_def_line_enclosing_the_cited_body():
    source = "class Pay:\n    def refund(self, amount):\n" + "        x = 1\n" * 10 + "        return amount > 0\n"
    calls = [ToolCallRecord("get_file", {"source_path": "p.py"}, source)]
    assert unsupported_identifiers("`Pay.refund` returns a bool [p.py:13].", calls) == []
    assert [u["identifier"] for u in unsupported_identifiers("`charge` returns a bool [p.py:13].", calls)] == ["charge"]
