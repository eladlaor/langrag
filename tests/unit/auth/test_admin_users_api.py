"""Tests for the admin user-management router (api.admin_users).

The router does all DB work on the TestClient's own event loop, so these tests
avoid the async Motor `db` fixture (which would bind a client to a different
loop) and use a synchronous pymongo client for setup / verification instead.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient

from config import get_settings
from constants import (
    API_V1_PREFIX,
    COLLECTION_USERS,
    HTTP_STATUS_CONFLICT,
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_OK,
    ROUTE_AUTH_USERS,
)
from custom_types.api_schemas import CurrentUser
from custom_types.db_schemas import UserRole
from custom_types.field_keys import UserKeys
from rag.auth.passwords import hash_password, verify_password
from tests._helpers.mongo import requires_mongodb

pytestmark = requires_mongodb


@pytest.fixture(autouse=True)
def _login_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LANGRAG_LOGIN_ENABLED", "true")
    monkeypatch.setenv("LANGRAG_LOGIN_SESSION_KEY", Fernet.generate_key().decode("utf-8"))
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_db_singletons():
    """Drop the memoized Motor client so the TestClient loop owns a fresh one."""
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    yield
    conn_mod._client = None
    conn_mod._database = None


@pytest.fixture
def users_col():
    """Synchronous pymongo handle to the users collection for setup / asserts."""
    client = MongoClient(get_settings().get_mongodb_url(), serverSelectionTimeoutMS=3000, directConnection=True)
    col = client[get_settings().database.database][COLLECTION_USERS]
    yield col
    client.close()


def _build_app(current: CurrentUser) -> FastAPI:
    from api import admin_users
    from api.auth import require_admin

    app = FastAPI()
    app.include_router(admin_users.router, prefix=API_V1_PREFIX)
    app.dependency_overrides[require_admin] = lambda: current
    return app


def _admin() -> CurrentUser:
    return CurrentUser(user_id="admin-self", email="admin@example.com", role=UserRole.ADMIN, communities=[])


def _seed_user(users_col, email: str, **overrides) -> str:
    import uuid

    doc = {
        UserKeys.USER_ID: str(uuid.uuid4()),
        UserKeys.EMAIL: email,
        UserKeys.ROLE: str(UserRole.VIEWER),
        UserKeys.PASSWORD_HASH: hash_password("seed-pass"),
        UserKeys.SESSION_EPOCH: 0,
        UserKeys.DISABLED: False,
        UserKeys.COMMUNITIES: [],
    }
    doc.update(overrides)
    users_col.insert_one(doc)
    return doc[UserKeys.USER_ID]


def test_create_user_returns_no_hash(users_col, unique_email):
    client = TestClient(_build_app(_admin()))
    resp = client.post(
        API_V1_PREFIX + ROUTE_AUTH_USERS,
        json={"email": unique_email, "password": "init-pass", "role": str(UserRole.VIEWER), "communities": ["langtalks"]},
    )
    try:
        assert resp.status_code == HTTP_STATUS_OK
        body = resp.json()
        assert "password_hash" not in body
        assert body["email"] == unique_email
        stored = users_col.find_one({UserKeys.EMAIL: unique_email})
        assert stored[UserKeys.PASSWORD_HASH] != "init-pass"
        assert verify_password("init-pass", stored[UserKeys.PASSWORD_HASH]) is True
    finally:
        users_col.delete_one({UserKeys.EMAIL: unique_email})


def test_create_duplicate_email_409(users_col, unique_email):
    _seed_user(users_col, unique_email)
    try:
        client = TestClient(_build_app(_admin()))
        resp = client.post(
            API_V1_PREFIX + ROUTE_AUTH_USERS,
            json={"email": unique_email, "password": "p", "role": str(UserRole.VIEWER), "communities": []},
        )
        assert resp.status_code == HTTP_STATUS_CONFLICT
    finally:
        users_col.delete_one({UserKeys.EMAIL: unique_email})


def test_list_users_strips_hash(users_col, unique_email):
    uid = _seed_user(users_col, unique_email)
    try:
        client = TestClient(_build_app(_admin()))
        resp = client.get(API_V1_PREFIX + ROUTE_AUTH_USERS)
        assert resp.status_code == HTTP_STATUS_OK
        rows = resp.json()
        assert all("password_hash" not in r for r in rows)
        assert any(r["user_id"] == uid for r in rows)
    finally:
        users_col.delete_one({UserKeys.USER_ID: uid})


def test_reset_password_bumps_epoch(users_col, unique_email):
    uid = _seed_user(users_col, unique_email, **{UserKeys.PASSWORD_HASH: hash_password("old")})
    try:
        client = TestClient(_build_app(_admin()))
        resp = client.post(f"{API_V1_PREFIX}{ROUTE_AUTH_USERS}/{uid}/password", json={"password": "new-pass"})
        assert resp.status_code == HTTP_STATUS_OK
        stored = users_col.find_one({UserKeys.USER_ID: uid})
        assert stored[UserKeys.SESSION_EPOCH] == 1
        assert verify_password("new-pass", stored[UserKeys.PASSWORD_HASH]) is True
    finally:
        users_col.delete_one({UserKeys.USER_ID: uid})


def test_disable_user(users_col, unique_email):
    uid = _seed_user(users_col, unique_email)
    try:
        client = TestClient(_build_app(_admin()))
        resp = client.post(f"{API_V1_PREFIX}{ROUTE_AUTH_USERS}/{uid}/disable", json={"disabled": True})
        assert resp.status_code == HTTP_STATUS_OK
        assert users_col.find_one({UserKeys.USER_ID: uid})[UserKeys.DISABLED] is True
    finally:
        users_col.delete_one({UserKeys.USER_ID: uid})


def test_admin_cannot_disable_self():
    admin = CurrentUser(user_id="self-123", email="self@example.com", role=UserRole.ADMIN, communities=[])
    client = TestClient(_build_app(admin))
    resp = client.post(f"{API_V1_PREFIX}{ROUTE_AUTH_USERS}/self-123/disable", json={"disabled": True})
    assert resp.status_code in (400, 409)


def test_admin_cannot_delete_self():
    admin = CurrentUser(user_id="self-456", email="self2@example.com", role=UserRole.ADMIN, communities=[])
    client = TestClient(_build_app(admin))
    resp = client.delete(f"{API_V1_PREFIX}{ROUTE_AUTH_USERS}/self-456")
    assert resp.status_code in (400, 409)


def test_delete_user(users_col, unique_email):
    uid = _seed_user(users_col, unique_email)
    client = TestClient(_build_app(_admin()))
    resp = client.delete(f"{API_V1_PREFIX}{ROUTE_AUTH_USERS}/{uid}")
    assert resp.status_code == HTTP_STATUS_OK
    assert users_col.find_one({UserKeys.USER_ID: uid}) is None


def test_role_guard_blocks_non_admin():
    """With the real require_admin (not overridden), a viewer is forbidden."""
    from api import admin_users
    from api.auth import require_session

    app = FastAPI()
    app.include_router(admin_users.router, prefix=API_V1_PREFIX)
    app.dependency_overrides[require_session] = lambda: CurrentUser(
        user_id="v-1", email="v@example.com", role=UserRole.VIEWER, communities=[]
    )
    client = TestClient(app)
    resp = client.get(API_V1_PREFIX + ROUTE_AUTH_USERS)
    assert resp.status_code == HTTP_STATUS_FORBIDDEN
