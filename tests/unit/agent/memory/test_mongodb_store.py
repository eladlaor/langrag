"""Tests for the `MongoDBStore` (LangGraph BaseStore over agent_memories)."""

from __future__ import annotations

import pytest

from agent.memory.mongodb_store import MongoDBStore, new_memory_id
from constants import COLLECTION_AGENT_MEMORIES
from custom_types.db_schemas import MemoryNamespace
from custom_types.field_keys import AgentMemoryKeys as Keys
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


def _store(db, fake_embedder) -> MongoDBStore:
    return MongoDBStore(
        collection=db[COLLECTION_AGENT_MEMORIES],
        embedder=fake_embedder,
        embedding_model="fake-embedder-v1",
    )


# ---------------------------------------------------------------------------
# put / get round-trip
# ---------------------------------------------------------------------------


async def test_aput_then_aget_round_trip(db, fake_embedder, unique_user_id):
    store = _store(db, fake_embedder)
    namespace = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    key = new_memory_id()
    try:
        await store.aput(
            namespace,
            key,
            {"content": "user prefers Hebrew newsletters", "importance": 0.9},
        )
        item = await store.aget(namespace, key)
        assert item is not None
        assert item.key == key
        assert item.namespace == namespace
        assert item.value["content"] == "user prefers Hebrew newsletters"
        assert item.value["importance"] == pytest.approx(0.9)
    finally:
        await store.adelete(namespace, key)


async def test_aput_writes_bson_binary_embedding(db, fake_embedder, unique_user_id):
    """The embedding must land as BSON Binary (subtype 9) so Atlas Vector
    Search can serve it. We assert the raw document carries Binary."""
    store = _store(db, fake_embedder)
    namespace = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    key = new_memory_id()
    try:
        await store.aput(namespace, key, {"content": "x"})
        raw = await db[COLLECTION_AGENT_MEMORIES].find_one({Keys.MEMORY_ID: key})
        assert raw is not None
        from bson.binary import Binary

        assert isinstance(raw[Keys.EMBEDDING], Binary)
        assert raw[Keys.EMBEDDING].subtype == 9
    finally:
        await store.adelete(namespace, key)


async def test_aput_requires_content(db, fake_embedder, unique_user_id):
    store = _store(db, fake_embedder)
    namespace = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    with pytest.raises(ValueError, match="content"):
        await store.aput(namespace, new_memory_id(), {})


async def test_aput_rejects_unknown_namespace(db, fake_embedder, unique_user_id):
    store = _store(db, fake_embedder)
    with pytest.raises(ValueError, match="Unknown memory namespace"):
        await store.aput(
            (unique_user_id, "not-a-namespace"),
            new_memory_id(),
            {"content": "x"},
        )


async def test_aput_rejects_short_namespace(db, fake_embedder):
    store = _store(db, fake_embedder)
    with pytest.raises(ValueError, match="user_id, memory_namespace"):
        await store.aput((), new_memory_id(), {"content": "x"})


# ---------------------------------------------------------------------------
# TTL semantics
# ---------------------------------------------------------------------------


async def test_aput_episodic_sets_default_ttl(db, fake_embedder, unique_user_id):
    """Episodic memories get the 30-day TTL by default; semantic + procedural don't."""
    store = _store(db, fake_embedder)
    ep_ns = (unique_user_id, str(MemoryNamespace.EPISODIC))
    sem_ns = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    proc_ns = (unique_user_id, str(MemoryNamespace.PROCEDURAL))
    ep_key, sem_key, proc_key = new_memory_id(), new_memory_id(), new_memory_id()
    try:
        await store.aput(ep_ns, ep_key, {"content": "event A"})
        await store.aput(sem_ns, sem_key, {"content": "fact A"})
        await store.aput(proc_ns, proc_key, {"content": "pattern A"})
        ep_raw = await db[COLLECTION_AGENT_MEMORIES].find_one({Keys.MEMORY_ID: ep_key})
        sem_raw = await db[COLLECTION_AGENT_MEMORIES].find_one({Keys.MEMORY_ID: sem_key})
        proc_raw = await db[COLLECTION_AGENT_MEMORIES].find_one({Keys.MEMORY_ID: proc_key})
        assert ep_raw[Keys.EXPIRES_AT] is not None
        assert sem_raw[Keys.EXPIRES_AT] is None
        assert proc_raw[Keys.EXPIRES_AT] is None
    finally:
        for ns, k in [(ep_ns, ep_key), (sem_ns, sem_key), (proc_ns, proc_key)]:
            await store.adelete(ns, k)


