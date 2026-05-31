"""Shared fixtures for agent auth tests."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")


@pytest_asyncio.fixture(autouse=True)
async def _ensure_indexes():
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
    return f"test-{uuid.uuid4().hex[:12]}@langrag.test"
