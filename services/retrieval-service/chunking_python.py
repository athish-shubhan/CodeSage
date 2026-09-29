"""AST-aware chunking for Python files: splits on top-level def/class
boundaries instead of blind line windows, so a chunk is (usually) one whole
function or class rather than an arbitrary 60-line slice that might cut a
function in half. Falls back to the caller's line-window chunker for
non-Python files, syntax errors, or any single unit too large to embed
sensibly whole.
"""
from __future__ import annotations

import ast

MAX_UNIT_LINES = 120  # a def/class body larger than this still gets windowed


def chunk_python_source(source: str, rel_path: str, window_chunks) -> list | None:
    """Returns RawChunk list, or None if `source` isn't parseable Python
    (caller should fall back to plain line-window chunking for the file)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines(keepends=True)
    units = _top_level_units(tree, len(lines))

    chunks = []
    for start, end in units:
        if end - start + 1 <= MAX_UNIT_LINES:
            text = "".join(lines[start - 1 : end]).strip()
            if text:
                chunks.append(_make_chunk(text, rel_path, start, end))
        else:
            chunks.extend(window_chunks(lines[start - 1 : end], rel_path, base_line=start))
    return chunks


def _make_chunk(text: str, rel_path: str, start: int, end: int):
    from chunking import RawChunk

    return RawChunk(text=text, source_path=rel_path, start_line=start, end_line=end)


def _top_level_units(tree: ast.Module, total_lines: int) -> list[tuple[int, int]]:
    """One (start_line, end_line) span per top-level def/class, with
    consecutive non-def/class statements (imports, constants, docstrings)
    merged into their own spans rather than split apart."""
    spans: list[tuple[int, int]] = []
    leftover_start: int | None = None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if leftover_start is not None:
                spans.append((leftover_start, node.lineno - 1))
                leftover_start = None
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans.append((start, node.end_lineno or node.lineno))
        else:
            if leftover_start is None:
                leftover_start = node.lineno

    if leftover_start is not None:
        spans.append((leftover_start, total_lines))

    return sorted(spans)
