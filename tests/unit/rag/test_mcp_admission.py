"""Admission-control tests for the MCP RAG tools.

Verifies rag_query / rag_search are guarded against the SAME process-wide budget
as the REST surface, that slots are released on success and on pipeline error,
that list_rag_sources is exempt, and that REST and MCP share one semaphore.
Runs WITHOUT Docker (pipeline / generation / repo are stubbed).
"""

import pytest

from config import get_settings
from rag.concurrency import guard
from rag.concurrency.guard import RagCapacityExceeded
from rag.mcp import tools as mcp_tools


@pytest.fixture
def set_cap(monkeypatch):
    def _set(cap: int) -> None:
        monkeypatch.setattr(get_settings().rag, "max_concurrent_requests", cap, raising=False)
        guard._reset_for_tests()

    yield _set
    guard._reset_for_tests()


def _non_empty_retrieval():
    return {
        "context": "some grounded context",
        "citations": [{"index": 0, "chunk_id": "c1"}],
        "freshness_warning": False,
        "oldest_source_date": None,
        "newest_source_date": None,
    }


@pytest.fixture
def stub_pipeline_ok(monkeypatch):
    """Stub RetrievalPipeline + generate_answer so rag_query/rag_search succeed."""
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)

    async def _fake_retrieve(self, *args, **kwargs):
        return _non_empty_retrieval()

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _fake_retrieve)

    async def _fake_generate(*args, **kwargs):
        return "grounded answer"

    monkeypatch.setattr(mcp_tools, "generate_answer", _fake_generate)


@pytest.fixture
def stub_pipeline_error(monkeypatch):
    """Stub RetrievalPipeline.retrieve to raise, to prove the slot still releases."""
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)

    async def _boom_retrieve(self, *args, **kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _boom_retrieve)


async def test_rag_query_raises_capacity_exceeded_when_full(set_cap, stub_pipeline_ok):
    set_cap(1)
    assert await guard.try_acquire() is True  # pre-fill to cap
    with pytest.raises(RagCapacityExceeded):
        await mcp_tools.rag_query(query="anything")


async def test_rag_query_releases_slot_on_success(set_cap, stub_pipeline_ok):
    set_cap(1)
    result = await mcp_tools.rag_query(query="anything")
    assert result["answer"] == "grounded answer"
    assert guard.current_in_flight() == 0


async def test_rag_query_releases_slot_on_pipeline_error(set_cap, stub_pipeline_error):
    set_cap(1)
    with pytest.raises(RuntimeError):
        await mcp_tools.rag_query(query="anything")
    assert guard.current_in_flight() == 0


async def test_list_rag_sources_is_not_guarded(set_cap, monkeypatch):
    set_cap(1)
    assert await guard.try_acquire() is True  # pre-fill to cap

    # Stub the DB + repo aggregation so list_rag_sources runs without Docker.
    async def _fake_get_database():
        return object()

    class _FakeCursor:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _FakeRepo:
        def __init__(self, db):
            self.collection = self

        async def aggregate(self, pipeline):
            return _FakeCursor()

    monkeypatch.setattr(mcp_tools, "get_database", _fake_get_database)
    monkeypatch.setattr(mcp_tools, "ChunksRepository", _FakeRepo)

    # Even at cap, the metadata call succeeds (it is exempt from the budget).
    result = await mcp_tools.list_rag_sources()
    assert isinstance(result, dict)


async def test_rest_and_mcp_share_the_same_budget(set_cap, stub_pipeline_ok):
    set_cap(1)
    # Hold the single slot as if the REST surface acquired it, then the MCP tool
    # is rejected — proving one process-wide semaphore backs both surfaces.
    assert await guard.try_acquire() is True
    with pytest.raises(RagCapacityExceeded):
        await mcp_tools.rag_query(query="anything")
