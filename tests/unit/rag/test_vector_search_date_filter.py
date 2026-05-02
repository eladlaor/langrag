"""
Unit tests for the date filter clause emitted by vector_search_chunks.

These tests don't talk to MongoDB; they spy on the aggregation pipeline that
the function would run, so we can assert the exact $vectorSearch.filter shape
without a live cluster.
"""

from datetime import UTC, datetime

import pytest

from rag.retrieval.vector_search import vector_search_chunks


class _FakeCursor:
    async def to_list(self, length=None):
        return []


class _SpyCollection:
    def __init__(self):
        self.last_pipeline: list[dict] | None = None

    def aggregate(self, pipeline):
        self.last_pipeline = pipeline
        return _FakeCursor()


@pytest.mark.asyncio
async def test_no_filters_means_no_filter_clause():
    spy = _SpyCollection()
    await vector_search_chunks(spy, query_embedding=[0.0] * 4, top_k=5)
    stage = spy.last_pipeline[0]["$vectorSearch"]
    assert "filter" not in stage


@pytest.mark.asyncio
async def test_date_start_only_filters_source_date_end():
    spy = _SpyCollection()
    ds = datetime(2026, 3, 1, tzinfo=UTC)
    await vector_search_chunks(spy, query_embedding=[0.0] * 4, date_start=ds, top_k=5)
    f = spy.last_pipeline[0]["$vectorSearch"]["filter"]
    assert f["source_date_end"] == {"$gte": ds}
    assert "source_date_start" not in f


@pytest.mark.asyncio
async def test_date_end_only_filters_source_date_start():
    spy = _SpyCollection()
    de = datetime(2026, 3, 31, tzinfo=UTC)
    await vector_search_chunks(spy, query_embedding=[0.0] * 4, date_end=de, top_k=5)
    f = spy.last_pipeline[0]["$vectorSearch"]["filter"]
    assert f["source_date_start"] == {"$lte": de}
    assert "source_date_end" not in f


@pytest.mark.asyncio
async def test_full_window_overlap_clause():
    spy = _SpyCollection()
    ds = datetime(2026, 3, 1, tzinfo=UTC)
    de = datetime(2026, 3, 31, tzinfo=UTC)
    await vector_search_chunks(
        spy, query_embedding=[0.0] * 4,
        content_sources=["newsletter"],
        date_start=ds, date_end=de,
        top_k=5,
    )
    f = spy.last_pipeline[0]["$vectorSearch"]["filter"]
    assert f["content_source"] == {"$in": ["newsletter"]}
    assert f["source_date_start"] == {"$lte": de}
    assert f["source_date_end"] == {"$gte": ds}
