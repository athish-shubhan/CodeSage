import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm_client import build_prompt  # noqa: E402


def test_build_prompt_includes_citations_for_each_chunk():
    chunks = [
        {"source_path": "app/main.py", "start_line": 10, "end_line": 20, "text": "def foo(): ..."},
        {"source_path": "app/auth.py", "start_line": 1, "end_line": 5, "text": "import jwt"},
    ]

    prompt = build_prompt("How does auth work?", chunks)

    assert "app/main.py:10-20" in prompt
    assert "app/auth.py:1-5" in prompt
    assert "How does auth work?" in prompt


def test_build_prompt_handles_no_context_gracefully():
    prompt = build_prompt("What is this?", [])

    assert "no matching context found" in prompt
    assert "What is this?" in prompt
