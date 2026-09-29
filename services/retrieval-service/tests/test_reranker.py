import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reranker  # noqa: E402


def test_rerank_reorders_by_cross_encoder_score():
    chunks = [
        {"source_path": "a.py", "start_line": 1, "end_line": 5, "text": "irrelevant", "fusion_score": 0.9},
        {"source_path": "b.py", "start_line": 1, "end_line": 5, "text": "exact match", "fusion_score": 0.1},
    ]
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.1, 0.9]  # b.py should win after rerank

    with patch("reranker._get_model", return_value=fake_model):
        result = reranker.rerank("query", chunks, top_k=2)

    assert result[0]["source_path"] == "b.py"
    assert result[0]["fusion_score"] == 0.9


def test_rerank_respects_top_k():
    chunks = [{"source_path": f"{i}.py", "start_line": 1, "end_line": 1, "text": "x"} for i in range(5)]
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.5] * 5

    with patch("reranker._get_model", return_value=fake_model):
        result = reranker.rerank("query", chunks, top_k=2)

    assert len(result) == 2


def test_rerank_handles_empty_input():
    assert reranker.rerank("query", [], top_k=5) == []
