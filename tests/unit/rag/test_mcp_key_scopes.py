"""API-key scope enforcement tests for the MCP tool boundary.

Covers RAGApiKeyScope + the routing-independent authorize_tool gate:
  - no scopes / empty scopes -> FULL (backward compatible).
  - PODCAST_QUERY-only key can invoke ONLY the public podcast tools.
  - FULL key can invoke internal tools.
Pure logic, no Docker.
"""

import pytest

from constants import (
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_LIST_RAG_SOURCES,
    MCP_TOOL_RAG_QUERY,
    MCP_TOOL_RAG_SEARCH,
    MCP_TOOL_SEARCH_PODCASTS,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys
from rag.auth.scopes import (
    ScopeForbiddenError,
    authorize_tool,
    is_full_scope,
    is_podcast_query_only,
    is_tool_allowed,
)


def _key(scopes=None):
    rec = {RAGApiKeyKeys.KEY_ID: "k1"}
    if scopes is not None:
        rec[RAGApiKeyKeys.SCOPES] = scopes
    return rec


class TestBackwardCompat:
    def test_missing_scopes_is_full(self):
        assert is_full_scope(_key())
        assert not is_podcast_query_only(_key())

    def test_empty_scopes_is_full(self):
        assert is_full_scope(_key([]))


class TestFullScope:
    def test_full_can_invoke_internal_tools(self):
        k = _key([str(RAGApiKeyScope.FULL)])
        for tool in (MCP_TOOL_RAG_QUERY, MCP_TOOL_RAG_SEARCH, MCP_TOOL_LIST_RAG_SOURCES):
            assert is_tool_allowed(k, tool)
            authorize_tool(k, tool)  # no raise


class TestPodcastQueryScope:
    def test_recognized_as_restricted(self):
        k = _key([str(RAGApiKeyScope.PODCAST_QUERY)])
        assert is_podcast_query_only(k)
        assert not is_full_scope(k)

    def test_can_invoke_public_tools(self):
        k = _key([str(RAGApiKeyScope.PODCAST_QUERY)])
        assert is_tool_allowed(k, MCP_TOOL_SEARCH_PODCASTS)
        assert is_tool_allowed(k, MCP_TOOL_LIST_PODCASTS)

    @pytest.mark.parametrize(
        "tool",
        [MCP_TOOL_RAG_QUERY, MCP_TOOL_RAG_SEARCH, MCP_TOOL_LIST_RAG_SOURCES],
    )
    def test_cannot_invoke_internal_tools(self, tool):
        k = _key([str(RAGApiKeyScope.PODCAST_QUERY)])
        assert not is_tool_allowed(k, tool)
        with pytest.raises(ScopeForbiddenError):
            authorize_tool(k, tool)

    def test_full_plus_podcast_query_is_full(self):
        # FULL present wins: not restricted.
        k = _key([str(RAGApiKeyScope.FULL), str(RAGApiKeyScope.PODCAST_QUERY)])
        assert not is_podcast_query_only(k)
        authorize_tool(k, MCP_TOOL_RAG_QUERY)  # no raise
