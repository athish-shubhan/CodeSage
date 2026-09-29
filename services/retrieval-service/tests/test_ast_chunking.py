import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chunking import chunk_file, window_chunks  # noqa: E402
from chunking_python import chunk_python_source  # noqa: E402


def test_splits_on_function_boundaries_not_line_count():
    source = (
        "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"
    )
    chunks = chunk_python_source(source, "m.py", window_chunks)

    assert len(chunks) == 2
    assert chunks[0].text.startswith("def foo")
    assert chunks[1].text.startswith("def bar")
    assert chunks[0].start_line == 1
    assert chunks[1].start_line == 5


def test_decorators_are_included_in_the_function_chunk():
    source = "@staticmethod\ndef foo():\n    return 1\n"
    chunks = chunk_python_source(source, "m.py", window_chunks)

    assert len(chunks) == 1
    assert chunks[0].text.startswith("@staticmethod")
    assert chunks[0].start_line == 1


def test_module_level_statements_merge_into_one_chunk():
    source = "import os\nimport sys\n\nX = 1\nY = 2\n"
    chunks = chunk_python_source(source, "m.py", window_chunks)

    assert len(chunks) == 1
    assert "import os" in chunks[0].text
    assert "Y = 2" in chunks[0].text


def test_oversized_function_falls_back_to_window_chunks():
    body = "\n".join(f"    x{i} = {i}" for i in range(200))
    source = f"def big():\n{body}\n"
    chunks = chunk_python_source(source, "m.py", window_chunks)

    assert len(chunks) > 1  # windowed, not one giant chunk


def test_syntax_error_returns_none_for_fallback():
    result = chunk_python_source("def broken(:\n", "m.py", window_chunks)
    assert result is None


def test_chunk_file_uses_ast_chunking_for_py_files(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def a():\n    pass\n\n\ndef b():\n    pass\n")

    chunks = chunk_file(str(f), "mod.py")

    assert len(chunks) == 2
    assert chunks[0].text == "def a():\n    pass"


def test_chunk_file_falls_back_for_invalid_python(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("this is not python(((\n" * 5)

    chunks = chunk_file(str(f), "broken.py")

    assert len(chunks) >= 1  # window fallback still produces something
