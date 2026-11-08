import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chunking import chunk_file, chunk_repo, iter_source_files  # noqa: E402


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return full


def test_chunk_file_covers_all_lines_with_overlap(tmp_path):
    content = "\n".join(f"line {i}" for i in range(1, 201))  # 200 lines
    full = _write(tmp_path, "big.py", content)

    chunks = chunk_file(str(full), "big.py")

    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 200
    # consecutive chunks overlap rather than leaving a gap
    for a, b in zip(chunks, chunks[1:]):
        assert b.start_line <= a.end_line


def test_chunk_file_skips_unreadable_path():
    assert chunk_file("/no/such/file.py", "file.py") == []


def test_iter_source_files_skips_ignored_dirs_and_extensions(tmp_path):
    _write(tmp_path, "src/main.py", "print(1)")
    _write(tmp_path, "src/notes.txt", "not indexed")
    _write(tmp_path, "node_modules/pkg/index.js", "skip me")
    _write(tmp_path, ".git/HEAD", "skip me too")

    found = {rel for _, rel in iter_source_files(str(tmp_path))}

    assert "src/main.py" in found
    assert "src/notes.txt" not in found
    assert not any("node_modules" in f for f in found)
    assert not any(f.startswith(".git") for f in found)


def test_iter_source_files_respects_include_globs(tmp_path):
    _write(tmp_path, "src/main.py", "print(1)")
    _write(tmp_path, "docs/readme.md", "# hi")

    found = {rel for _, rel in iter_source_files(str(tmp_path), include_globs=["src/*.py"])}

    assert found == {"src/main.py"}


def test_chunk_repo_counts_files_and_chunks(tmp_path):
    _write(tmp_path, "a.py", "x = 1\n" * 5)
    _write(tmp_path, "b.py", "y = 2\n" * 5)

    chunks, files_seen = chunk_repo(str(tmp_path))

    assert files_seen == 2
    assert len(chunks) == 2  # each small file fits in a single chunk


def test_ingest_scan_skips_symlinks_that_leave_the_repo(tmp_path):
    from chunking import iter_source_files

    repo, outside = tmp_path / "repo", tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET_KEY=hunter2\n")
    (outside / "lib.py").write_text("x = 1\n")
    (repo / "ok.py").write_text("y = 2\n")
    (repo / "leak.md").symlink_to(outside / "secret.txt")
    (repo / "linkdir").symlink_to(outside, target_is_directory=True)
    (repo / "alias.py").symlink_to(repo / "ok.py")

    assert sorted(rel for _, rel in iter_source_files(str(repo))) == ["alias.py", "ok.py"]


def test_chunk_start_line_names_its_first_non_blank_line():
    from chunking import window_chunks

    lines = ["\n", "\n", "first = 1\n", "second = 2\n", "\n"]
    (chunk,) = window_chunks(lines, "a.yml")
    assert (chunk.start_line, chunk.end_line) == (3, 4)
    assert chunk.text.split("\n")[0] == "first = 1"


def test_every_chunk_of_this_repo_starts_on_its_reported_line():
    """Text line i of a chunk is file line start_line + i, for the whole repo."""
    import os

    from chunking import chunk_file, iter_source_files

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    checked = 0
    for full, rel in iter_source_files(root):
        file_lines = open(full, encoding="utf-8", errors="ignore").read().splitlines()
        for c in chunk_file(full, rel):
            text_lines = c.text.split("\n")
            assert len(text_lines) == c.end_line - c.start_line + 1, rel
            assert all(t.strip() == file_lines[c.start_line - 1 + i].strip() for i, t in enumerate(text_lines)), rel
            checked += 1
    assert checked > 100


def test_oversized_files_are_not_indexed(tmp_path, monkeypatch):
    import chunking

    (tmp_path / "small.py").write_text("x = 1\n")
    (tmp_path / "big.py").write_text("y = 2\n" * 100)
    monkeypatch.setattr(chunking, "MAX_FILE_BYTES", 50)
    assert [rel for _, rel in chunking.iter_source_files(str(tmp_path))] == ["small.py"]
