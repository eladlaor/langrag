"""Integration test: agent-layer indexes are actually created on startup.

Calls `ensure_indexes(db)` against the real MongoDB and then asserts that
the expected indexes are present on each new collection. Search indexes
(vector + lexical) are best-effort against mongot; their absence is a warning
not a failure, so this test only checks they were created when mongot built
them — see `_search_index_present` below.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from constants import (
    AGENT_MEMORY_LEXICAL_INDEX_NAME,
    AGENT_MEMORY_VECTOR_INDEX_NAME,
    COLLECTION_AGENT_MEMORIES,
    COLLECTION_AGENT_SESSIONS,
    COLLECTION_USER_API_KEYS,
    COLLECTION_USERS,
)
from db.indexes import ensure_indexes
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db():
    """Same per-test-loop reset as the unit tests' conftest."""
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    database = await conn_mod.get_database()
    try:
        yield database
    finally:
        await conn_mod.close_connection()


async def _index_names(collection) -> set[str]:
    """Return the set of regular (non-search) index names on a collection."""
    info = await collection.index_information()
    return set(info.keys())


async def _search_index_present(collection, name: str) -> bool:
    try:
        async for idx in collection.list_search_indexes():
            if idx.get("name") == name:
                return True
        return False
    except Exception:
        # Local Mongo without mongot raises here; the index is genuinely absent.
        return False


async def test_ensure_indexes_creates_agent_layer_indexes(db):
    """ensure_indexes() must create every regular index declared for the four new collections."""
    await ensure_indexes(db)

    users_indexes = await _index_names(db[COLLECTION_USERS])
    # _id_ is always there. The others are listed by the field they cover.
    # Mongo names compound indexes like "user_id_1" or "email_1", etc.
    assert any("user_id" in n for n in users_indexes), users_indexes
    assert any("email" in n for n in users_indexes), users_indexes

    keys_indexes = await _index_names(db[COLLECTION_USER_API_KEYS])
    assert any("key_hash" in n for n in keys_indexes), keys_indexes
    assert any("key_id" in n for n in keys_indexes), keys_indexes

    sessions_indexes = await _index_names(db[COLLECTION_AGENT_SESSIONS])
    assert any("session_id" in n for n in sessions_indexes), sessions_indexes
    # TTL index on expires_at
    assert any("expires_at" in n for n in sessions_indexes), sessions_indexes

    memories_indexes = await _index_names(db[COLLECTION_AGENT_MEMORIES])
    assert any("memory_id" in n for n in memories_indexes), memories_indexes
    assert any("user_id" in n and "namespace" in n for n in memories_indexes), memories_indexes
    assert any("expires_at" in n for n in memories_indexes), memories_indexes


async def test_agent_memory_search_indexes_attempted(db):
    """If mongot is available, both Atlas Search indexes must be registered.

    On a stock local Mongo without mongot, list_search_indexes() raises and
    the test skips its strong assertion. The non-Atlas case is still covered
    by the warning in `_ensure_agent_memory_*_index` paths.
    """
    await ensure_indexes(db)
    coll = db[COLLECTION_AGENT_MEMORIES]
    try:
        # Trigger one fetch to detect mongot presence; if it raises, skip.
        async for _ in coll.list_search_indexes():
            break
    except Exception:
        pytest.skip("mongot not available — Atlas Search indexes can't be inspected")

    vec_present = await _search_index_present(coll, AGENT_MEMORY_VECTOR_INDEX_NAME)
    lex_present = await _search_index_present(coll, AGENT_MEMORY_LEXICAL_INDEX_NAME)
    # Building Atlas Search indexes is asynchronous in mongot; the wait loop
    # inside ensure_indexes already polled to queryable=True for fresh ones,
    # but on a cold first run we still accept "registered but not yet ready".
    assert vec_present, f"{AGENT_MEMORY_VECTOR_INDEX_NAME} not registered after ensure_indexes"
    assert lex_present, f"{AGENT_MEMORY_LEXICAL_INDEX_NAME} not registered after ensure_indexes"
