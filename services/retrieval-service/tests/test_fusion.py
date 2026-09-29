import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fusion import assemble_context, dedupe_overlapping, reciprocal_rank_fusion  # noqa: E402


def _chunk(path, start, end, text="x"):
    return {"source_path": path, "start_line": start, "end_line": end, "text": text}


def test_fusion_favors_item_ranked_high_in_both_lists():
    shared = _chunk("a.py", 1, 10)
    dense_only = _chunk("b.py", 1, 10)
    lexical_only = _chunk("c.py", 1, 10)

    fused = reciprocal_rank_fusion(
        dense=[shared, dense_only], lexical=[shared, lexical_only], lex_weight=0.5
    )

    assert fused[0]["source_path"] == "a.py"


def test_lex_weight_zero_ignores_lexical_only_hits():
    dense_only = _chunk("a.py", 1, 10)
    lexical_only = _chunk("b.py", 1, 10)

    fused = reciprocal_rank_fusion(dense=[dense_only], lexical=[lexical_only], lex_weight=0.0)

    assert fused[0]["source_path"] == "a.py"
    assert fused[0]["fusion_score"] > 0
    lexical_score = next(c["fusion_score"] for c in fused if c["source_path"] == "b.py")
    assert lexical_score == 0.0


def test_dedupe_drops_chunk_contained_within_a_kept_one():
    outer = _chunk("a.py", 1, 100)
    inner = _chunk("a.py", 10, 20)
    other_file = _chunk("b.py", 10, 20)

    result = dedupe_overlapping([outer, inner, other_file])

    assert result == [outer, other_file]


def test_assemble_context_stops_before_exceeding_budget():
    chunks = [_chunk("a.py", 1, 1, text="x" * 400) for _ in range(5)]  # ~100 tokens each

    selected, total = assemble_context(chunks, max_tokens=250)

    assert len(selected) == 2  # 100 + 100 fits, +100 more would exceed 250
    assert total <= 250


def test_assemble_context_always_includes_at_least_one_chunk():
    huge = _chunk("a.py", 1, 1, text="x" * 10_000)

    selected, total = assemble_context([huge], max_tokens=10)

    assert len(selected) == 1  # never drop to zero chunks just from budget
