"""Login endpoint tests for individual-account auth (api.auth.login)."""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from constants import HTTP_STATUS_UNAUTHORIZED
from custom_types.api_schemas import LoginRequest
from custom_types.db_schemas import UserRole
from db.repositories.users import UsersRepository
from rag.auth.passwords import hash_password
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _login_env(monkeypatch):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_TTL_MINUTES", "60")
    monkeypatch.setenv("LANGRAG_LOGIN_COOKIE_SECURE", "false")
    yield
    get_settings.cache_clear()


class _Resp:
    """Minimal stand-in for fastapi.Response to capture set_cookie calls."""

    def __init__(self):
        self.cookies: dict[str, str] = {}

    def set_cookie(self, key, value, **kwargs):
        self.cookies[key] = value


async def test_login_success_sets_cookie(db, unique_email):
    from api.auth import login

    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=["langtalks"], role=UserRole.ADMIN, password_hash=hash_password("pw-correct"))
    try:
        resp = _Resp()
        result = await login(LoginRequest(email=unique_email, password="pw-correct"), resp)
        assert result.authenticated is True
        assert result.email == unique_email
        assert result.role == UserRole.ADMIN
        from constants import SESSION_COOKIE_NAME

        assert SESSION_COOKIE_NAME in resp.cookies
    finally:
        await repo.delete_user(user_id)


async def test_login_wrong_password_401(db, unique_email):
    from api.auth import login

    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash=hash_password("right"))
    try:
        with pytest.raises(HTTPException) as exc:
            await login(LoginRequest(email=unique_email, password="wrong"), _Resp())
        assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED
    finally:
        await repo.delete_user(user_id)


async def test_login_unknown_email_401(db):
    from api.auth import login

    with pytest.raises(HTTPException) as exc:
        await login(LoginRequest(email=f"nobody-{uuid.uuid4().hex}@example.com", password="whatever"), _Resp())
    assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED


async def test_login_disabled_account_401(db, unique_email):
    from api.auth import login

    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash=hash_password("pw"))
    try:
        await repo.set_disabled(user_id, True)
        with pytest.raises(HTTPException) as exc:
            await login(LoginRequest(email=unique_email, password="pw"), _Resp())
        assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED
    finally:
        await repo.delete_user(user_id)
