import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_router import pick_model  # noqa: E402


def test_falls_back_to_single_model_when_no_fast_variant_configured():
    with patch("app.agent.model_router.settings") as mock_settings:
        mock_settings.llm_model_fast = ""
        mock_settings.llm_model = "capable-model"
        assert pick_model("short task") == "capable-model"


def test_routes_short_simple_task_to_fast_model():
    with patch("app.agent.model_router.settings") as mock_settings:
        mock_settings.llm_model_fast = "fast-model"
        mock_settings.llm_model = "capable-model"
        assert pick_model("what does auth.py do") == "fast-model"


def test_routes_long_task_to_capable_model():
    with patch("app.agent.model_router.settings") as mock_settings:
        mock_settings.llm_model_fast = "fast-model"
        mock_settings.llm_model = "capable-model"
        long_task = "why " * 40
        assert pick_model(long_task) == "capable-model"


def test_routes_multi_question_task_to_capable_model():
    with patch("app.agent.model_router.settings") as mock_settings:
        mock_settings.llm_model_fast = "fast-model"
        mock_settings.llm_model = "capable-model"
        assert pick_model("what does auth do? and why is it here?") == "capable-model"
