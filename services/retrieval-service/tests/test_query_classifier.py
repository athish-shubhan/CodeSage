import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from query_classifier import lexical_weight  # noqa: E402


def test_identifier_heavy_query_gets_high_lexical_weight():
    w = lexical_weight("what does GATEWAY_LLM_BASE_URL configure in llm_client.py?")
    assert w > 0.5


def test_natural_language_query_gets_low_lexical_weight():
    w = lexical_weight("why does the gateway handle websocket errors differently")
    assert w <= 0.3


def test_weight_is_bounded():
    w = lexical_weight("GATEWAY_LLM_BASE_URL config.py AioRpcError \"exact phrase\" dotted.path")
    assert 0.0 <= w <= 0.8
