"""
Unit tests for the $rankFusion hybrid search pipeline shape.

Spies on the aggregation pipeline emitted by hybrid_search_chunks so we can
assert the $rankFusion stage shape, weights, BinData queryVector, and filter
propagation without a live MongoDB 8.1+ cluster.
"""

from datetime import UTC, datetime

import pytest
from bson.binary import Binary

from constants import (
    RAG_HYBRID_LEXICAL_WEIGHT,
    RAG_HYBRID_VECTOR_COSINE_FIELD,
    RAG_HYBRID_VECTOR_WEIGHT,
    RAG_LEXICAL_INDEX_NAME,
    RAG_SEARCH_SCORE_FIELD,
    RAG_VECTOR_INDEX_NAME,
)
from rag.retrieval.hybrid_search import (
    RRF_RAW_SCORE_FIELD,
    _normalize_rrf_scores,
    hybrid_search_chunks,
)


class _FakeCursor:
    def __init__(self, results: list[dict] | None = None):
        self._results = results or []

    async def to_list(self, length=None):
        return self._results


class _SpyCollection:
    def __init__(self, results: list[dict] | None = None):
        self.last_pipeline: list[dict] | None = None
        self._results = results or []

    def aggregate(self, pipeline):
        self.last_pipeline = pipeline
        return _FakeCursor(self._results)


@pytest.mark.asyncio
async def test_rank_fusion_stage_shape():
    spy = _SpyCollection()
    await hybrid_search_chunks(
        spy,
        query_text="what is langgraph",
        query_embedding=[0.1, 0.2, 0.3, 0.4],
        top_k=10,
    )

    rank_fusion = spy.last_pipeline[0]["$rankFusion"]
    pipelines = rank_fusion["input"]["pipelines"]
    assert set(pipelines.keys()) == {"vector", "lexical"}

    vector_stage = pipelines["vector"][0]["$vectorSearch"]
    assert vector_stage["index"] == RAG_VECTOR_INDEX_NAME
    assert isinstance(vector_stage["queryVector"], Binary)
    assert vector_stage["queryVector"].subtype == 9

    lex_search = pipelines["lexical"][0]["$search"]
    assert lex_search["index"] == RAG_LEXICAL_INDEX_NAME
    # No filters provided in this test, so the lexical leg uses a top-level
    # `text` clause rather than the `compound.must` wrapper.
    assert lex_search["text"]["query"] == "what is langgraph"

    weights = rank_fusion["combination"]["weights"]
    assert weights["vector"] == RAG_HYBRID_VECTOR_WEIGHT
    assert weights["lexical"] == RAG_HYBRID_LEXICAL_WEIGHT


@pytest.mark.asyncio
async def test_rank_fusion_filter_propagation():
    spy = _SpyCollection()
    ds = datetime(2026, 3, 1, tzinfo=UTC)
    de = datetime(2026, 3, 31, tzinfo=UTC)
    await hybrid_search_chunks(
        spy,
        query_text="podcast about agents",
        query_embedding=[0.0] * 4,
        content_sources=["podcast"],
        date_start=ds,
        date_end=de,
        top_k=8,
    )

    pipelines = spy.last_pipeline[0]["$rankFusion"]["input"]["pipelines"]

    vector_filter = pipelines["vector"][0]["$vectorSearch"]["filter"]
    assert vector_filter["content_source"] == {"$in": ["podcast"]}
    assert vector_filter["source_date_start"] == {"$lte": de}
    assert vector_filter["source_date_end"] == {"$gte": ds}

    # Lexical leg now pushes filters into $search.compound.filter so mongot
    # prunes non-matching docs before Lucene scoring, instead of a downstream
    # $match. The pipeline shape is [$search, $limit] — no separate $match.
    lex_stage = pipelines["lexical"][0]["$search"]
    assert lex_stage["compound"]["must"][0]["text"]["query"] == "podcast about agents"
    filter_clauses = lex_stage["compound"]["filter"]
    in_clause = next(c["in"] for c in filter_clauses if "in" in c)
    assert in_clause == {"path": "content_source", "value": ["podcast"]}
    range_clauses = [c["range"] for c in filter_clauses if "range" in c]
    assert {"path": "source_date_start", "lte": de} in range_clauses
    assert {"path": "source_date_end", "gte": ds} in range_clauses
    assert all("$match" not in stage for stage in pipelines["lexical"])


