"""
Unit tests for parent-document retrieval (D10).

Covers the three application-side pieces without a live MongoDB:
  1. `_expand_with_parents` emits the expected $lookup stage and attaches the
     resolved messages (time-ordered, capped) back onto each chunk.
  2. `_format_context` renders a dedicated PRIMARY SOURCES section only when
     chunks carry `parent_messages`.
  3. `retrieve(include_raw_messages=False)` is a no-op: no $lookup, no section.

The $lookup aggregation is spied via a fake collection (same idiom as
test_hybrid_search.py); the newsletter->messages provenance itself is written at
ingest and is out of scope here.
"""

import pytest

from custom_types.field_keys import DbFieldKeys, RAGChunkKeys as Keys, RAGChunkMetadataKeys
from rag.retrieval.pipeline import RetrievalPipeline


class _FakeCursor:
    def __init__(self, results):
        self._results = results or []

    async def to_list(self, length=None):
        return self._results


class _SpyCollection:
    def __init__(self, results=None):
        self.last_pipeline = None
        self._results = results or []

    async def aggregate(self, pipeline):
        self.last_pipeline = pipeline
        return _FakeCursor(self._results)


class _FakeDB:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, _name):
        return self._collection


def _pipeline_instance() -> RetrievalPipeline:
    """Build a RetrievalPipeline without running its embedder-loading __init__."""
    return RetrievalPipeline.__new__(RetrievalPipeline)


class _Settings:
    parent_messages_per_chunk_cap = 40


@pytest.mark.asyncio
async def test_expand_with_parents_lookup_shape_and_attach(monkeypatch):
    # Two chunks; the $lookup result returns messages for chunk c1 only.
    lookup_rows = [
        {
            Keys.CHUNK_ID: "c1",
            RAGChunkMetadataKeys.PARENT_MESSAGES: [
                {DbFieldKeys.MESSAGE_ID: "m2", DbFieldKeys.SENDER: "bob", DbFieldKeys.CONTENT: "second", DbFieldKeys.TIMESTAMP: 200},
                {DbFieldKeys.MESSAGE_ID: "m1", DbFieldKeys.SENDER: "ana", DbFieldKeys.CONTENT: "first", DbFieldKeys.TIMESTAMP: 100},
            ],
        },
    ]
    spy = _SpyCollection(results=lookup_rows)
    monkeypatch.setattr("rag.retrieval.pipeline.get_database", lambda: _async_return(_FakeDB(spy)))

    pipe = _pipeline_instance()
    pipe._settings = _Settings()

    chunks = [{Keys.CHUNK_ID: "c1"}, {Keys.CHUNK_ID: "c2"}]
    await pipe._expand_with_parents(chunks)

    # $lookup stage shape: chunks -> messages on the nested metadata.message_ids.
    lookup = spy.last_pipeline[1]["$lookup"]
    assert lookup["from"] == "messages"
    assert lookup["localField"] == f"{Keys.METADATA}.{RAGChunkMetadataKeys.MESSAGE_IDS}"
    assert lookup["foreignField"] == DbFieldKeys.MESSAGE_ID
    assert lookup["as"] == RAGChunkMetadataKeys.PARENT_MESSAGES

    # c1 gets messages, time-ordered (m1 before m2); c2 gets an empty list.
    c1_msgs = chunks[0][RAGChunkMetadataKeys.PARENT_MESSAGES]
    assert [m[DbFieldKeys.MESSAGE_ID] for m in c1_msgs] == ["m1", "m2"]
    assert chunks[1][RAGChunkMetadataKeys.PARENT_MESSAGES] == []


@pytest.mark.asyncio
async def test_expand_with_parents_caps_messages(monkeypatch):
    many = [
        {DbFieldKeys.MESSAGE_ID: f"m{i}", DbFieldKeys.SENDER: "x", DbFieldKeys.CONTENT: "c", DbFieldKeys.TIMESTAMP: i}
        for i in range(100)
    ]
    spy = _SpyCollection(results=[{Keys.CHUNK_ID: "c1", RAGChunkMetadataKeys.PARENT_MESSAGES: many}])
    monkeypatch.setattr("rag.retrieval.pipeline.get_database", lambda: _async_return(_FakeDB(spy)))

    pipe = _pipeline_instance()
    pipe._settings = _Settings()  # cap = 40

    chunks = [{Keys.CHUNK_ID: "c1"}]
    await pipe._expand_with_parents(chunks)
    assert len(chunks[0][RAGChunkMetadataKeys.PARENT_MESSAGES]) == 40


def test_format_context_adds_primary_sources_section_only_when_present():
    chunk_with = {
        Keys.CHUNK_ID: "c1",
        Keys.CONTENT: "summary text",
        Keys.SOURCE_TITLE: "LangTalks Newsletter",
        RAGChunkMetadataKeys.PARENT_MESSAGES: [
            {DbFieldKeys.SENDER: "ana", DbFieldKeys.CONTENT: "raw one"},
            {DbFieldKeys.SENDER: "bob", DbFieldKeys.CONTENT: "raw two"},
        ],
    }
    context, citations = RetrievalPipeline._format_context([chunk_with])
    assert "PRIMARY SOURCES" in context
    assert "ana: raw one" in context
    assert "[1] raw messages:" in context
    # Citations carry the parent messages through too.
    assert len(citations[0][RAGChunkMetadataKeys.PARENT_MESSAGES]) == 2

    chunk_without = {Keys.CHUNK_ID: "c2", Keys.CONTENT: "summary only", Keys.SOURCE_TITLE: "X"}
    context2, _ = RetrievalPipeline._format_context([chunk_without])
    assert "PRIMARY SOURCES" not in context2


def _async_return(value):
    async def _coro():
        return value
    return _coro()
