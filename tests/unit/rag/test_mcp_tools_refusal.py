"""Regression guard: the MCP rag_query tool returns the canonical refusal strings
on empty retrieval, via the shared helper (no hardcoded literals)."""

import pytest

from constants import RAG_REFUSAL_NO_CONTENT, RAG_REFUSAL_OUT_OF_RANGE
from rag.mcp import tools as mcp_tools


def _empty_retrieval():
    return {
        "context": "",
        "citations": [],
        "freshness_warning": False,
        "oldest_source_date": None,
        "newest_source_date": None,
    }


@pytest.fixture
def patch_empty_retrieval(monkeypatch):
    # Stub the constructor so we don't build a real embedder (needs an API key).
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)

    async def _fake_retrieve(self, *args, **kwargs):
        return _empty_retrieval()

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _fake_retrieve)

    # Fail loudly if the LLM is ever called on empty context.
    async def _boom(*args, **kwargs):
        raise AssertionError("generate_answer must not be called on empty context")

    monkeypatch.setattr(mcp_tools, "generate_answer", _boom)


class TestRagQueryRefusal:
    async def test_no_dates_returns_no_content_refusal(self, patch_empty_retrieval):
        result = await mcp_tools.rag_query(query="anything")
        assert result["answer"] == RAG_REFUSAL_NO_CONTENT
        assert result["citations"] == []

    async def test_with_date_filter_returns_out_of_range_refusal(self, patch_empty_retrieval):
        result = await mcp_tools.rag_query(query="anything", date_start="2030-01-01", date_end="2030-12-31")
        assert result["answer"] == RAG_REFUSAL_OUT_OF_RANGE
        assert result["citations"] == []
