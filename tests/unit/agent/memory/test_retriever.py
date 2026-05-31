"""Tests for `load_relevant_memories`.

Uses a fake store that records calls and returns scripted SearchItems.
Validates dedupe, per-namespace querying, and the user_id requirement.
No MongoDB needed.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.store.base import SearchItem

from agent.memory.retriever import load_relevant_memories
from custom_types.db_schemas import MemoryNamespace

pytestmark = [pytest.mark.asyncio]


def _search_item(key: str, score: float, ns: str, content: str = "c") -> SearchItem:
    return SearchItem(
        value={"content": content},
        key=key,
        namespace=("u1", ns),
        created_at=None,
        updated_at=None,
        score=score,
    )


class FakeStore:
    def __init__(self, results_by_namespace: dict[str, list[SearchItem]]) -> None:
        self.results = results_by_namespace
        self.calls: list[dict[str, Any]] = []

    async def asearch(self, namespace_prefix, /, *, query=None, limit=10, **kwargs):
        self.calls.append(
            {"prefix": namespace_prefix, "query": query, "limit": limit}
        )
        ns = namespace_prefix[1] if len(namespace_prefix) > 1 else "*"
        return self.results.get(ns, [])


# ---------------------------------------------------------------------------


async def test_empty_user_id_rejected():
    with pytest.raises(ValueError, match="user_id"):
        await load_relevant_memories(FakeStore({}), "", "q")  # type: ignore[arg-type]


async def test_empty_query_returns_empty():
    """Without a query, the retriever short-circuits (don't load everything)."""
    store = FakeStore({})
    out = await load_relevant_memories(store, "u1", "")  # type: ignore[arg-type]
    assert out == []
    assert store.calls == []


async def test_queries_all_three_namespaces_by_default():
    store = FakeStore(
        {
            str(MemoryNamespace.SEMANTIC): [_search_item("s1", 0.9, "semantic")],
            str(MemoryNamespace.EPISODIC): [_search_item("e1", 0.5, "episodic")],
            str(MemoryNamespace.PROCEDURAL): [_search_item("p1", 0.7, "procedural")],
        }
    )
    out = await load_relevant_memories(store, "u1", "what do you know about me")  # type: ignore[arg-type]
    namespaces_queried = {c["prefix"][1] for c in store.calls}
    assert namespaces_queried == {
        str(MemoryNamespace.SEMANTIC),
        str(MemoryNamespace.EPISODIC),
        str(MemoryNamespace.PROCEDURAL),
    }
    assert len(out) == 3
    # Sorted by score desc
    assert [m["_memory_id"] for m in out] == ["s1", "p1", "e1"]
    assert out[0]["_namespace"] == "semantic"
    assert out[0]["_score"] == pytest.approx(0.9)


async def test_namespace_restriction():
    store = FakeStore(
        {
            str(MemoryNamespace.SEMANTIC): [_search_item("s1", 0.9, "semantic")],
            str(MemoryNamespace.EPISODIC): [_search_item("e1", 0.5, "episodic")],
        }
    )
    out = await load_relevant_memories(
        store,  # type: ignore[arg-type]
        "u1",
        "q",
        namespaces=[MemoryNamespace.SEMANTIC],
    )
    assert {c["prefix"][1] for c in store.calls} == {str(MemoryNamespace.SEMANTIC)}
    assert [m["_memory_id"] for m in out] == ["s1"]


async def test_dedupes_by_key_across_namespaces():
    """If the same memory_id somehow surfaces from two namespaces, dedupe."""
    store = FakeStore(
        {
            str(MemoryNamespace.SEMANTIC): [_search_item("k1", 0.9, "semantic")],
            str(MemoryNamespace.EPISODIC): [_search_item("k1", 0.5, "episodic")],
        }
    )
    out = await load_relevant_memories(store, "u1", "q")  # type: ignore[arg-type]
    assert len(out) == 1
    # First occurrence wins (semantic, score 0.9)
    assert out[0]["_namespace"] == "semantic"
    assert out[0]["_score"] == pytest.approx(0.9)


async def test_top_k_limits_total_output():
    store = FakeStore(
        {
            str(MemoryNamespace.SEMANTIC): [
                _search_item(f"s{i}", 0.9 - i * 0.01, "semantic")
                for i in range(10)
            ],
            str(MemoryNamespace.EPISODIC): [
                _search_item(f"e{i}", 0.5 - i * 0.01, "episodic")
                for i in range(10)
            ],
            str(MemoryNamespace.PROCEDURAL): [
                _search_item(f"p{i}", 0.7 - i * 0.01, "procedural")
                for i in range(10)
            ],
        }
    )
    out = await load_relevant_memories(store, "u1", "q", top_k=5)  # type: ignore[arg-type]
    assert len(out) == 5
    # Scores must be sorted desc
    scores = [m["_score"] for m in out]
    assert scores == sorted(scores, reverse=True)
