"""Integration tests for the cookie-gated agent API-key endpoints.

Covers the handler logic added in the agent-UI wireup:
  - issue -> list -> revoke round-trip through HTTP, scoped to the caller.
  - cross-user revoke denial: a user cannot revoke another user's key (404),
    and the foreign key stays enabled.

`require_session` is overridden to inject a CurrentUser directly, so the test
exercises the handler + real repository against the docker MongoDB without
reconstructing the Fernet cookie flow (that path is covered by auth tests).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests._helpers.mongo import requires_mongodb

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")
os.environ["AGENT_ENABLED"] = "true"

pytestmark = [requires_mongodb, pytest.mark.asyncio]

KEYS_ROUTE = "/api/users/me/agent-keys"


def _current_user(user_id: str):
    from custom_types.api_schemas import CurrentUser
    from custom_types.db_schemas import UserRole

    return CurrentUser(user_id=user_id, email=f"{user_id}@test.local", role=UserRole.ADMIN, communities=[])


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setenv("AGENT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    # Reset the Motor connection singletons so the app binds its client to the
    # event loop ASGITransport runs on (each test gets a fresh loop). Mirrors
    # tests/integration/agent/test_chat_non_streaming.py.
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None

    import importlib

    import main

    importlib.reload(main)
    from api.auth import require_session

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, main.app, require_session

    main.app.dependency_overrides.clear()
    await conn_mod.close_connection()
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_issue_list_revoke_round_trip(client):
    c, app, require_session = client
    user_id = f"user-{uuid.uuid4()}"
    app.dependency_overrides[require_session] = lambda: _current_user(user_id)

    issued = (await c.post(KEYS_ROUTE, json={"name": "laptop"})).json()
    assert issued["plaintext"].startswith("lk_user_")
    assert issued["name"] == "laptop"
    key_id = issued["key_id"]

    listing = (await c.get(KEYS_ROUTE)).json()
    assert any(k["key_id"] == key_id and k["enabled"] for k in listing)
    assert all("plaintext" not in k and "key_hash" not in k for k in listing)

    resp = await c.delete(f"{KEYS_ROUTE}/{key_id}")
    assert resp.status_code == 204

    listing_after = (await c.get(KEYS_ROUTE)).json()
    assert all(k["key_id"] != key_id or k["enabled"] is False for k in listing_after)


async def test_cannot_revoke_another_users_key(client):
    c, app, require_session = client
    owner = f"owner-{uuid.uuid4()}"
    attacker = f"attacker-{uuid.uuid4()}"

    app.dependency_overrides[require_session] = lambda: _current_user(owner)
    key_id = (await c.post(KEYS_ROUTE, json={"name": "victim"})).json()["key_id"]

    # Switch identity to the attacker and attempt to revoke the owner's key.
    app.dependency_overrides[require_session] = lambda: _current_user(attacker)
    resp = await c.delete(f"{KEYS_ROUTE}/{key_id}")
    assert resp.status_code == 404

    # The owner's key must still be enabled.
    app.dependency_overrides[require_session] = lambda: _current_user(owner)
    listing = (await c.get(KEYS_ROUTE)).json()
    assert any(k["key_id"] == key_id and k["enabled"] for k in listing)
