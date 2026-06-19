"""API tests for the per-user RAG preferences endpoints.

Covers criterion 5 (422 validation at the API) and criterion 6 (PUT/GET
round-trip through FastAPI). Auth is faked via dependency_overrides on
`require_user`, matching the admin-users API test pattern.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import MongoClient

from config import get_settings
from constants import (
    API_V1_PREFIX,
    COLLECTION_USERS,
    HTTP_STATUS_OK,
    HTTP_STATUS_UNPROCESSABLE_ENTITY,
    ROUTE_USER_RAG_PREFERENCES,
)
from custom_types.field_keys import UserKeys
from tests._helpers.mongo import requires_mongodb

pytestmark = requires_mongodb


@pytest.fixture(autouse=True)
def _reset_db_singletons():
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    yield
    conn_mod._client = None
    conn_mod._database = None


@pytest.fixture
def users_col():
    client = MongoClient(get_settings().get_mongodb_url(), serverSelectionTimeoutMS=3000, directConnection=True)
    col = client[get_settings().database.database][COLLECTION_USERS]
    seeded: list[str] = []
    col._seeded = seeded  # type: ignore[attr-defined]
    yield col
    # Clean up exactly the users this test seeded, so the suite leaves no
    # residue in the shared collection (other users' rows are untouched).
    if seeded:
        col.delete_many({UserKeys.USER_ID: {"$in": seeded}})
    client.close()


def _seed_user(users_col) -> str:
    from constants import CURRENT_SCHEMA_VERSION_USER, SCHEMA_VERSION_FIELD

    user_id = str(uuid.uuid4())
    users_col.insert_one(
        {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_USER,
            UserKeys.USER_ID: user_id,
            UserKeys.EMAIL: f"api-pref-{user_id}@example.com",
            UserKeys.ROLE: "viewer",
            UserKeys.DISABLED: False,
        }
    )
    users_col._seeded.append(user_id)  # type: ignore[attr-defined]
    return user_id


def _build_app(user_id: str) -> FastAPI:
    from agent.auth.dependencies import require_user
    from agent.auth.user_context import UserContext
    from api import user_preferences

    app = FastAPI()
    app.include_router(user_preferences.router, prefix=API_V1_PREFIX)
    app.dependency_overrides[require_user] = lambda: UserContext(
        user_id=user_id, email="x@y.z", role="viewer", communities=()
    )
    return app


def _url() -> str:
    return f"{API_V1_PREFIX}{ROUTE_USER_RAG_PREFERENCES}"


# --- Criterion 6: PUT then GET round-trip ---
def test_put_then_get_round_trip(users_col):
    user_id = _seed_user(users_col)
    # Context-manager form keeps a single portal/event loop alive across both
    # requests, so the memoized Motor client from the PUT is still bound to a
    # live loop when the GET runs.
    with TestClient(_build_app(user_id)) as client:
        put = client.put(_url(), json={"mmr_lambda": 0.3, "enable_mmr_diversity": False})
        assert put.status_code == HTTP_STATUS_OK
        assert put.json()["mmr_lambda"] == pytest.approx(0.3)
        assert put.json()["enable_mmr_diversity"] is False

        got = client.get(_url())
        assert got.status_code == HTTP_STATUS_OK
        assert got.json()["mmr_lambda"] == pytest.approx(0.3)
        assert got.json()["enable_mmr_diversity"] is False


def test_get_unset_user_falls_back_to_config_default(users_col):
    user_id = _seed_user(users_col)
    client = TestClient(_build_app(user_id))

    got = client.get(_url())
    assert got.status_code == HTTP_STATUS_OK
    assert got.json()["mmr_lambda"] == pytest.approx(get_settings().rag.mmr_lambda)


# --- Criterion 5: API 422 on out-of-range, 200 on boundaries ---
@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_put_out_of_range_returns_422(users_col, bad):
    user_id = _seed_user(users_col)
    client = TestClient(_build_app(user_id))
    resp = client.put(_url(), json={"mmr_lambda": bad, "enable_mmr_diversity": True})
    assert resp.status_code == HTTP_STATUS_UNPROCESSABLE_ENTITY


@pytest.mark.parametrize("ok", [0.0, 1.0])
def test_put_boundary_returns_200(users_col, ok):
    user_id = _seed_user(users_col)
    client = TestClient(_build_app(user_id))
    resp = client.put(_url(), json={"mmr_lambda": ok, "enable_mmr_diversity": True})
    assert resp.status_code == HTTP_STATUS_OK
    assert resp.json()["mmr_lambda"] == pytest.approx(ok)
