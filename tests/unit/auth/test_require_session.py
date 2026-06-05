"""Tests for the require_session dependency (api.auth.require_session)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from constants import HTTP_STATUS_UNAUTHORIZED
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
    yield
    get_settings.cache_clear()


async def test_valid_cookie_resolves_current_user(db, unique_email):
    from api.auth import require_session
    from api.session_token import encode_session

    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=["mcp_israel"], role=UserRole.VIEWER, password_hash=hash_password("pw"))
    try:
        token = encode_session(user_id=user_id, role=UserRole.VIEWER, epoch=0)
        current = await require_session(session_cookie=token)
        assert current.user_id == user_id
        assert current.email == unique_email
        assert current.role == UserRole.VIEWER
        assert current.communities == ["mcp_israel"]
    finally:
        await repo.delete_user(user_id)


async def test_missing_cookie_401(db):
    from api.auth import require_session

    with pytest.raises(HTTPException) as exc:
        await require_session(session_cookie=None)
    assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED


async def test_stale_epoch_rejected(db, unique_email):
    from api.auth import require_session
    from api.session_token import encode_session

    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash=hash_password("pw"))
    try:
        token = encode_session(user_id=user_id, role=UserRole.ADMIN, epoch=0)
        await repo.bump_session_epoch(user_id)  # now stored epoch == 1
        with pytest.raises(HTTPException) as exc:
            await require_session(session_cookie=token)
        assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED
    finally:
        await repo.delete_user(user_id)


async def test_disabled_user_rejected(db, unique_email):
    from api.auth import require_session
    from api.session_token import encode_session

    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash=hash_password("pw"))
    try:
        token = encode_session(user_id=user_id, role=UserRole.ADMIN, epoch=0)
        await repo.set_disabled(user_id, True)
        with pytest.raises(HTTPException) as exc:
            await require_session(session_cookie=token)
        assert exc.value.status_code == HTTP_STATUS_UNAUTHORIZED
    finally:
        await repo.delete_user(user_id)


async def test_gate_disabled_returns_sentinel_admin(db, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "false")
    get_settings.cache_clear()
    from api.auth import require_session

    current = await require_session(session_cookie=None)
    assert current.role == UserRole.ADMIN