async def test_aput_explicit_ttl_overrides_default(db, fake_embedder, unique_user_id):
    store = _store(db, fake_embedder)
    ns = (unique_user_id, str(MemoryNamespace.EPISODIC))
    key = new_memory_id()
    try:
        await store.aput(ns, key, {"content": "x", "ttl_days": 7})
        raw = await db[COLLECTION_AGENT_MEMORIES].find_one({Keys.MEMORY_ID: key})
        from datetime import datetime, timedelta

        delta = raw[Keys.EXPIRES_AT] - datetime.utcnow()
        assert timedelta(days=6) < delta < timedelta(days=8)
    finally:
        await store.adelete(ns, key)


# ---------------------------------------------------------------------------
# Cross-user isolation (the multi-tenancy guarantee)
# ---------------------------------------------------------------------------


async def test_aget_does_not_cross_users(db, fake_embedder, unique_user_id, other_user_id):
    store = _store(db, fake_embedder)
    mine_ns = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    theirs_ns = (other_user_id, str(MemoryNamespace.SEMANTIC))
    mine_key = new_memory_id()
    theirs_key = new_memory_id()
    try:
        await store.aput(mine_ns, mine_key, {"content": "mine"})
        await store.aput(theirs_ns, theirs_key, {"content": "theirs"})
        # Reading the other user's key under MY namespace must return None.
        leak = await store.aget(mine_ns, theirs_key)
        assert leak is None
    finally:
        await store.adelete(mine_ns, mine_key)
        await store.adelete(theirs_ns, theirs_key)


async def test_adelete_does_not_cross_users(db, fake_embedder, unique_user_id, other_user_id):
    store = _store(db, fake_embedder)
    mine_ns = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    theirs_ns = (other_user_id, str(MemoryNamespace.SEMANTIC))
    mine_key = new_memory_id()
    theirs_key = new_memory_id()
    try:
        await store.aput(mine_ns, mine_key, {"content": "mine"})
        await store.aput(theirs_ns, theirs_key, {"content": "theirs"})
        # Trying to delete theirs from MY namespace is a no-op.
        await store.adelete(mine_ns, theirs_key)
        # Their record is still there.
        their_row = await db[COLLECTION_AGENT_MEMORIES].find_one(
            {Keys.MEMORY_ID: theirs_key},
        )
        assert their_row is not None
    finally:
        await store.adelete(mine_ns, mine_key)
        await store.adelete(theirs_ns, theirs_key)


async def test_asearch_requires_user_id_prefix(db, fake_embedder):
    store = _store(db, fake_embedder)
    with pytest.raises(ValueError, match="namespace_prefix"):
        await store.asearch((), query="x")


# ---------------------------------------------------------------------------
# alist_namespaces
# ---------------------------------------------------------------------------


async def test_alist_namespaces_returns_pairs(db, fake_embedder, unique_user_id):
    store = _store(db, fake_embedder)
    sem_ns = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    ep_ns = (unique_user_id, str(MemoryNamespace.EPISODIC))
    sem_key = new_memory_id()
    ep_key = new_memory_id()
    try:
        await store.aput(sem_ns, sem_key, {"content": "x"})
        await store.aput(ep_ns, ep_key, {"content": "y"})
        listing = await store.alist_namespaces(prefix=(unique_user_id,))
        assert sem_ns in listing
        assert ep_ns in listing
    finally:
        await store.adelete(sem_ns, sem_key)
        await store.adelete(ep_ns, ep_key)


# ---------------------------------------------------------------------------
# asearch without query (degraded "list recent" path)
# ---------------------------------------------------------------------------


async def test_asearch_without_query_lists_recent(db, fake_embedder, unique_user_id):
    """asearch with query=None must fall back to a recent-first list scoped
    to the prefix's user_id (no cross-tenant leakage)."""
    store = _store(db, fake_embedder)
    sem_ns = (unique_user_id, str(MemoryNamespace.SEMANTIC))
    keys = [new_memory_id() for _ in range(3)]
    try:
        for k, content in zip(keys, ["a", "b", "c"]):
            await store.aput(sem_ns, k, {"content": content})
        items = await store.asearch((unique_user_id,), limit=10)
        keys_back = {item.key for item in items}
        assert set(keys) <= keys_back
    finally:
        for k in keys:
            await store.adelete(sem_ns, k)
