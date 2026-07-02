"""COST-4a: the retrieval pipeline reuses a cached query embedding on a repeat
query (cache hit) instead of re-embedding, and F5: podcast search can opt out of
the soft default date window (unbounded_default_window)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag.retrieval import pipeline as pipeline_mod
from rag.retrieval.pipeline import RetrievalPipeline


def _make_pipeline(monkeypatch, *, window_days=30):
    monkeypatch.setattr(RetrievalPipeline, "__init__", lambda self: None)
    p = RetrievalPipeline()
    p._embedder = MagicMock()
    p._embedder.embed_text = MagicMock(return_value=[0.1, 0.2, 0.3])
    settings = MagicMock()
    settings.default_retrieval_window_days = window_days
    settings.hybrid_enabled = False
    settings.vector_search_top_k = 20
    settings.rerank_top_k = 5
    settings.mmr_lambda = 0.7
    settings.enable_mmr_diversity = False
    settings.include_raw_messages_default = False
    settings.min_similarity_score = 0.5
    settings.freshness_warning_days = 0
    p._settings = settings
    return p


@pytest.fixture(autouse=True)
def _reset_cache():
    pipeline_mod._get_query_cache()._reset_for_tests()
    yield
    pipeline_mod._get_query_cache()._reset_for_tests()


async def _run(p, monkeypatch, captured, **kwargs):
    async def _fake_vs(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(pipeline_mod, "vector_search_chunks", _fake_vs)
    monkeypatch.setattr(pipeline_mod, "get_database", AsyncMock(return_value={"rag_chunks": MagicMock()}))
    with patch.object(pipeline_mod, "langfuse_span"), patch.object(pipeline_mod, "track_retrieval"):
        return await p.retrieve(query=kwargs.pop("query", "q"), **kwargs)


class TestQueryEmbeddingCache:
    async def test_second_identical_query_hits_cache(self, monkeypatch):
        # Force a real cache with TTL enabled.
        monkeypatch.setattr(
            pipeline_mod, "_get_query_cache",
            lambda: pipeline_mod._query_cache_singleton or _install_cache(monkeypatch),
        )
        cache = _install_cache(monkeypatch)
        p = _make_pipeline(monkeypatch)
        captured: dict = {}
        await _run(p, monkeypatch, captured, query="Same Query")
        await _run(p, monkeypatch, captured, query="same query")  # normalized-equal
        assert p._embedder.embed_text.call_count == 1  # second served from cache
        assert cache.get("same query") == [0.1, 0.2, 0.3]


class TestUnboundedWindow:
    async def test_default_window_applied_when_no_dates(self, monkeypatch):
        p = _make_pipeline(monkeypatch, window_days=30)
        captured: dict = {}
        await _run(p, monkeypatch, captured, query="q")
        assert captured["date_start"] is not None  # soft window applied

    async def test_unbounded_skips_default_window(self, monkeypatch):
        p = _make_pipeline(monkeypatch, window_days=30)
        captured: dict = {}
        await _run(p, monkeypatch, captured, query="q", unbounded_default_window=True)
        assert captured["date_start"] is None  # no window on the podcast surface


def _install_cache(monkeypatch):
    from rag.cache.query_embedding_cache import QueryEmbeddingCache

    cache = QueryEmbeddingCache(max_size=16, ttl_seconds=100, clock=lambda: 0.0)
    monkeypatch.setattr(pipeline_mod, "_query_cache_singleton", cache, raising=False)
    monkeypatch.setattr(pipeline_mod, "_get_query_cache", lambda: cache)
    return cache
