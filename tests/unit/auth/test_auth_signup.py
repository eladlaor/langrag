"""Email+password self-signup endpoint tests (api.auth.signup)."""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.requests import Request

from constants import HTTP_STATUS_CONFLICT, HTTP_STATUS_FORBIDDEN, SESSION_COOKIE_NAME, SIGNUP_CODE_NOT_ALLOWLISTED
from custom_types.api_schemas import SignupRequest
from custom_types.db_schemas import AuthProvider, UserRole
from custom_types.field_keys import UserKeys
from db.repositories.users import UsersRepository
from rag.auth.passwords import hash_password
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


class _Resp:
    """Minimal stand-in for fastapi.Response to capture set_cookie calls."""

    def __init__(self):
        self.cookies: dict[str, str] = {}

    def set_cookie(self, key, value, **kwargs):
        self.cookies[key] = value


def _Req() -> Request:
    """A minimal real Starlette Request.

    slowapi's @limiter.limit reaches into the request via app.state, so the
    rate-limit decorator needs a genuine starlette.requests.Request rather than
    a duck-typed stand-in. With no app.state.limiter wired in a direct function
    call, slowapi treats the limiter as disabled and passes through.
    """
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/signup",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


@pytest.fixture
def _signup_env(monkeypatch, unique_email):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_TTL_MINUTES", "60")
    monkeypatch.setenv("LANGRAG_LOGIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("LANGRAG_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_SIGNUP_ALLOWLIST", f'["{unique_email}"]')
    yield
    get_settings.cache_clear()


async def test_signup_allowlisted_creates_viewer_and_cookie(db, unique_email, _signup_env):
    from api.auth import signup
    from api.session_token import decode_session

    repo = UsersRepository(db)
    resp = _Resp()
    result = await signup(_Req(), SignupRequest(email=unique_email, password="pw-strong"), resp)
    try:
        assert result.authenticated is True
        assert result.role == UserRole.VIEWER
        assert SESSION_COOKIE_NAME in resp.cookies
        payload = decode_session(resp.cookies[SESSION_COOKIE_NAME])
        assert payload.role == UserRole.VIEWER
        user = await repo.find_by_email(unique_email)
        assert user[UserKeys.ROLE] == str(UserRole.VIEWER)
        assert user[UserKeys.COMMUNITIES] == []
        assert user[UserKeys.AUTH_PROVIDER] == str(AuthProvider.PASSWORD)
    finally:
        existing = await repo.find_by_email(unique_email)
        if existing:
            await repo.delete_user(existing[UserKeys.USER_ID])


async def test_signup_not_allowlisted_403_no_user(db, monkeypatch):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_SIGNUP_ALLOWLIST", '["someone-else@example.com"]')
    try:
        from api.auth import signup

        email = f"nope-{uuid.uuid4().hex[:12]}@example.com"
        resp = _Resp()
        with pytest.raises(HTTPException) as exc:
            await signup(_Req(), SignupRequest(email=email, password="pw"), resp)
        assert exc.value.status_code == HTTP_STATUS_FORBIDDEN
        assert exc.value.detail["code"] == SIGNUP_CODE_NOT_ALLOWLISTED
        assert SESSION_COOKIE_NAME not in resp.cookies
        repo = UsersRepository(db)
        assert await repo.find_by_email(email) is None
    finally:
        get_settings.cache_clear()


async def test_signup_disabled_403(db, monkeypatch, unique_email):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_SIGNUP_ENABLED", "false")
    monkeypatch.setenv("LANGRAG_SIGNUP_ALLOWLIST", f'["{unique_email}"]')
    try:
        from api.auth import signup

        with pytest.raises(HTTPException) as exc:
            await signup(_Req(), SignupRequest(email=unique_email, password="pw"), _Resp())
        assert exc.value.status_code == HTTP_STATUS_FORBIDDEN
    finally:
        get_settings.cache_clear()


async def test_signup_duplicate_email_409(db, unique_email, _signup_env):
    from api.auth import signup

    repo = UsersRepository(db)
    existing_id = await repo.create_user(email=unique_email, communities=[], role=UserRole.VIEWER, password_hash=hash_password("pw"))
    try:
        with pytest.raises(HTTPException) as exc:
            await signup(_Req(), SignupRequest(email=unique_email, password="pw2"), _Resp())
        assert exc.value.status_code == HTTP_STATUS_CONFLICT
    finally:
        await repo.delete_user(existing_id)
