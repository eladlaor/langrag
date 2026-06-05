"""Shared fixtures for individual-account auth tests.

Mirrors tests/unit/db/conftest.py: a per-test Motor handle bound to the current
event loop, plus unique-value helpers. Kept local to this directory so it does
not turn tests/unit/ into a package (which would collide with src/).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

# Password hashing for users needs no pepper, but other imports in the auth
# stack pull in rag.auth.hashing which requires a pepper at import-resolution
# time; set a deterministic one so tests do not depend on .env.
os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")


@pytest_asyncio.fixture(autouse=True)
async def _ensure_user_indexes():
    """Create user-collection indexes (unique email) before every test."""
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
    """Yield a Motor database handle bound to the current event loop."""
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
    # Use a normal TLD: EmailStr (email-validator) rejects reserved/special-use
    # TLDs like .test, so the shared db-conftest domain would not validate here.
    return f"test-{uuid.uuid4().hex[:12]}@example.com"
