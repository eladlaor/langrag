"""Tests for AgentMemoriesRepository (agentic chatbot layer)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_types.db_schemas import MemoryNamespace
from custom_types.field_keys import AgentMemoryKeys
from db.repositories.agent_memories import AgentMemoriesRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


# A small placeholder "embedding". The real index expects BSON Binary subtype
# 9; for the repository round-trip we only care that the value survives the
# insert/fetch cycle, so a plain list is fine here. Vector search itself is
# exercised in commit 4 (MongoDBStore tests).
def _dummy_embedding() -> list[float]:
    return [0.0] * 16


async def test_create_memory_persistent(db, unique_user_id):
    repo = AgentMemoriesRepository(db)
    memory_id = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.SEMANTIC,
        content="user prefers Hebrew newsletters",
        embedding=_dummy_embedding(),
        embedding_model="text-embedding-3-small",
        importance=0.9,
        metadata={"community_key": "mcp_israel"},
    )
    try:
        row = await repo.find_by_memory_id(memory_id)
        assert row is not None
        assert row[AgentMemoryKeys.USER_ID] == unique_user_id
        assert row[AgentMemoryKeys.NAMESPACE] == str(MemoryNamespace.SEMANTIC)
        assert row[AgentMemoryKeys.EXPIRES_AT] is None, "semantic must not set TTL"
        assert row[AgentMemoryKeys.IMPORTANCE] == pytest.approx(0.9)
    finally:
        await repo.delete_memory(unique_user_id, memory_id)


async def test_create_memory_episodic_sets_ttl(db, unique_user_id):
    repo = AgentMemoriesRepository(db)
    memory_id = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.EPISODIC,
        content="on 2026-05-28 user rejected the first draft",
        embedding=_dummy_embedding(),
        embedding_model="text-embedding-3-small",
        ttl_days=AgentMemoriesRepository.episodic_ttl_days(),
    )
    try:
        row = await repo.find_by_memory_id(memory_id)
        assert row[AgentMemoryKeys.EXPIRES_AT] is not None
        # Mongo returns naive UTC datetimes; compare against naive now()
        delta = row[AgentMemoryKeys.EXPIRES_AT] - datetime.utcnow()
        assert timedelta(days=29) < delta < timedelta(days=31)
    finally:
        await repo.delete_memory(unique_user_id, memory_id)


async def test_list_for_user_strips_embedding(db, unique_user_id):
    repo = AgentMemoriesRepository(db)
    m1 = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.SEMANTIC,
        content="memory 1",
        embedding=_dummy_embedding(),
        embedding_model="m",
    )
    try:
        listing = await repo.list_for_user(unique_user_id)
        assert any(r[AgentMemoryKeys.MEMORY_ID] == m1 for r in listing)
        for r in listing:
            assert AgentMemoryKeys.EMBEDDING not in r
    finally:
        await repo.delete_memory(unique_user_id, m1)


async def test_cross_user_isolation_on_delete(db, unique_user_id):
    """Deleting under user A must NOT delete memories owned by user B."""
    other_user = unique_user_id + "-other"
    repo = AgentMemoriesRepository(db)
    mine = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.SEMANTIC,
        content="mine",
        embedding=_dummy_embedding(),
        embedding_model="m",
    )
    theirs = await repo.create_memory(
        user_id=other_user,
        namespace=MemoryNamespace.SEMANTIC,
        content="theirs",
        embedding=_dummy_embedding(),
        embedding_model="m",
    )
    try:
        # Try to delete the other user's memory under MY user_id; must be a no-op.
        deleted = await repo.delete_memory(unique_user_id, theirs)
        assert deleted is False
        # Their memory is still there.
        assert await repo.find_by_memory_id(theirs) is not None
        # Mine is also still there.
        assert await repo.find_by_memory_id(mine) is not None
    finally:
        await repo.delete_memory(unique_user_id, mine)
        await repo.delete_memory(other_user, theirs)


async def test_delete_all_for_user(db, unique_user_id):
    repo = AgentMemoriesRepository(db)
    m1 = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.SEMANTIC,
        content="a",
        embedding=_dummy_embedding(),
        embedding_model="m",
    )
    m2 = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.EPISODIC,
        content="b",
        embedding=_dummy_embedding(),
        embedding_model="m",
        ttl_days=30,
    )
    try:
        count = await repo.delete_all_for_user(unique_user_id)
        assert count >= 2
        assert await repo.find_by_memory_id(m1) is None
        assert await repo.find_by_memory_id(m2) is None
    finally:
        # idempotent cleanup
        await repo.delete_memory(unique_user_id, m1)
        await repo.delete_memory(unique_user_id, m2)


async def test_touch_access_increments_count(db, unique_user_id):
    repo = AgentMemoriesRepository(db)
    memory_id = await repo.create_memory(
        user_id=unique_user_id,
        namespace=MemoryNamespace.PROCEDURAL,
        content="x",
        embedding=_dummy_embedding(),
        embedding_model="m",
    )
    try:
        before = await repo.find_by_memory_id(memory_id)
        assert before[AgentMemoryKeys.ACCESS_COUNT] == 0
        await repo.touch_access(memory_id)
        after = await repo.find_by_memory_id(memory_id)
        assert after[AgentMemoryKeys.ACCESS_COUNT] == 1
        assert after[AgentMemoryKeys.LAST_ACCESSED_AT] is not None
    finally:
        await repo.delete_memory(unique_user_id, memory_id)
