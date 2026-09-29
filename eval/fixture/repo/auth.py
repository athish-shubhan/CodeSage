"""Tiny fixture module for the CI retrieval-smoke test. Not part of the
real application, just fixed, known content for a fast deterministic check.
"""

WIDGET_API_TOKEN_HEADER = "X-Widget-Api-Token"


def authenticate_widget_request(token: str) -> bool:
    return token == "widget-secret-token"


def revoke_widget_token(token: str) -> None:
    pass
