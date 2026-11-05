import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import authenticate, create_access_token, decode_token  # noqa: E402


def test_authenticate_valid_demo_credentials():
    assert authenticate("admin", "admin") is True


def test_authenticate_rejects_wrong_password():
    assert authenticate("admin", "wrong") is False


def test_token_round_trip():
    token = create_access_token("admin")
    assert decode_token(token) == "admin"


def test_insecure_defaults_are_reported_until_overridden(monkeypatch):
    from app.auth import insecure_defaults
    from app.config import settings

    assert len(insecure_defaults()) == 2  # the shipped settings
    monkeypatch.setattr(settings, "jwt_secret", "a-real-secret")
    monkeypatch.setattr(settings, "demo_password", "not-admin")
    assert insecure_defaults() == []


def test_startup_logs_each_insecure_default(caplog):
    from fastapi.testclient import TestClient

    from app.main import app

    with caplog.at_level("WARNING", logger="gateway-api"), TestClient(app):
        pass
    warnings = [r.getMessage() for r in caplog.records if r.name == "gateway-api"]
    assert len(warnings) == 2 and all(w.startswith("insecure default:") for w in warnings)
