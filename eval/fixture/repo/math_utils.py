"""Tiny fixture module for the CI retrieval-smoke test. Deliberately
unrelated content, so the benchmark has a real negative case."""


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
