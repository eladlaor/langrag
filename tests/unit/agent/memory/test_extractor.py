"""Tests for `extract_and_persist_memories`.

The extractor is exercised against a fake LLM that returns scripted JSON
and an in-memory fake store. No MongoDB needed for these tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.memory.extractor import (
    DEFAULT_IMPORTANCE_THRESHOLD,
    extract_and_persist_memories,
)
from custom_types.db_schemas import MemoryNamespace

pytestmark = [pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeLLMResponse:
    content: str


class FakeLLM:
    """Returns a queued response on each `ainvoke` call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[Any] = []

    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        self.calls.append(input)
        if not self._responses:
            return _FakeLLMResponse(content="[]")
        return _FakeLLMResponse(content=self._responses.pop(0))


class FakeStore:
    """In-memory stand-in for `MongoDBStore` used by the extractor.

    The extractor only ever calls `aput`, so that's all we model.
    """

    def __init__(self) -> None:
        self.writes: list[tuple[tuple[str, ...], str, dict]] = []

    async def aput(self, namespace, key, value, index=None, *, ttl=None):
        self.writes.append((namespace, key, dict(value)))


def _exchange() -> list:
    return [
        HumanMessage(content="Run this week's newsletter for MCP Israel in Hebrew."),
        AIMessage(content="Generating MCP Israel for the last 7 days in Hebrew."),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_persists_items_above_threshold():
    """One high-importance memory persists; one below-threshold is dropped."""
    llm_json = """[
        {"namespace": "semantic", "content": "user prefers Hebrew newsletters", "importance": 0.9},
        {"namespace": "semantic", "content": "greeted the agent", "importance": 0.1}
    ]"""
    llm = FakeLLM([llm_json])
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=llm,
        store=store,
    )
    assert len(persisted) == 1
    assert len(store.writes) == 1
    ns, key, value = store.writes[0]
    assert ns == ("u1", str(MemoryNamespace.SEMANTIC))
    assert value["content"] == "user prefers Hebrew newsletters"
    assert value["importance"] == pytest.approx(0.9)


async def test_threshold_is_inclusive_below_only():
    """Items exactly at the threshold ARE kept (the cutoff is strict <)."""
    llm_json = (
        f'[{{"namespace": "semantic", "content": "x", '
        f'"importance": {DEFAULT_IMPORTANCE_THRESHOLD}}}]'
    )
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_json]),
        store=store,
    )
    assert len(persisted) == 1


async def test_episodic_with_ttl_days_is_carried_through():
    llm_json = """[
        {"namespace": "episodic", "content": "user rejected the first draft",
         "importance": 0.8, "ttl_days": 7}
    ]"""
    store = FakeStore()
    await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_json]),
        store=store,
    )
    assert len(store.writes) == 1
    _, _, value = store.writes[0]
    assert value.get("ttl_days") == 7


async def test_ttl_days_ignored_for_semantic():
    """ttl_days should only land on episodic memories — semantic must persist."""
    llm_json = """[
        {"namespace": "semantic", "content": "x", "importance": 0.9, "ttl_days": 1}
    ]"""
    store = FakeStore()
    await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_json]),
        store=store,
    )
    _, _, value = store.writes[0]
    assert "ttl_days" not in value


async def test_empty_array_writes_nothing():
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM(["[]"]),
        store=store,
    )
    assert persisted == []
    assert store.writes == []


async def test_handles_markdown_fenced_json():
    llm_response = """```json
[
  {"namespace": "semantic", "content": "x", "importance": 0.9}
]
```"""
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_response]),
        store=store,
    )
    assert len(persisted) == 1


async def test_unknown_namespace_is_skipped():
    """An LLM emitting an unknown namespace should not crash the turn."""
    llm_json = """[
        {"namespace": "totally-made-up", "content": "x", "importance": 0.9},
        {"namespace": "semantic", "content": "valid", "importance": 0.9}
    ]"""
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_json]),
        store=store,
    )
    assert len(persisted) == 1
    _, _, value = store.writes[0]
    assert value["content"] == "valid"


async def test_missing_content_is_skipped():
    llm_json = """[
        {"namespace": "semantic", "importance": 0.9},
        {"namespace": "semantic", "content": "ok", "importance": 0.9}
    ]"""
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_json]),
        store=store,
    )
    assert len(persisted) == 1


async def test_invalid_json_returns_empty():
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM(["this is not json at all"]),
        store=store,
    )
    assert persisted == []


async def test_empty_exchange_returns_empty():
    store = FakeStore()
    persisted = await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=[],
        llm=FakeLLM(["[]"]),
        store=store,
    )
    # LLM must not even be called on an empty exchange.
    assert persisted == []
    assert store.writes == []


async def test_user_id_required():
    with pytest.raises(ValueError, match="user_id"):
        await extract_and_persist_memories(
            user_id="",
            recent_exchange=_exchange(),
            llm=FakeLLM(["[]"]),
            store=FakeStore(),
        )


async def test_community_context_stamped_on_metadata():
    llm_json = """[{"namespace": "semantic", "content": "x", "importance": 0.9}]"""
    store = FakeStore()
    await extract_and_persist_memories(
        user_id="u1",
        recent_exchange=_exchange(),
        llm=FakeLLM([llm_json]),
        store=store,
        community_context="mcp_israel",
    )
    _, _, value = store.writes[0]
    assert value["metadata"]["community_key"] == "mcp_israel"
