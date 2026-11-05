"""The agent layer's untrusted-data handling, applied to the single-pass
/chat and /ws/chat paths (docs/adr/0006-untrusted-tool-output.md).

Retrieved chunks are repository text, so they get the same treatment as an
agent tool result: instruction-like sentences are removed before the chunk
enters the prompt (recorded as injection flags at their file lines), the
context block is delimited as data (llm_client.build_prompt), and the answer's
citations and identifiers are checked against the chunks the model was shown.
"""
from __future__ import annotations

from app.agent import citations, untrusted
from app.agent.state import InjectionFlag, ToolCallRecord
from app.metrics import CHAT_CITATIONS, CHAT_INJECTION_FLAGS


def sanitize_sources(sources: list[dict]) -> tuple[list[dict], list[InjectionFlag]]:
    """(copies of sources with flagged sentences removed, what was removed).
    A chunk's text line i is file line start_line + i (chunking.trimmed_span)."""
    clean, flags = [], []
    for src in sources:
        text, removals = untrusted.sanitize(src["text"])
        for r in removals:
            flags.append(
                InjectionFlag(
                    "retrieval",
                    r.rule,
                    r.text,
                    src["source_path"],
                    src["start_line"] + r.start_line - 1,
                    src["start_line"] + r.end_line - 1,
                )
            )
            CHAT_INJECTION_FLAGS.labels(rule=r.rule).inc()
        clean.append({**src, "text": text})
    return clean, flags


def check_answer(answer: str, clean_sources: list[dict], flags: list[InjectionFlag]) -> dict:
    """{"grounded", "ungrounded", "unsupported_identifiers"} for an answer
    written from these (sanitized) sources, by the same checks /agent runs."""
    shown = ToolCallRecord(
        "search_code",
        {},
        "\n\n".join(
            f"[{c['source_path']}:{c['start_line']}-{c['end_line']}]\n{citations.escape_header_lines(c['text'])}"
            for c in clean_sources
        ),
    )
    verdict = citations.check(answer, [shown], citations.removed_lines(flags))
    CHAT_CITATIONS.labels(grounded="true").inc(len(verdict["grounded"]))
    CHAT_CITATIONS.labels(grounded="false").inc(len(verdict["ungrounded"]))
    return {**verdict, "unsupported_identifiers": citations.unsupported_identifiers(answer, [shown])}
