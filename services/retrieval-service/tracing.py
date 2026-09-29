"""A plain in-process trace: a list of timed spans through the retrieval
pipeline (classify -> dense -> lexical -> fuse -> rerank -> assemble).

Deliberately not OpenTelemetry/Jaeger: this is a single-node demo with one
consumer (the debug view / eval harness), so a collector + storage backend
+ UI would be pure overhead. If CodeSage ever runs multi-node with several
teams needing cross-service trace correlation, that calculation changes --
see docs/architecture.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Span:
    stage: str
    ms: float
    meta: dict = field(default_factory=dict)


class Trace:
    def __init__(self) -> None:
        self.spans: list[Span] = []

    def step(self, stage: str, meta: dict | None = None):
        """Context manager: `with trace.step("dense_search"): ...`"""
        return _StepTimer(self, stage, meta or {})

    def as_dict(self) -> list[dict]:
        return [{"stage": s.stage, "ms": round(s.ms, 2), "meta": s.meta} for s in self.spans]


class _StepTimer:
    def __init__(self, trace: Trace, stage: str, meta: dict) -> None:
        self.trace, self.stage, self.meta = trace, stage, meta

    def __enter__(self):
        self._start = time.perf_counter()
        return self.meta

    def __exit__(self, *exc):
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        self.trace.spans.append(Span(stage=self.stage, ms=elapsed_ms, meta=self.meta))
        return False
