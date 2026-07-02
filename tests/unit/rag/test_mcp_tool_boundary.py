"""Tool-boundary security tests for the MCP search surface.

Covers the resource-exhaustion guards required before public launch:
  - top_k clamped to a hard max (not passed straight through).
  - over-long / empty query rejected with an explicit error (not silent truncation).
  - inverted / absurd date ranges rejected.
Runs WITHOUT Docker (pure input validation + a stubbed pipeline).
"""

from datetime import UTC, datetime

import pytest

from constants import MCP_QUERY_MAX_LENGTH, MCP_TOP_K_HARD_MAX
from rag.mcp import tools as mcp_tools
from rag.mcp.validation import (
    MCPToolInputError,
    clamp_top_k,
    validate_date_range,
    validate_query,
)


class TestClampTopK:
    def test_none_passes_through(self):
        assert clamp_top_k(None) is None

    def test_within_bound_unchanged(self):
        assert clamp_top_k(5) == 5

    def test_at_bound_unchanged(self):
        assert clamp_top_k(MCP_TOP_K_HARD_MAX) == MCP_TOP_K_HARD_MAX

    def test_huge_value_clamped_to_hard_max(self):
        assert clamp_top_k(10**9) == MCP_TOP_K_HARD_MAX

    def test_zero_or_negative_rejected(self):
        with pytest.raises(MCPToolInputError):
            clamp_top_k(0)
        with pytest.raises(MCPToolInputError):
            clamp_top_k(-3)


class TestValidateQuery:
    def test_empty_rejected(self):
        with pytest.raises(MCPToolInputError):
            validate_query("")
        with pytest.raises(MCPToolInputError):
            validate_query("   ")

    def test_at_limit_ok(self):
        q = "x" * MCP_QUERY_MAX_LENGTH
        assert validate_query(q) == q

    def test_over_limit_rejected(self):
        with pytest.raises(MCPToolInputError):
            validate_query("x" * (MCP_QUERY_MAX_LENGTH + 1))


class TestValidateDateRange:
    def test_inverted_rejected(self):
        ds = datetime(2026, 5, 1, tzinfo=UTC)
        de = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(MCPToolInputError):
            validate_date_range(ds, de)

    def test_ordered_ok(self):
        ds = datetime(2026, 1, 1, tzinfo=UTC)
        de = datetime(2026, 5, 1, tzinfo=UTC)
        validate_date_range(ds, de)  # no raise

    def test_absurd_year_rejected(self):
        de = datetime(9999, 1, 1, tzinfo=UTC)
        with pytest.raises(MCPToolInputError):
            validate_date_range(None, de)

    def test_open_ranges_ok(self):
        validate_date_range(None, None)


def _stub_pipeline(monkeypatch, captured: dict):
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)

    async def _fake_retrieve(self, *args, **kwargs):
        captured.update(kwargs)
        return {
            "context": "ctx",
            "citations": [],
            "freshness_warning": False,
            "oldest_source_date": None,
            "newest_source_date": None,
        }

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _fake_retrieve)
    monkeypatch.setattr(mcp_tools, "create_rag_trace", lambda **kw: (None, "t-1"))
    monkeypatch.setattr(mcp_tools, "flush_langfuse", lambda: None)


class TestRagSearchAppliesBoundary:
    async def test_top_k_clamped_before_retrieval(self, monkeypatch):
        captured: dict = {}
        _stub_pipeline(monkeypatch, captured)
        await mcp_tools.rag_search(query="q", top_k=10**9)
        assert captured["rerank_top_k"] == MCP_TOP_K_HARD_MAX

    async def test_over_long_query_rejected_before_any_work(self, monkeypatch):
        captured: dict = {}
        _stub_pipeline(monkeypatch, captured)
        with pytest.raises(MCPToolInputError):
            await mcp_tools.rag_search(query="x" * (MCP_QUERY_MAX_LENGTH + 1))
        assert captured == {}  # retrieval never ran

    async def test_inverted_date_rejected_before_any_work(self, monkeypatch):
        captured: dict = {}
        _stub_pipeline(monkeypatch, captured)
        with pytest.raises(MCPToolInputError):
            await mcp_tools.rag_search(query="q", date_start="2026-05-01", date_end="2026-01-01")
        assert captured == {}
