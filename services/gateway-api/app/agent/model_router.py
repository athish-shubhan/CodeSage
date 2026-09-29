"""Model routing: picks between a 'fast' and a 'capable' model based on a
cheap heuristic, not a learned or sophisticated routing engine. The task
doesn't warrant one yet. See docs/architecture.md for when it would.
"""
from __future__ import annotations

from app.config import settings


def pick_model(task: str) -> str:
    """Longer or multi-part questions likely need the more capable model;
    short lookups can use the faster one. Falls back to the single
    configured model when no 'fast' variant is set (the common case, and
    what every existing backend override still does)."""
    if not settings.llm_model_fast:
        return settings.llm_model
    is_complex = len(task) > 120 or task.count("?") > 1 or " and " in task.lower()
    return settings.llm_model if is_complex else settings.llm_model_fast
