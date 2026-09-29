"""Deterministic citation-faithfulness check: does an answer only cite
files that were actually retrieved for it? A plain regex + set-membership
check, deliberately not an LLM judge: "was this file in the retrieved
set" is a fact, not a matter of interpretation.
"""
from __future__ import annotations

import re

_CITATION_RE = re.compile(r"([\w./-]+\.\w+):(\d+)(?:-(\d+))?")


def extract_citations(answer: str) -> list[tuple[str, int, int]]:
    """Returns [(path, start, end), ...] found in `[path:start-end]`-style
    citations in the answer text."""
    return [(path, int(start), int(end) if end else int(start)) for path, start, end in _CITATION_RE.findall(answer)]


def check_faithfulness(answer: str, retrieved_chunks: list[dict]) -> dict:
    """retrieved_chunks: [{source_path, start_line, end_line}, ...]. A
    citation is faithful if its file was retrieved; line-range overlap is
    a bonus check, not required, since models paraphrase ranges."""
    citations = extract_citations(answer)
    if not citations:
        return {"citations_found": 0, "faithful": None, "unfaithful_citations": []}

    unfaithful = []
    for path, start, end in citations:
        in_file = any(c["source_path"] == path for c in retrieved_chunks)
        if not in_file:
            unfaithful.append(f"{path}:{start}-{end}")

    return {
        "citations_found": len(citations),
        "faithful": len(unfaithful) == 0,
        "unfaithful_citations": unfaithful,
    }
