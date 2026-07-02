"""Unit tests for the in-process query-embedding cache (COST-4a).

Injectable clock keeps TTL deterministic; no Docker.
"""

from rag.cache.query_embedding_cache import QueryEmbeddingCache


class TestQueryEmbeddingCache:
    def test_miss_then_hit(self):
        cache = QueryEmbeddingCache(max_size=8, ttl_seconds=100, clock=lambda: 0.0)
        assert cache.get("hello") is None
        cache.put("hello", [1.0, 2.0])
        assert cache.get("hello") == [1.0, 2.0]

    def test_normalizes_query_text(self):
        cache = QueryEmbeddingCache(max_size=8, ttl_seconds=100, clock=lambda: 0.0)
        cache.put("  Hello   World ", [1.0])
        # Case + surrounding/inner whitespace normalized: a differently-spaced,
        # differently-cased variant hits the same entry.
        assert cache.get("hello world") == [1.0]

    def test_ttl_expiry(self):
        clock = {"t": 0.0}
        cache = QueryEmbeddingCache(max_size=8, ttl_seconds=10, clock=lambda: clock["t"])
        cache.put("q", [1.0])
        clock["t"] = 9
        assert cache.get("q") == [1.0]
        clock["t"] = 11
        assert cache.get("q") is None

    def test_bounded_lru_eviction(self):
        cache = QueryEmbeddingCache(max_size=2, ttl_seconds=100, clock=lambda: 0.0)
        cache.put("a", [1.0])
        cache.put("b", [2.0])
        cache.get("a")  # touch a so b is the LRU
        cache.put("c", [3.0])  # evicts b
        assert cache.get("b") is None
        assert cache.get("a") == [1.0]
        assert cache.get("c") == [3.0]

    def test_disabled_when_ttl_zero(self):
        cache = QueryEmbeddingCache(max_size=8, ttl_seconds=0, clock=lambda: 0.0)
        cache.put("q", [1.0])
        assert cache.get("q") is None
