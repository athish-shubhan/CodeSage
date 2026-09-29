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
