"""Tests for the Fernet session-token helpers (api.session_token)."""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from custom_types.db_schemas import UserRole


@pytest.fixture(autouse=True)
def _fernet_env(monkeypatch):
    """Configure a real Fernet key + a tiny TTL via the login settings cache."""
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_TTL_MINUTES", "60")
    yield
    get_settings.cache_clear()


def test_round_trip_preserves_claims():
    from api.session_token import decode_session, encode_session

    token = encode_session(user_id="u-123", role=UserRole.ADMIN, epoch=7)
    payload = decode_session(token)
    assert payload.sub == "u-123"
    assert payload.role == UserRole.ADMIN
    assert payload.epoch == 7


def test_tampered_token_is_rejected():
    from api.session_token import SessionDecodeError, decode_session, encode_session

    token = encode_session(user_id="u-1", role=UserRole.VIEWER, epoch=0)
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(SessionDecodeError):
        decode_session(tampered)


def test_garbage_token_is_rejected():
    from api.session_token import SessionDecodeError, decode_session

    with pytest.raises(SessionDecodeError):
        decode_session("not-a-real-token")


def test_expired_token_is_rejected(monkeypatch):
    from api.session_token import SessionDecodeError, decode_session, encode_session

    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_TTL_MINUTES", "0")
    from config import get_settings

    get_settings.cache_clear()
    token = encode_session(user_id="u-9", role=UserRole.ADMIN, epoch=1)
    time.sleep(1.1)
    with pytest.raises(SessionDecodeError):
        decode_session(token)
