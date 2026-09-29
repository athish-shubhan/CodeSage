import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import context_expand  # noqa: E402


def _write(tmp_path, rel, n_lines):
    f = tmp_path / rel
    f.write_text("\n".join(f"line {i}" for i in range(1, n_lines + 1)) + "\n")
    return f


def test_expand_pads_before_and_after(tmp_path):
    _write(tmp_path, "mod.py", 100)
    context_expand.set_repo_root("t1", str(tmp_path))

    text = context_expand.expand("t1", "mod.py", start_line=50, end_line=55, extra_lines=5)

    lines = text.splitlines()
    assert lines[0] == "line 45"
    assert lines[-1] == "line 60"


def test_expand_clamps_at_file_boundaries(tmp_path):
    _write(tmp_path, "mod.py", 10)
    context_expand.set_repo_root("t2", str(tmp_path))

    text = context_expand.expand("t2", "mod.py", start_line=1, end_line=10, extra_lines=20)

    lines = text.splitlines()
    assert lines[0] == "line 1"
    assert lines[-1] == "line 10"


def test_expand_returns_none_for_unknown_collection():
    assert context_expand.expand("nonexistent", "mod.py", 1, 5) is None


def test_expand_rejects_path_traversal(tmp_path):
    context_expand.set_repo_root("t3", str(tmp_path))
    assert context_expand.expand("t3", "../../etc/passwd", 1, 5) is None


def test_read_file_returns_full_content(tmp_path):
    _write(tmp_path, "mod.py", 5)
    context_expand.set_repo_root("t4", str(tmp_path))

    result = context_expand.read_file("t4", "mod.py")

    assert result["truncated"] is False
    assert result["text"].splitlines()[0] == "line 1"


def test_read_file_truncates_at_max_bytes(tmp_path):
    (tmp_path / "big.py").write_text("x" * 1000)
    context_expand.set_repo_root("t5", str(tmp_path))

    result = context_expand.read_file("t5", "big.py", max_bytes=100)

    assert result["truncated"] is True
    assert len(result["text"]) == 100


def test_read_file_rejects_path_traversal(tmp_path):
    context_expand.set_repo_root("t6", str(tmp_path))
    assert context_expand.read_file("t6", "../../etc/passwd") is None
