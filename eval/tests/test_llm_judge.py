import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_judge import judge  # noqa: E402


def _fake_response(content: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_judge_parses_valid_json_verdict():
    with patch("httpx.post", return_value=_fake_response('{"score": 4, "reason": "mostly correct"}')):
        result = judge("q", "a")
    assert result == {"score": 4, "reason": "mostly correct"}


def test_judge_handles_non_json_response_gracefully():
    with patch("httpx.post", return_value=_fake_response("not json at all")):
        result = judge("q", "a")
    assert result["score"] is None
    assert "not json" in result["reason"]
