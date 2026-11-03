import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from run_eval import recall_at_k, reciprocal_rank, unanswerable_is_clean  # noqa: E402


def test_recall_at_k_hit():
    assert recall_at_k(["a.py", "b.py"], ["b.py"]) == 1.0


def test_recall_at_k_miss():
    assert recall_at_k(["a.py", "c.py"], ["b.py"]) == 0.0


def test_recall_at_k_none_for_unanswerable():
    assert recall_at_k(["a.py"], []) is None


def test_reciprocal_rank_position():
    assert reciprocal_rank(["a.py", "b.py", "c.py"], ["c.py"]) == 1 / 3


def test_reciprocal_rank_not_found():
    assert reciprocal_rank(["a.py"], ["b.py"]) == 0.0


def test_unanswerable_clean_when_empty():
    assert unanswerable_is_clean([]) is True
    assert unanswerable_is_clean(["a.py"]) is False


def test_bootstrap_ci_brackets_the_mean_and_is_reproducible():
    from run_eval import bootstrap_ci

    values = [1.0] * 14 + [0.0] * 6
    lo, hi = bootstrap_ci(values)
    assert lo < 0.7 < hi
    assert bootstrap_ci(values) == (lo, hi)
    assert bootstrap_ci([1.0] * 5) == (1.0, 1.0)


def test_abstention_sweep_trades_unanswerable_catch_rate_for_recall():
    from abstention import sweep

    per_q = [
        {"category": "semantic", "recall": 1.0, "top_dense_score": 0.6},
        {"category": "semantic", "recall": 1.0, "top_dense_score": 0.3},
        {"category": "unanswerable", "recall": None, "top_dense_score": 0.2},
    ]
    off, mid, high = sweep(per_q, [0.0, 0.25, 0.5])
    assert (off["unanswerable_abstained"], off["recall_at_k"]) == (0.0, 1.0)
    assert (mid["unanswerable_abstained"], mid["answerable_abstained"], mid["recall_at_k"]) == (1.0, 0.0, 1.0)
    assert (high["answerable_abstained"], high["recall_at_k"]) == (0.5, 0.5)


def test_ablation_rewrite_keeps_the_agent_reliability_section(tmp_path, monkeypatch):
    import ablation

    report = tmp_path / "report.md"
    report.write_text("# old table\n\n<!-- agent-reliability:start -->\nagent\n<!-- agent-reliability:end -->\n")
    row = {"label": "dense only", "recall_at_k": 0.5, "recall_ci95": (0.1, 0.9), "mrr": 0.4,
           "p50_latency_ms": 1, "p95_latency_ms": 2, "avg_context_tokens": 3, "n": 2}
    monkeypatch.setattr(ablation, "run", lambda *a, **k: row)
    monkeypatch.setattr(sys, "argv", ["ablation.py", "--report", str(report)])
    ablation.main()
    text = report.read_text()
    assert "# old table" not in text and "# CodeSage retrieval ablation report" in text
    assert text.endswith("\n<!-- agent-reliability:start -->\nagent\n<!-- agent-reliability:end -->\n")
