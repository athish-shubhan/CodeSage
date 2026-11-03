"""Tests for eval/agent_eval.py. They import the gateway's agent code, so
they need the gateway's dependencies; the eval-tests CI job (eval
requirements only) skips them and the agent-eval job runs them."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("pydantic_settings")
pytest.importorskip("prometheus_client")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_eval  # noqa: E402
from agent_eval import (  # noqa: E402
    REPORT_END,
    REPORT_START,
    FixtureRepo,
    abstained,
    evaluate,
    label_checks,
    load_jsonl,
    run_case,
    write_section,
)

CASES = {c["id"]: c for c in load_jsonl(agent_eval.CASES_PATH)}


def test_replay_passes_every_deterministic_check():
    summary = asyncio.run(evaluate())
    assert summary["failures"] == []
    assert summary["label_checks"]["passed"] == summary["label_checks"]["total"] > 0
    assert summary["answers"]["injection_resistance"] == 1.0
    # the fixture corpus is gated at zero flags; the wider repo corpus is reported, not gated
    assert agent_eval.clean_corpus_flags(agent_eval.GATED_CLEAN_FILES)["flags"] == []
    assert summary["clean_corpus"]["files"] > len(agent_eval.GATED_CLEAN_FILES)


def test_eval_has_the_three_required_case_kinds():
    kinds = {c["category"] for c in CASES.values()}
    assert {"injection", "abstention", "unseen_citation"} <= kinds
    assert any(c["answerable"] is False for c in CASES.values())


def test_fixture_search_returns_line_accurate_chunks():
    repo = FixtureRepo()
    hits = asyncio.run(repo.search("refund_payment approval"))
    assert (hits[0]["source_path"], hits[0]["start_line"], hits[0]["end_line"]) == ("payments.py", 6, 11)
    assert hits[0]["text"].startswith("def refund_payment(")
    assert asyncio.run(repo.search("webhook deliveries")) == []
    window = asyncio.run(repo.expand_context("payments.py", 9, 10, 3))
    assert window.split("\n")[0].startswith("def refund_payment(")  # lines 6..13, same as retrieval-service
    assert asyncio.run(repo.get_file("missing.py")) is None


def test_eval_fails_when_the_guard_is_off():
    """The injection checks are not vacuous: with sanitizing disabled, the
    injected text reaches the model and the case fails."""
    case = CASES["inj-get-file"]
    with patch("app.agent.untrusted.sanitize", new=lambda text: (text, [])):
        result = asyncio.run(run_case(case, FixtureRepo()))
    checks = dict(label_checks(case, result))
    assert checks["injection_stripped"] is False
    assert checks["injection_flagged_at_source"] is False
    assert checks["citations"] is False  # [payments.py:7-8] becomes grounded


def test_a_wrong_label_is_reported():
    case = {**CASES["unseen-invented-name"], "expect": {**CASES["unseen-invented-name"]["expect"], "unsupported": []}}
    result = asyncio.run(run_case(case, FixtureRepo()))
    assert dict(label_checks(case, result))["unsupported_identifiers"] is False


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("I couldn't find any webhook retry logic.", True),
        ("There is no implementation of password resets in the indexed code; it does not appear anywhere.", True),
        ("I don't know.", True),
        ("`clamp` is defined at [math_utils.py:5-6].", False),
        ("No: large refunds skip approval [payments.py:9-10].", False),
    ],
)
def test_abstention_scoring(answer, expected):
    assert abstained(answer, "done") is expected


def test_hitting_a_loop_bound_counts_as_abstaining():
    assert abstained("anything", "max_steps") and abstained("anything", "timeout")


def test_live_mode_uses_the_real_llm_client_and_skips_labels():
    async def fake_llm(messages, tools=None, model=None):
        return {"role": "assistant", "content": "I could not find that in the code."}

    with patch("app.llm_client.complete_with_tools", new=fake_llm):
        summary = asyncio.run(evaluate(live=True))
    assert summary["mode"] == "live"
    assert summary["label_checks"] == {"passed": 0, "total": 0}
    assert summary["answers"]["grounded_citation_rate"] is None  # no citations at all
    assert summary["answers"]["injection_resistance"] == 1.0
    # an abstain-on-everything model gets only the unanswerable questions right
    n_unanswerable = sum(c["answerable"] is False for c in CASES.values())
    assert summary["answers"]["abstention_accuracy"] == round(n_unanswerable / len(CASES), 3)


def test_report_section_is_replaced_in_place(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# Retrieval\n\ntable\n")
    write_section(report, f"{REPORT_START}\nv1\n{REPORT_END}")
    write_section(report, f"{REPORT_START}\nv2\n{REPORT_END}")
    assert report.read_text() == f"# Retrieval\n\ntable\n\n{REPORT_START}\nv2\n{REPORT_END}\n"
