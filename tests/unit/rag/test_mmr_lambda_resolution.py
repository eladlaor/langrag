"""Unit tests for RAG MMR lambda resolution in the retrieval pipeline.

Covers TDD success criteria 1, 2, 3 (resolver/rerank level), and 5 (pipeline
fail-fast). These tests do NOT touch MongoDB: they stub the embedder, the db,
and the search functions so the pipeline's lambda-resolution + rerank-gating
logic is exercised in isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from config import get_settings
from rag.retrieval.pipeline import RetrievalPipeline


def _chunk(chunk_id: str, score: float, embedding: list[float]) -> dict:
    """Build a synthetic chunk shaped like a vector-search result."""
    from constants import RAG_SEARCH_SCORE_FIELD
    from custom_types.field_keys import RAGChunkKeys as Keys

    return {
        Keys.CHUNK_ID: chunk_id,
        Keys.CONTENT: f"content-{chunk_id}",
        Keys.SOURCE_TITLE: "t",
        Keys.SOURCE_ID: "s",
        Keys.CONTENT_SOURCE: "podcast",
        Keys.EMBEDDING: embedding,
        RAG_SEARCH_SCORE_FIELD: score,
    }


_SIM_AB = 0.35  # cosine(a, b)


def _dup_heavy_chunks() -> list[dict]:
    """Chunks tuned so 0.7 and 0.3 select a DIFFERENT second chunk.

    First pick is always "a" (highest relevance). For the second slot MMR
    compares "b" (high score, similar to a) against "c" (lower score, diverse).
    The crossover lambda is sim/((score_b - score_c) + sim) = 0.35/(0.19+0.35)
    ~= 0.648, so at lambda=0.7 relevance wins and "b" is chosen, while at
    lambda=0.3 diversity wins and "c" is chosen.
    """
    import math

    b_vec = [_SIM_AB, math.sqrt(1.0 - _SIM_AB**2)]  # cosine(a, b) == _SIM_AB
    return [
        _chunk("a", 0.90, [1.0, 0.0]),
        _chunk("b", 0.89, b_vec),            # similar-ish to a, high score
        _chunk("c", 0.70, [0.0, 1.0]),       # diverse, lower score
    ]


async def _run_pipeline(
    chunks: list[dict],
    *,
    mmr_lambda=None,
    enable_mmr=None,
    final_top_k: int = 2,
):
    """Drive RetrievalPipeline.retrieve with search stubbed to return `chunks`."""
    pipeline = RetrievalPipeline.__new__(RetrievalPipeline)
    pipeline._settings = get_settings().rag
    pipeline._embedder = type("E", (), {"embed_text": staticmethod(lambda q: [0.1, 0.2, 0.3])})()

    from constants import COLLECTION_RAG_CHUNKS

    with (
        patch("rag.retrieval.pipeline.get_database", new=AsyncMock(return_value={COLLECTION_RAG_CHUNKS: object()})),
        patch("rag.retrieval.pipeline.hybrid_search_chunks", new=AsyncMock(return_value=[dict(c) for c in chunks])),
        patch("rag.retrieval.pipeline.vector_search_chunks", new=AsyncMock(return_value=[dict(c) for c in chunks])),
        patch("rag.retrieval.pipeline.rerank_chunks_mmr") as rerank_spy,
    ):
        rerank_spy.side_effect = _real_rerank
        result = await pipeline.retrieve(
            query="q",
            rerank_top_k=final_top_k,
            mmr_lambda=mmr_lambda,
            enable_mmr=enable_mmr,
        )
        return result, rerank_spy


def _real_rerank(*args, **kwargs):
    """Delegate the spy to the genuine reranker so selection stays correct."""
    from rag.retrieval.reranker import rerank_chunks_mmr as real

    return real(*args, **kwargs)


# --- Criterion 1: default parity (no user setting + no arg => lambda 0.7) ---
async def test_default_parity_uses_config_lambda():
    result, spy = await _run_pipeline(_dup_heavy_chunks())
    assert spy.called
    assert spy.call_args.kwargs["lambda_param"] == pytest.approx(0.7)
    assert result["effective_lambda"] == pytest.approx(0.7)


# --- Criterion 2: config override (lambda 1.0 or disabled => skip MMR) ---
async def test_config_lambda_one_skips_rerank(monkeypatch):
    monkeypatch.setenv("RAG_MMR_LAMBDA", "1.0")
    get_settings.cache_clear()
    try:
        result, spy = await _run_pipeline(_dup_heavy_chunks())
        assert not spy.called
        # Output == fused top-k order (first 2 by search order).
        assert [c["chunk_id"] for c in result["reranked_chunks"]] == ["a", "b"]
    finally:
        get_settings.cache_clear()


async def test_enable_mmr_false_skips_rerank():
    result, spy = await _run_pipeline(_dup_heavy_chunks(), enable_mmr=False)
    assert not spy.called
    assert [c["chunk_id"] for c in result["reranked_chunks"]] == ["a", "b"]


# --- Criterion 3: user setting honored (0.3 selects differently than 0.7) ---
async def test_low_lambda_selects_more_diverse_than_high():
    high, _ = await _run_pipeline(_dup_heavy_chunks(), mmr_lambda=0.7)
    low, _ = await _run_pipeline(_dup_heavy_chunks(), mmr_lambda=0.3)

    high_ids = [c["chunk_id"] for c in high["reranked_chunks"]]
    low_ids = [c["chunk_id"] for c in low["reranked_chunks"]]
    assert high_ids == ["a", "b"]   # relevance-weighted keeps the similar high scorer
    assert low_ids == ["a", "c"]    # diversity-weighted swaps in the dissimilar chunk
    assert high_ids != low_ids


# --- Criterion 5 (pipeline side): fail-fast on out-of-range lambda ---
@pytest.mark.parametrize("bad", [-0.1, 1.1])
async def test_pipeline_rejects_out_of_range_lambda(bad):
    with pytest.raises(ValueError) as exc:
        await _run_pipeline(_dup_heavy_chunks(), mmr_lambda=bad)
    assert "retrieve" in str(exc.value)
    assert str(bad) in str(exc.value)


@pytest.mark.parametrize("ok", [0.0, 1.0])
async def test_pipeline_accepts_boundary_lambda(ok):
    # Should not raise. 0.0 reranks, 1.0 skips; both are valid.
    result, _ = await _run_pipeline(_dup_heavy_chunks(), mmr_lambda=ok)
    assert result["effective_lambda"] == pytest.approx(ok)