@pytest.mark.asyncio
async def test_lexical_leg_has_bounded_limit():
    """The lexical leg must cap the candidate set or it can return the whole
    Atlas Search corpus per query."""
    spy = _SpyCollection()
    await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=7
    )
    lexical = spy.last_pipeline[0]["$rankFusion"]["input"]["pipelines"]["lexical"]
    limits = [stage["$limit"] for stage in lexical if "$limit" in stage]
    assert limits == [28]  # top_k * 4


@pytest.mark.asyncio
async def test_num_candidates_capped():
    """numCandidates must be bounded to avoid Atlas Search ceiling errors at
    high top_k."""
    spy = _SpyCollection()
    await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=100
    )
    vector_stage = (
        spy.last_pipeline[0]["$rankFusion"]["input"]["pipelines"]["vector"][0]["$vectorSearch"]
    )
    assert vector_stage["numCandidates"] == 1000


@pytest.mark.asyncio
async def test_score_details_off_by_default():
    """scoreDetails has non-trivial query cost; it must be opt-in."""
    spy = _SpyCollection()
    await hybrid_search_chunks(spy, query_text="x", query_embedding=[0.0] * 4, top_k=5)
    rank_fusion = spy.last_pipeline[0]["$rankFusion"]
    assert "scoreDetails" not in rank_fusion


@pytest.mark.asyncio
async def test_score_details_can_be_enabled():
    spy = _SpyCollection()
    await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=5, debug_score_details=True
    )
    rank_fusion = spy.last_pipeline[0]["$rankFusion"]
    assert rank_fusion["scoreDetails"] is True


@pytest.mark.asyncio
async def test_rrf_scores_normalized_to_unit_range():
    """The raw RRF score is in ~[0, 0.03]; MMR rerank expects a relevance term
    on the same scale as cosine (0..1). hybrid_search must normalize."""
    fake_results = [
        {"chunk_id": "a", RRF_RAW_SCORE_FIELD: 0.030},
        {"chunk_id": "b", RRF_RAW_SCORE_FIELD: 0.015},
        {"chunk_id": "c", RRF_RAW_SCORE_FIELD: 0.005},
    ]
    spy = _SpyCollection(results=fake_results)
    out = await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=3
    )
    scores = [r[RAG_SEARCH_SCORE_FIELD] for r in out]
    assert scores[0] == 1.0
    assert scores[-1] == 0.0
    assert 0.0 < scores[1] < 1.0
    # Raw RRF score preserved for debugging.
    assert all(RRF_RAW_SCORE_FIELD in r for r in out)


@pytest.mark.asyncio
async def test_rrf_normalization_handles_all_equal_scores():
    """If every chunk has the same raw RRF score, normalization must NOT
    collapse relevance to zero (which would break MMR)."""
    fake_results = [
        {"chunk_id": "a", RRF_RAW_SCORE_FIELD: 0.010},
        {"chunk_id": "b", RRF_RAW_SCORE_FIELD: 0.010},
    ]
    spy = _SpyCollection(results=fake_results)
    out = await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=2
    )
    assert [r[RAG_SEARCH_SCORE_FIELD] for r in out] == [1.0, 1.0]


def test_normalize_rrf_scores_empty_list_is_noop():
    """Empty result page must not raise on normalization."""
    results: list[dict] = []
    _normalize_rrf_scores(results)
    assert results == []


def test_normalize_rrf_scores_preserves_legitimate_zero_raw_score():
    """A raw RRF score of exactly 0.0 must NOT be masked into the default;
    it should normalize relative to the rest of the page like any other value."""
    results = [
        {"chunk_id": "a", RRF_RAW_SCORE_FIELD: 0.0},
        {"chunk_id": "b", RRF_RAW_SCORE_FIELD: 0.02},
    ]
    _normalize_rrf_scores(results)
    assert results[0][RAG_SEARCH_SCORE_FIELD] == 0.0
    assert results[1][RAG_SEARCH_SCORE_FIELD] == 1.0


class _RaisingCollection:
    """Spy that simulates a mongot failure on the aggregation call."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def aggregate(self, pipeline):
        raise self._exc


@pytest.mark.asyncio
async def test_vector_leg_captures_cosine_for_relevance_floor():
    """The vector leg must capture $meta:vectorSearchScore right after
    $vectorSearch so the cosine survives $rankFusion and a relevance floor can
    be applied. $rankFusion fuses ranks, so the fused score alone cannot express
    'everything is irrelevant'."""
    spy = _SpyCollection()
    await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=5, min_vector_score=0.5
    )
    vector_leg = spy.last_pipeline[0]["$rankFusion"]["input"]["pipelines"]["vector"]
    # [$vectorSearch, $addFields(cosine)]
    assert "$vectorSearch" in vector_leg[0]
    add_fields = vector_leg[1]["$addFields"]
    assert add_fields[RAG_HYBRID_VECTOR_COSINE_FIELD] == {"$meta": "vectorSearchScore"}


@pytest.mark.asyncio
async def test_relevance_floor_drops_low_cosine_chunks():
    """Chunks below the cosine floor (and lexical-only chunks with no cosine)
    must be dropped so the empty-context refusal can fire on junk queries."""
    fake_results = [
        {"chunk_id": "hit", RAG_HYBRID_VECTOR_COSINE_FIELD: 0.62, RRF_RAW_SCORE_FIELD: 0.03},
        {"chunk_id": "weak", RAG_HYBRID_VECTOR_COSINE_FIELD: 0.31, RRF_RAW_SCORE_FIELD: 0.02},
        {"chunk_id": "lexical_only", RRF_RAW_SCORE_FIELD: 0.015},  # no cosine
    ]
    spy = _SpyCollection(results=fake_results)
    out = await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=5, min_vector_score=0.5
    )
    assert [r["chunk_id"] for r in out] == ["hit"]


@pytest.mark.asyncio
async def test_relevance_floor_returns_empty_on_all_irrelevant():
    """An out-of-corpus query where every chunk is below the floor must return
    [] so the caller's refusal path triggers."""
    fake_results = [
        {"chunk_id": "a", RAG_HYBRID_VECTOR_COSINE_FIELD: 0.10, RRF_RAW_SCORE_FIELD: 0.03},
        {"chunk_id": "b", RAG_HYBRID_VECTOR_COSINE_FIELD: 0.20, RRF_RAW_SCORE_FIELD: 0.02},
    ]
    spy = _SpyCollection(results=fake_results)
    out = await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=5, min_vector_score=0.5
    )
    assert out == []


@pytest.mark.asyncio
async def test_no_floor_when_min_vector_score_is_none():
    """With no floor configured, every fused chunk is returned (legacy behavior)."""
    fake_results = [
        {"chunk_id": "a", RAG_HYBRID_VECTOR_COSINE_FIELD: 0.10, RRF_RAW_SCORE_FIELD: 0.03},
        {"chunk_id": "b", RRF_RAW_SCORE_FIELD: 0.02},
    ]
    spy = _SpyCollection(results=fake_results)
    out = await hybrid_search_chunks(
        spy, query_text="x", query_embedding=[0.0] * 4, top_k=5, min_vector_score=None
    )
    assert [r["chunk_id"] for r in out] == ["a", "b"]


@pytest.mark.asyncio
async def test_aggregate_failure_propagates():
    """Per project fail-fast policy, hybrid_search must NOT swallow a
    MongoDB aggregation error. Callers (retrieval pipeline) rely on the
    raise to trigger a 500 rather than silently falling back."""
    coll = _RaisingCollection(RuntimeError("mongot offline"))
    with pytest.raises(RuntimeError, match="mongot offline"):
        await hybrid_search_chunks(
            coll, query_text="x", query_embedding=[0.0] * 4, top_k=3
        )
