"""
Unit tests for RAG chunk reranker (MMR diversity).
"""

import pytest

from rag.retrieval.reranker import rerank_chunks_mmr, _cosine_similarity
from constants import RAG_SEARCH_SCORE_FIELD
from custom_types.field_keys import RAGChunkKeys as Keys


class TestCosaineSimilarity:
    """Tests for inline cosine similarity function."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine_similarity(a, b) == 0.0


class TestRerankChunksMMR:
    """Tests for MMR reranking logic."""

    def _make_chunk(self, chunk_id: str, score: float, embedding: list[float] | None = None) -> dict:
        return {
            Keys.CHUNK_ID: chunk_id,
            Keys.CONTENT: f"Content for {chunk_id}",
            RAG_SEARCH_SCORE_FIELD: score,
            Keys.EMBEDDING: embedding,
        }

    def test_returns_all_if_fewer_than_top_k(self):
        chunks = [self._make_chunk("a", 0.9), self._make_chunk("b", 0.8)]
        result = rerank_chunks_mmr(chunks, query_embedding=[1.0, 0.0], top_k=5)
        assert len(result) == 2

    def test_returns_top_k_chunks(self):
        chunks = [
            self._make_chunk("a", 0.9),
            self._make_chunk("b", 0.8),
            self._make_chunk("c", 0.7),
            self._make_chunk("d", 0.6),
        ]
        result = rerank_chunks_mmr(chunks, query_embedding=[1.0, 0.0], top_k=2)
        assert len(result) == 2

    def test_highest_relevance_first_without_embeddings(self):
        """Without embeddings, MMR degrades to pure relevance ranking."""
        chunks = [
            self._make_chunk("low", 0.3),
            self._make_chunk("high", 0.9),
            self._make_chunk("mid", 0.6),
        ]
        result = rerank_chunks_mmr(chunks, query_embedding=[1.0], top_k=2)
        assert result[0][Keys.CHUNK_ID] == "high"

    def test_diversity_penalizes_similar_chunks(self):
        """With embeddings, MMR should prefer diverse chunks over similar high-scoring ones."""
        # Two chunks with identical embeddings (similar content) vs one different
        similar_emb = [1.0, 0.0, 0.0]
        different_emb = [0.0, 1.0, 0.0]

        chunks = [
            self._make_chunk("similar_1", 0.95, embedding=similar_emb),
            self._make_chunk("similar_2", 0.90, embedding=similar_emb),
            self._make_chunk("different", 0.85, embedding=different_emb),
        ]

        # With diversity (lambda=0.5), the "different" chunk should be preferred over "similar_2"
        result = rerank_chunks_mmr(chunks, query_embedding=[1.0, 0.0, 0.0], top_k=2, lambda_param=0.5)

        result_ids = [c[Keys.CHUNK_ID] for c in result]
        assert "similar_1" in result_ids  # highest score, always first
        assert "different" in result_ids  # diverse, preferred over similar_2

    def test_lambda_1_is_pure_relevance(self):
        """lambda=1.0 should ignore diversity entirely."""
        similar_emb = [1.0, 0.0]
        chunks = [
            self._make_chunk("a", 0.9, embedding=similar_emb),
            self._make_chunk("b", 0.8, embedding=similar_emb),
            self._make_chunk("c", 0.7, embedding=[0.0, 1.0]),
        ]
        result = rerank_chunks_mmr(chunks, query_embedding=[1.0, 0.0], top_k=2, lambda_param=1.0)

        result_ids = [c[Keys.CHUNK_ID] for c in result]
        assert result_ids == ["a", "b"]  # pure relevance order
