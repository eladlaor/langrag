"""
Unit tests for the community pre-filter (data_source_name) in retrieval.

Asserts that passing data_source_names pushes a data_source_name filter into
BOTH the vector leg ($vectorSearch.filter) and, for hybrid, the lexical leg
($search compound filter). Spies on the emitted aggregation pipeline; no live
MongoDB. Uses the async-cursor spy idiom (matches the driver's await-aggregate).
"""

import pytest

from custom_types.field_keys import RAGChunkKeys as Keys
from rag.retrieval.vector_search import vector_search_chunks
from rag.retrieval.hybrid_search import hybrid_search_chunks


class _FakeCursor:
    def __init__(self, results=None):
        self._results = results or []

    async def to_list(self, length=None):
        return self._results


class _SpyCollection:
    def __init__(self):
        self.last_pipeline = None

    async def aggregate(self, pipeline):
        self.last_pipeline = pipeline
        return _FakeCursor()


@pytest.mark.asyncio
async def test_vector_leg_community_filter():
    spy = _SpyCollection()
    await vector_search_chunks(
        spy,
        query_embedding=[0.1, 0.2, 0.3, 0.4],
        data_source_names=["langtalks", "mcp_israel"],
        top_k=5,
    )
    flt = spy.last_pipeline[0]["$vectorSearch"]["filter"]
    assert flt[Keys.DATA_SOURCE_NAME] == {"$in": ["langtalks", "mcp_israel"]}


@pytest.mark.asyncio
async def test_no_community_means_no_community_filter():
    spy = _SpyCollection()
    await vector_search_chunks(spy, query_embedding=[0.0] * 4, top_k=5)
    stage = spy.last_pipeline[0]["$vectorSearch"]
    # No filter at all when nothing is passed.
    assert "filter" not in stage


@pytest.mark.asyncio
async def test_hybrid_both_legs_community_filter():
    spy = _SpyCollection()
    await hybrid_search_chunks(
        spy,
        query_text="what is langgraph",
        query_embedding=[0.1, 0.2, 0.3, 0.4],
        data_source_names=["langtalks"],
        top_k=5,
    )
    rank_fusion = spy.last_pipeline[0]["$rankFusion"]
    pipelines = rank_fusion["input"]["pipelines"]

    # Vector leg carries the data_source_name $in filter.
    vector_filter = pipelines["vector"][0]["$vectorSearch"]["filter"]
    assert vector_filter[Keys.DATA_SOURCE_NAME] == {"$in": ["langtalks"]}

    # Lexical leg carries an equivalent compound filter clause.
    lexical_stage = pipelines["lexical"][0]["$search"]
    filter_clauses = lexical_stage["compound"]["filter"]
    assert any(
        c.get("in", {}).get("path") == Keys.DATA_SOURCE_NAME
        and c["in"]["value"] == ["langtalks"]
        for c in filter_clauses
    )
