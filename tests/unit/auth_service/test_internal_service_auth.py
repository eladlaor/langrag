"""Tests for the internal service-auth path in api.auth.require_session.

These tests deliberately live OUTSIDE tests/unit/auth/ so they do not inherit
that directory's autouse MongoDB-index fixture: the service-principal path must
resolve WITHOUT touching the database, and that is exactly what is asserted
here. The cookie/DB paths themselves remain covered by
tests/unit/auth/test_require_session.py (Mongo-gated).
"""

from __future__ import annotations

import os

# The auth stack imports rag.auth.hashing, which requires a pepper at import
# resolution time. Set a deterministic one before any auth import so the tests
# do not depend on a populated .env.
os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from constants import HTTP_STATUS_UNAUTHORIZED, SERVICE_PRINCIPAL_SUBJECT, SESSION_SUBJECT_VALUE
from custom_types.db_schemas import UserRole

pytestmark = pytest.mark.asyncio

# Test-only header value. Not a real secret; never used outside these tests.
_CONFIGURED_KEY = "unit-test-internal-key-value"
_WRONG_KEY = "unit-test-wrong-key-value"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the lru_cache around get_settings before and after each test."""
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_login_env(monkeypatch, *, enabled: bool, internal_api_key: str) -> None:
    """Configure the LANGRAG_LOGIN_* env so get_settings reflects this test's intent."""
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_TTL_MINUTES", "60")
    monkeypatch.setenv("LANGRAG_LOGIN_INTERNAL_API_KEY", internal_api_key)
    from config import get_settings

    get_settings.cache_clear()


async def test_gate_disabled_ignores_internal_key_returns_sentinel(monkeypatch):
    """Login disabled -> service path irrelevant, dev sentinel admin returned."""
    _set_login_env(monkeypatch, enabled=False, internal_api_key=_CONFIGURED_KEY)
    from api.auth import require_session

    current = await require_session(session_cookie=None, internal_key=_CONFIGURED_KEY)

    assert current.role == UserRole.ADMIN
    assert current.user_id == SESSION_SUBJECT_VALUE  # dev sentinel, NOT the service principal


async def test_correct_internal_key_resolves_service_principal(monkeypatch):
    """Enabled + configured key + correct header -> admin service principal, no DB lookup.

    No `db` fixture is used and get_database is never invoked: a DB hit here would
    fail (no Mongo guaranteed), so reaching CurrentUser proves the DB was bypassed.
    """
    _set_login_env(monkeypatch, enabled=True, internal_api_key=_CONFIGURED_KEY)
    from api.auth import require_session

    current = await require_session(session_cookie=None, internal_key=_CONFIGURED_KEY)

    assert current.role == UserRole.ADMIN
    assert current.user_id == SERVICE_PRINCIPAL_SUBJECT
    assert current.email == SERVICE_PRINCIPAL_SUBJECT
    assert current.communities == []


async def test_wrong_internal_key_is_401_no_fallthrough(monkeypatch):
    """Enabled + configured key + WRONG header -> 401, does not fall through to cookie path.

    A valid cookie is supplied alongside the wrong key; if the code fell through
    to the cookie path it would attempt a DB lookup. The explicit 401 proves the
    wrong key short-circuits before any cookie/DB handling.
    """
    _set_login_env(monkeypatch, enabled=True, internal_api_key=_CONFIGURED_KEY)
    from api.auth import require_session
    from api.session_token import encode_session

    cookie = encode_session(user_id="any-user", role=UserRole.VIEWER, epoch=0)

    with pytest.raises(HTTPException) as exc:
        await require_session(session_cookie=cookie, internal_key=_WRONG_KEY)
    assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED


async def test_no_header_no_cookie_401(monkeypatch):
    """Enabled + configured key + no header + no cookie -> 401 (cookie path unchanged)."""
    _set_login_env(monkeypatch, enabled=True, internal_api_key=_CONFIGURED_KEY)
    from api.auth import require_session

    with pytest.raises(HTTPException) as exc:
        await require_session(session_cookie=None, internal_key=None)
    assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED


async def test_no_header_invalid_cookie_falls_through_to_cookie_path(monkeypatch):
    """Enabled + configured key + no header + a cookie -> cookie path runs (service path inert).

    Uses a structurally invalid cookie so the cookie path rejects it at decode
    time (SessionDecodeError -> 401) WITHOUT needing Mongo. The point is that the
    service path did not interfere: control reached the cookie-decode branch.
    """
    _set_login_env(monkeypatch, enabled=True, internal_api_key=_CONFIGURED_KEY)
    from api.auth import require_session

    with pytest.raises(HTTPException) as exc:
        await require_session(session_cookie="not-a-valid-fernet-token", internal_key=None)
    assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED


async def test_empty_configured_key_makes_header_inert(monkeypatch):
    """Enabled + EMPTY configured key + any header value -> header path inert (fail-closed).

    With no key configured, presenting any X-Internal-Key must NOT authenticate;
    control falls through to the cookie path, which 401s with no cookie present.
    """
    _set_login_env(monkeypatch, enabled=True, internal_api_key="")
    from api.auth import require_session

    with pytest.raises(HTTPException) as exc:
        await require_session(session_cookie=None, internal_key=_CONFIGURED_KEY)
    assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED
