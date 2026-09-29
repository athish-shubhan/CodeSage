"""Splits source files into overlapping line-ranged chunks for embedding."""
from __future__ import annotations

import os
from dataclasses import dataclass

CHUNK_LINES = 60
OVERLAP_LINES = 10

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
    ".md", ".yaml", ".yml", ".json", ".proto", ".sh", ".sql", ".toml",
}


@dataclass
class RawChunk:
    text: str
    source_path: str
    start_line: int
    end_line: int


def iter_source_files(repo_path: str, include_globs: list[str] | None = None):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
        for fname in files:
            ext = os.path.splitext(fname)[1]
            if ext not in TEXT_EXTENSIONS:
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, repo_path)
            if include_globs and not any(_matches(rel, g) for g in include_globs):
                continue
            yield full, rel


def _matches(path: str, glob: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(path, glob)


def window_chunks(lines: list[str], rel_path: str, base_line: int = 1) -> list[RawChunk]:
    """Fixed line-window chunking with overlap. `base_line` is the absolute
    line number `lines[0]` corresponds to in the source file, so callers can
    window just a sub-range (e.g. one oversized function) and still get
    correct file-relative line numbers back."""
    chunks: list[RawChunk] = []
    step = CHUNK_LINES - OVERLAP_LINES
    for start in range(0, max(len(lines), 1), step):
        end = min(start + CHUNK_LINES, len(lines))
        text = "".join(lines[start:end]).strip()
        if text:
            chunks.append(
                RawChunk(text=text, source_path=rel_path, start_line=base_line + start, end_line=base_line + end - 1)
            )
        if end >= len(lines):
            break
    return chunks


def chunk_file(full_path: str, rel_path: str) -> list[RawChunk]:
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except OSError:
        return []

    if rel_path.endswith(".py"):
        from chunking_python import chunk_python_source

        chunks = chunk_python_source(source, rel_path, window_chunks)
        if chunks is not None:
            return chunks

    return window_chunks(source.splitlines(keepends=True), rel_path)


def chunk_repo(repo_path: str, include_globs: list[str] | None = None) -> tuple[list[RawChunk], int]:
    all_chunks: list[RawChunk] = []
    files_seen = 0
    for full, rel in iter_source_files(repo_path, include_globs):
        files_seen += 1
        all_chunks.extend(chunk_file(full, rel))
    return all_chunks, files_seen
