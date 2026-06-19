"""Shared fixtures for agent-layer repository tests.

The `requires_mongodb` skip marker lives at `tests._helpers.mongo` so it can
be imported by both unit and integration tests without making `tests/unit/db/`
a Python package (which would collide with `src/db/` at import time).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

# Hashing requires a pepper; tests set a deterministic one so api-key tests
# don't depend on .env. Production deployments still source the pepper from
# secrets at runtime.
os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")


@pytest_asyncio.fixture(autouse=True)
async def _ensure_agent_indexes():
    """Create the agent-layer indexes before every test.

    `ensure_indexes` is idempotent and cheap when the indexes already exist
    (MongoDB short-circuits the create). Doing it autouse means the tests
    don't have to remember to do it themselves, and the unique-email
    constraint is in place even on a freshly-mongo-rm'd database.
    """
    import db.connection as conn_mod
    from db.indexes import ensure_indexes

    conn_mod._client = None
    conn_mod._database = None
    database = await conn_mod.get_database()
    try:
        await ensure_indexes(database)
    finally:
        await conn_mod.close_connection()
    yield


@pytest_asyncio.fixture
async def db():
    """Yield a Motor database handle backed by the real MongoDB service.

    The `db.connection` module memoizes a single `AsyncMongoClient` for the
    process. Under pytest-asyncio's per-test event loop policy, that cached
    client outlives its loop and the second test fails with "Event loop is
    closed". Reset the singletons each test so every test gets a client
    bound to the current loop.
    """
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    database = await conn_mod.get_database()
    try:
        yield database
    finally:
        await conn_mod.close_connection()


@pytest.fixture
def unique_email():
    """Return a unique email per test so unique-constraint tests stay isolated."""
    return f"test-{uuid.uuid4().hex[:12]}@langrag.test"


@pytest.fixture
def unique_user_id():
    """Return a unique user_id per test."""
    return f"u-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def unique_session_id():
    return f"s-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def unique_memory_id():
    return f"m-{uuid.uuid4().hex[:12]}"
