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
