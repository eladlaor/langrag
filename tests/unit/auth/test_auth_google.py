"""Google OAuth callback tests (api.google_oauth.google_callback).

Authlib's authorize_access_token is mocked end-to-end so no Google network call
is made: we stub _oauth.create_client to hand back a fake client returning a
{"userinfo": {...}} token. Account resolution, the VIEWER-only invariant, the
allowlist gate, email-verification, and the disabled-account rejection are then
asserted against the real users collection.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

from constants import (
    GOOGLE_CLAIM_EMAIL,
    GOOGLE_CLAIM_EMAIL_VERIFIED,
    GOOGLE_CLAIM_SUB,
    GOOGLE_TOKEN_USERINFO_KEY,
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_FOUND,
    QUERY_PARAM_SIGNUP,
    SESSION_COOKIE_NAME,
    SIGNUP_STATUS_REJECTED,
)
from custom_types.db_schemas import AuthProvider, UserRole
from custom_types.field_keys import UserKeys
from db.repositories.users import UsersRepository
from rag.auth.passwords import hash_password
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


def _Req() -> Request:
    """A minimal real Starlette Request carrying a transient OAuth session."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/auth/google/callback",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
        "session": {},
    }
    return Request(scope)


class _FakeGoogleClient:
    """Stands in for the Authlib client; returns a fixed validated token."""

    def __init__(self, token: dict):
        self._token = token

    async def authorize_access_token(self, request):
        return self._token


def _install_userinfo(monkeypatch, *, sub: str, email: str, email_verified: bool = True):
    """Patch api.google_oauth._oauth.create_client to return a fake client."""
    import api.google_oauth as mod

    token = {
        GOOGLE_TOKEN_USERINFO_KEY: {
            GOOGLE_CLAIM_SUB: sub,
            GOOGLE_CLAIM_EMAIL: email,
            GOOGLE_CLAIM_EMAIL_VERIFIED: email_verified,
        }
    }
    monkeypatch.setattr(mod._oauth, "create_client", lambda name: _FakeGoogleClient(token))


