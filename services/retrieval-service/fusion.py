"""Combines dense (Qdrant) and lexical (BM25) results via weighted
reciprocal rank fusion, then assembles the fused list into a token-budgeted
context: dedupes overlapping chunks and truncates without ever cutting a
single chunk in half.
"""
from __future__ import annotations

RRF_K = 60  # standard RRF smoothing constant


def _key(c: dict) -> tuple:
    return (c["source_path"], c["start_line"], c["end_line"])


def reciprocal_rank_fusion(dense: list[dict], lexical: list[dict], lex_weight: float) -> list[dict]:
    """dense/lexical: ranked chunk-dict lists. lex_weight in [0,1] scales
    lexical's contribution relative to dense's (1 - lex_weight)."""
    scores: dict[tuple, float] = {}
    chunks: dict[tuple, dict] = {}

    for rank, c in enumerate(dense):
        k = _key(c)
        scores[k] = scores.get(k, 0.0) + (1 - lex_weight) / (RRF_K + rank + 1)
        chunks[k] = c

    for rank, c in enumerate(lexical):
        k = _key(c)
        scores[k] = scores.get(k, 0.0) + lex_weight / (RRF_K + rank + 1)
        chunks.setdefault(k, c)

    fused = [{**chunks[k], "fusion_score": s} for k, s in scores.items()]
    fused.sort(key=lambda c: c["fusion_score"], reverse=True)
    return fused


def dedupe_overlapping(chunks: list[dict]) -> list[dict]:
    """Drops a chunk whose line range is fully contained within an
    already-kept, higher-ranked chunk on the same file."""
    kept: list[dict] = []
    for c in chunks:
        if any(
            k["source_path"] == c["source_path"] and k["start_line"] <= c["start_line"] and k["end_line"] >= c["end_line"]
            for k in kept
        ):
            continue
        kept.append(c)
    return kept


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # ~4 chars/token; good enough for budgeting


def assemble_context(chunks: list[dict], max_tokens: int, max_chunks: int | None = None) -> tuple[list[dict], int]:
    """Takes fused, deduped, best-first chunks and returns (selected,
    total_tokens) without exceeding max_tokens or max_chunks. A chunk is
    included whole or not at all, never truncated mid-chunk, since half a
    function is worse than no function. total_tokens counts only what was
    selected."""
    selected: list[dict] = []
    total = 0
    for c in chunks:
        if max_chunks is not None and len(selected) >= max_chunks:
            break
        t = _approx_tokens(c["text"])
        if total + t > max_tokens and selected:
            break
        selected.append(c)
        total += t
    return selected, total
