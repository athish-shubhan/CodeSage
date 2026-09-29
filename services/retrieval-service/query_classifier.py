"""Deterministic query classification: decides how much to trust lexical
(BM25) vs dense (embedding) search for a given query, without an LLM call.

Queries containing identifier-shaped tokens (snake_case, camelCase,
CONSTANT_CASE, dotted.paths, quoted strings, filenames) usually want an
exact match BM25 is much better at than a bi-encoder; free-text questions
want semantic matching. This is a cheap heuristic on purpose. An LLM call
just to classify would add a full round-trip of latency for a decision a
handful of regexes make instantly.
"""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b"),  # snake_case
    re.compile(r"\b[a-z]+[A-Z][a-zA-Z0-9]*\b"),  # camelCase
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"),  # CONSTANT_CASE
    re.compile(r"\b\w+\.\w+(?:\.\w+)*\b"),  # dotted.path or filename.ext
    re.compile(r"[\"'][^\"']+[\"']"),  # quoted string
]


def lexical_weight(query: str) -> float:
    """Weight in [0, 1] for how much to trust lexical results relative to
    dense results during fusion; 0.5 = equal trust."""
    hits = sum(1 for pat in _PATTERNS if pat.search(query))
    if hits == 0:
        return 0.3
    return min(0.5 + 0.15 * hits, 0.8)
