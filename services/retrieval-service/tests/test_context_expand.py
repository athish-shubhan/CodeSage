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


def _repo_with_links(tmp_path):
    repo, outside = tmp_path / "repo", tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET_KEY=hunter2\n")
    (repo / "ok.py").write_text("def ok():\n    pass\n")
    (repo / "leak.md").symlink_to(outside / "secret.txt")
    (repo / "linkdir").symlink_to(outside, target_is_directory=True)
    (repo / "alias.py").symlink_to(repo / "ok.py")  # a link that stays inside the repo
    return repo


def test_symlinks_out_of_the_repo_are_refused(tmp_path):
    repo = _repo_with_links(tmp_path)
    context_expand.set_repo_root("links", str(repo))

    assert context_expand.read_file("links", "leak.md") is None
    assert context_expand.read_file("links", "linkdir/secret.txt") is None
    assert context_expand.expand("links", "leak.md", 1, 1) is None
    assert context_expand.read_file("links", "alias.py")["text"].startswith("def ok")
    assert context_expand.read_file("links", "ok.py")["text"].startswith("def ok")


def test_repo_root_that_is_itself_a_symlink_still_works(tmp_path):
    repo = _repo_with_links(tmp_path)
    (tmp_path / "root-link").symlink_to(repo, target_is_directory=True)
    context_expand.set_repo_root("rootlink", str(tmp_path / "root-link"))

    assert context_expand.read_file("rootlink", "ok.py")["text"].startswith("def ok")
    assert context_expand.read_file("rootlink", "leak.md") is None


def test_files_that_ingest_would_not_index_cannot_be_read_back(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=secret\n")
    (tmp_path / "key.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.toml").write_text("x = 1\n")
    (tmp_path / "ok.py").write_text("x = 1\n")
    context_expand.set_repo_root("noindex", str(tmp_path))
    for rel in (".env", "key.pem", ".git/config.toml"):
        assert context_expand.read_file("noindex", rel) is None
        assert context_expand.expand("noindex", rel, 1, 1) is None
    assert context_expand.read_file("noindex", "ok.py")["text"] == "x = 1\n"
