"""Tests for the memory tools (remember / forget / list_memories).

Use a fake store so we exercise the tool wiring without standing up
MongoDB. The real `MongoDBStore` tests are in tests/unit/agent/memory/.
"""

from __future__ import annotations

import pytest
from langgraph.store.base import SearchItem

from agent.auth.user_context import UserContext, user_context
from agent.tools.memory_tools import build_memory_tools
from custom_types.db_schemas import MemoryNamespace

pytestmark = [pytest.mark.asyncio]


class FakeStore:
    def __init__(self) -> None:
        self.puts: list = []
        self.deletes: list = []
        self.search_returns: list[SearchItem] = []
        self.last_search_kwargs: dict | None = None

    async def aput(self, namespace, key, value, index=None, *, ttl=None):
        self.puts.append((namespace, key, dict(value)))

    async def adelete(self, namespace, key):
        self.deletes.append((namespace, key))

    async def asearch(self, namespace_prefix, /, *, query=None, limit=10, **kw):
        self.last_search_kwargs = {
            "prefix": namespace_prefix,
            "query": query,
            "limit": limit,
        }
        return list(self.search_returns)


def _ctx() -> UserContext:
    return UserContext(
        user_id="u1",
        email="u1@langrag.test",
        role="admin",
        communities=("mcp_israel",),
    )


def _by_name(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise AssertionError(f"tool not found: {name}")


# ---------------------------------------------------------------------------
# remember
# ---------------------------------------------------------------------------


async def test_remember_persists_with_user_id_from_context():
    """remember reads the user_id from the contextvar (NOT a tool arg)."""
    store = FakeStore()
    tools = build_memory_tools(lambda: store)
    remember = _by_name(tools, "remember")
    with user_context(_ctx()):
        out = await remember.ainvoke(
            {"content": "user prefers Hebrew newsletters", "importance": 0.9}
        )
    assert len(store.puts) == 1
    ns, key, value = store.puts[0]
    assert ns == ("u1", str(MemoryNamespace.SEMANTIC))
    assert value["content"] == "user prefers Hebrew newsletters"
    assert value["importance"] == pytest.approx(0.9)
    assert out["memory_id"] == key
    assert out["namespace"] == "semantic"


async def test_remember_episodic_namespace():
    store = FakeStore()
    tools = build_memory_tools(lambda: store)
    remember = _by_name(tools, "remember")
    with user_context(_ctx()):
        await remember.ainvoke({"content": "x", "namespace": "episodic"})
    ns, _, _ = store.puts[0]
    assert ns == ("u1", str(MemoryNamespace.EPISODIC))


async def test_remember_unknown_namespace_raises():
    store = FakeStore()
    tools = build_memory_tools(lambda: store)
    remember = _by_name(tools, "remember")
    with user_context(_ctx()):
        with pytest.raises(ValueError, match="Unknown memory namespace"):
            await remember.ainvoke({"content": "x", "namespace": "made-up"})


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


async def test_forget_attempts_delete_across_all_three_namespaces():
    """Without a namespace param, forget asks the store to delete the key
    under each of the three namespaces. The store's own ACL ensures
    nothing happens to other users' rows."""
    store = FakeStore()
    tools = build_memory_tools(lambda: store)
    forget = _by_name(tools, "forget")
    with user_context(_ctx()):
        out = await forget.ainvoke({"memory_id": "m-123"})
    assert out["deleted"] is True
    assert {ns[1] for (ns, _) in store.deletes} == {
        str(MemoryNamespace.SEMANTIC),
        str(MemoryNamespace.EPISODIC),
        str(MemoryNamespace.PROCEDURAL),
    }
    # user_id always matches the contextvar — never accepted from the LLM.
    assert all(ns[0] == "u1" for (ns, _) in store.deletes)


# ---------------------------------------------------------------------------
# list_memories
# ---------------------------------------------------------------------------


async def test_list_memories_returns_summary_payload():
    store = FakeStore()
    store.search_returns = [
        SearchItem(
            value={"content": "user prefers Hebrew", "importance": 0.9},
            key="m1",
            namespace=("u1", str(MemoryNamespace.SEMANTIC)),
            created_at=None,
            updated_at=None,
        ),
    ]
    tools = build_memory_tools(lambda: store)
    list_mem = _by_name(tools, "list_memories")
    with user_context(_ctx()):
        out = await list_mem.ainvoke({"limit": 10})
    assert len(out) == 1
    assert out[0]["memory_id"] == "m1"
    assert out[0]["content"] == "user prefers Hebrew"
    assert out[0]["namespace"] == "semantic"
    # The store was queried with the user_id from the contextvar.
    assert store.last_search_kwargs["prefix"] == ("u1",)


async def test_list_memories_with_namespace_filter():
    store = FakeStore()
    tools = build_memory_tools(lambda: store)
    list_mem = _by_name(tools, "list_memories")
    with user_context(_ctx()):
        await list_mem.ainvoke({"namespace": "episodic", "limit": 5})
    assert store.last_search_kwargs["prefix"] == ("u1", str(MemoryNamespace.EPISODIC))


async def test_list_memories_unknown_namespace_raises():
    store = FakeStore()
    tools = build_memory_tools(lambda: store)
    list_mem = _by_name(tools, "list_memories")
    with user_context(_ctx()):
        with pytest.raises(ValueError, match="Unknown memory namespace"):
            await list_mem.ainvoke({"namespace": "totally-not-a-thing"})
