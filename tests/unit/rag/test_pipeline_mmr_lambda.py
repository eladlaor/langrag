"""
Unit tests for MMR lambda resolution + skip behavior in RetrievalPipeline.retrieve.

Covers plan TDD criteria: config override (skip MMR at lambda>=1.0 / disabled),
precedence (explicit arg beats config default), and fail-fast validation.
Search, embedding and DB are mocked so these run without Docker.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import RAG_SEARCH_SCORE_FIELD
from custom_types.field_keys import RAGChunkKeys as Keys


def _chunk(chunk_id: str, score: float, embedding: list[float]) -> dict:
    return {
        Keys.CHUNK_ID: chunk_id,
        Keys.CONTENT: f"content {chunk_id}",
        Keys.SOURCE_TITLE: "T",
        Keys.CONTENT_SOURCE: "podcast",
        Keys.SOURCE_ID: "s1",
        Keys.EMBEDDING: embedding,
        RAG_SEARCH_SCORE_FIELD: score,
    }


@pytest.fixture
def fused_chunks():
    # Descending relevance; near-duplicate embeddings for the top two so MMR
    # (low lambda) would reorder, while skip-MMR preserves fused order.
    return [
        _chunk("a", 0.9, [1.0, 0.0, 0.0]),
        _chunk("b", 0.85, [0.99, 0.01, 0.0]),
        _chunk("c", 0.6, [0.0, 1.0, 0.0]),
    ]


def _make_pipeline(fused_chunks, settings_lambda=0.7, settings_enable=True):
    """Build a RetrievalPipeline with embedder/search/DB stubbed out."""
    from rag.retrieval import pipeline as pipeline_mod

    with patch.object(pipeline_mod, "get_settings") as mock_get_settings, \
         patch.object(pipeline_mod, "EmbeddingProviderFactory") as mock_factory:
        s = MagicMock()
        s.rag.mmr_lambda = settings_lambda
        s.rag.enable_mmr_diversity = settings_enable
        s.rag.vector_search_top_k = 10
        s.rag.rerank_top_k = 5
        s.rag.hybrid_enabled = False
        s.rag.min_similarity_score = 0.5
        s.rag.freshness_warning_days = 0
        s.rag_embedding.model = "m"
        s.rag_embedding.dimensions = 3
        mock_get_settings.return_value = s
        mock_factory.create.return_value = MagicMock(embed_text=MagicMock(return_value=[1.0, 0.0, 0.0]))
        pipe = pipeline_mod.RetrievalPipeline()
    return pipe


async def _run(pipe, fused_chunks, **kwargs):
    from rag.retrieval import pipeline as pipeline_mod

    with patch.object(pipeline_mod, "get_database", new=AsyncMock(return_value=MagicMock())), \
         patch.object(pipeline_mod, "vector_search_chunks", new=AsyncMock(return_value=[dict(c) for c in fused_chunks])), \
         patch.object(pipeline_mod, "rerank_chunks_mmr") as mock_rerank:
        mock_rerank.side_effect = lambda chunks, query_embedding, top_k, lambda_param: chunks[:top_k]
        result = await pipe.retrieve(query="q", **kwargs)
        return result, mock_rerank


class TestSkipMmr:
    async def test_lambda_one_skips_rerank(self, fused_chunks):
        pipe = _make_pipeline(fused_chunks)
        result, mock_rerank = await _run(pipe, fused_chunks, mmr_lambda=1.0)
        mock_rerank.assert_not_called()
        assert [c[Keys.CHUNK_ID] for c in result["reranked_chunks"]] == ["a", "b", "c"]
        assert result["mmr_applied"] is False
        assert result["mmr_lambda"] == 1.0

    async def test_disabled_skips_rerank(self, fused_chunks):
        pipe = _make_pipeline(fused_chunks)
        result, mock_rerank = await _run(pipe, fused_chunks, enable_mmr=False)
        mock_rerank.assert_not_called()
        assert result["mmr_applied"] is False

    async def test_config_disabled_default_skips(self, fused_chunks):
        pipe = _make_pipeline(fused_chunks, settings_enable=False)
        result, mock_rerank = await _run(pipe, fused_chunks)
        mock_rerank.assert_not_called()


class TestApplyMmr:
    async def test_default_lambda_applies_rerank(self, fused_chunks):
        pipe = _make_pipeline(fused_chunks)
        result, mock_rerank = await _run(pipe, fused_chunks)
        mock_rerank.assert_called_once()
        assert mock_rerank.call_args.kwargs["lambda_param"] == 0.7
        assert result["mmr_applied"] is True

    async def test_explicit_arg_beats_config_default(self, fused_chunks):
        pipe = _make_pipeline(fused_chunks, settings_lambda=0.7)
        _, mock_rerank = await _run(pipe, fused_chunks, mmr_lambda=0.3)
        assert mock_rerank.call_args.kwargs["lambda_param"] == 0.3


class TestValidation:
    @pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0, -1.0])
    async def test_out_of_range_lambda_raises(self, fused_chunks, bad):
        pipe = _make_pipeline(fused_chunks)
        with pytest.raises(ValueError, match="mmr_lambda"):
            await _run(pipe, fused_chunks, mmr_lambda=bad)

    @pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
    async def test_boundary_lambda_accepted(self, fused_chunks, ok):
        pipe = _make_pipeline(fused_chunks)
        result, _ = await _run(pipe, fused_chunks, mmr_lambda=ok)
        assert result["mmr_lambda"] == ok
