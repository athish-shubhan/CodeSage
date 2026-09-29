"""Tiny fixture module for the CI retrieval-smoke test."""

SPROCKET_QUEUE_DEPTH = 42


def load_sprocket_settings() -> dict:
    return {"queue_depth": SPROCKET_QUEUE_DEPTH}