@pytest.fixture
def _google_env(monkeypatch, unique_email):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_TTL_MINUTES", "60")
    monkeypatch.setenv("LANGRAG_LOGIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("LANGRAG_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_SIGNUP_ALLOWLIST", f'["{unique_email}"]')
    monkeypatch.setenv("LANGRAG_SIGNUP_OAUTH_STATE_SECRET", "test-oauth-state-secret")
    monkeypatch.setenv("LANGRAG_GOOGLE_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("LANGRAG_GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("LANGRAG_GOOGLE_REDIRECT_URI", "http://localhost/api/auth/google/callback")
    yield
    get_settings.cache_clear()


async def test_google_new_allowlisted_creates_viewer_cookie_and_302(db, unique_email, _google_env, monkeypatch):
    from api.google_oauth import google_callback
    from api.session_token import decode_session

    repo = UsersRepository(db)
    sub = f"sub-{uuid.uuid4().hex[:12]}"
    _install_userinfo(monkeypatch, sub=sub, email=unique_email)
    try:
        resp = await google_callback(_Req())
        assert isinstance(resp, RedirectResponse)
        assert resp.status_code == HTTP_STATUS_FOUND
        assert resp.headers["location"] == "/"
        assert SESSION_COOKIE_NAME in resp.headers.get("set-cookie", "")

        user = await repo.find_by_email(unique_email)
        assert user is not None
        assert user[UserKeys.ROLE] == str(UserRole.VIEWER)
        assert user[UserKeys.COMMUNITIES] == []
        assert user[UserKeys.AUTH_PROVIDER] == str(AuthProvider.GOOGLE)
        assert user[UserKeys.GOOGLE_SUB] == sub

        # The cookie carries a real, decodable VIEWER session.
        cookie_header = resp.headers["set-cookie"]
        token = cookie_header.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
        payload = decode_session(token)
        assert payload.role == UserRole.VIEWER
    finally:
        existing = await repo.find_by_email(unique_email)
        if existing:
            await repo.delete_user(existing[UserKeys.USER_ID])


async def test_google_new_not_allowlisted_redirects_rejected_no_user_no_cookie(db, _google_env, monkeypatch):
    from api.google_oauth import google_callback

    repo = UsersRepository(db)
    email = f"nope-{uuid.uuid4().hex[:12]}@example.com"
    sub = f"sub-{uuid.uuid4().hex[:12]}"
    _install_userinfo(monkeypatch, sub=sub, email=email)
    try:
        resp = await google_callback(_Req())
        assert isinstance(resp, RedirectResponse)
        assert resp.status_code == HTTP_STATUS_FOUND
        assert f"{QUERY_PARAM_SIGNUP}={SIGNUP_STATUS_REJECTED}" in resp.headers["location"]
        assert SESSION_COOKIE_NAME not in resp.headers.get("set-cookie", "")
        assert await repo.find_by_email(email) is None
        assert await repo.find_by_google_sub(sub) is None
    finally:
        existing = await repo.find_by_email(email)
        if existing:
            await repo.delete_user(existing[UserKeys.USER_ID])


async def test_google_existing_password_account_same_email_links(db, unique_email, _google_env, monkeypatch):
    from api.google_oauth import google_callback

    repo = UsersRepository(db)
    user_id = await repo.create_self_signup_user(
        email=unique_email,
        auth_provider=AuthProvider.PASSWORD,
        password_hash=hash_password("pw"),
    )
    sub = f"sub-{uuid.uuid4().hex[:12]}"
    _install_userinfo(monkeypatch, sub=sub, email=unique_email)
    try:
        resp = await google_callback(_Req())
        assert isinstance(resp, RedirectResponse)
        assert resp.status_code == HTTP_STATUS_FOUND
        assert SESSION_COOKIE_NAME in resp.headers.get("set-cookie", "")

        user = await repo.find_by_user_id(user_id)
        assert user[UserKeys.GOOGLE_SUB] == sub
        assert user[UserKeys.AUTH_PROVIDER] == str(AuthProvider.PASSWORD_AND_GOOGLE)
        assert user[UserKeys.ROLE] == str(UserRole.VIEWER)
    finally:
        await repo.delete_user(user_id)


async def test_google_existing_sub_logs_in_directly(db, unique_email, _google_env, monkeypatch):
    from api.google_oauth import google_callback

    repo = UsersRepository(db)
    sub = f"sub-{uuid.uuid4().hex[:12]}"
    user_id = await repo.create_self_signup_user(
        email=unique_email,
        auth_provider=AuthProvider.GOOGLE,
        google_sub=sub,
    )
    _install_userinfo(monkeypatch, sub=sub, email=unique_email)
    try:
        resp = await google_callback(_Req())
        assert isinstance(resp, RedirectResponse)
        assert resp.status_code == HTTP_STATUS_FOUND
        assert SESSION_COOKIE_NAME in resp.headers.get("set-cookie", "")

        # No second user created for the same sub.
        found = await repo.find_by_google_sub(sub)
        assert found[UserKeys.USER_ID] == user_id
    finally:
        await repo.delete_user(user_id)


async def test_google_email_not_verified_rejected(db, unique_email, _google_env, monkeypatch):
    from api.google_oauth import google_callback

    repo = UsersRepository(db)
    sub = f"sub-{uuid.uuid4().hex[:12]}"
    _install_userinfo(monkeypatch, sub=sub, email=unique_email, email_verified=False)
    try:
        with pytest.raises(HTTPException) as exc:
            await google_callback(_Req())
        assert exc.value.status_code == HTTP_STATUS_FORBIDDEN
        assert await repo.find_by_email(unique_email) is None
    finally:
        existing = await repo.find_by_email(unique_email)
        if existing:
            await repo.delete_user(existing[UserKeys.USER_ID])


async def test_google_disabled_account_rejected(db, unique_email, _google_env, monkeypatch):
    from api.google_oauth import google_callback

    repo = UsersRepository(db)
    sub = f"sub-{uuid.uuid4().hex[:12]}"
    user_id = await repo.create_self_signup_user(
        email=unique_email,
        auth_provider=AuthProvider.GOOGLE,
        google_sub=sub,
    )
    await repo.set_disabled(user_id, True)
    _install_userinfo(monkeypatch, sub=sub, email=unique_email)
    try:
        with pytest.raises(HTTPException) as exc:
            await google_callback(_Req())
        assert exc.value.status_code == HTTP_STATUS_FORBIDDEN
    finally:
        await repo.delete_user(user_id)
