"""Criterion 7: the agent-memory retrieval path must apply NO MMR / lambda.

Agent memory deliberately ranks by reinforcement + fused RRF, not by MMR
diversity. This guard fails if the MMR/lambda machinery ever leaks into the
memory module, and confirms the retriever preserves the fused order it is
given (no diversity rerank step reorders it).
"""

from __future__ import annotations

import inspect

from unittest.mock import AsyncMock, patch

import pytest

import agent.memory.hybrid_memory_search as hms


def test_memory_module_imports_no_mmr_reranker():
    """Static guard: the memory search module must not reference MMR/lambda."""
    src = inspect.getsource(hms)
    assert "rerank_chunks_mmr" not in src
    assert "mmr_lambda" not in src
    assert "lambda_param" not in src


async def test_memory_search_preserves_fused_order():
    """Behavioral guard: output order == the order $rankFusion returns.

    We stub the aggregation so it returns documents in a fixed fused order
    and assert the retriever does not reorder them (which an MMR diversity
    rerank would). Score normalization is order-preserving.
    """
    fused = [
        {"memory_id": "m1", "content": "x", "rrf_score": 0.9},
        {"memory_id": "m2", "content": "y", "rrf_score": 0.6},
        {"memory_id": "m3", "content": "z", "rrf_score": 0.3},
    ]

    class FakeCursor:
        async def to_list(self, length=None):
            return [dict(d) for d in fused]

    class FakeCollection:
        def aggregate(self, pipeline):
            return FakeCursor()

    results = await hms.hybrid_search_memories(
        FakeCollection(),
        user_id="u1",
        query_text="q",
        query_embedding=[0.1, 0.2, 0.3],
        top_k=3,
    )

    assert [r["memory_id"] for r in results] == ["m1", "m2", "m3"]
