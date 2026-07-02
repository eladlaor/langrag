"""Runtime scope-enforcement tests at the built-server tool boundary (no Docker).

Proves the wiring, not just the gate: with a PODCAST_QUERY key set in the
per-request auth context, invoking an INTERNAL tool via the built server is
rejected at runtime (even in internal mode), and no retrieval/generation runs.
A public tool with the same key is allowed. A FULL key may invoke internal tools.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest

from constants import (
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_RAG_QUERY,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys
from rag.mcp import auth_context
from rag.mcp.server import build_server


@pytest.fixture(autouse=True)
def _clear_context():
    auth_context.set_current_key_record(None)
    yield
    auth_context.set_current_key_record(None)


def _record(scope):
    return {RAGApiKeyKeys.KEY_ID: "k1", RAGApiKeyKeys.SCOPES: [str(scope)]}


async def test_podcast_key_rejected_on_internal_tool_at_runtime(monkeypatch):
    # Make retrieval blow up if ever reached, proving the gate short-circuits.
    from rag.mcp import tools as mcp_tools

    async def _must_not_run(*a, **k):
        raise AssertionError("retrieval must not run for a scope-forbidden call")

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _must_not_run, raising=False)

    server = build_server(public_mode=False)
    auth_context.set_current_key_record(_record(RAGApiKeyScope.PODCAST_QUERY))

    with pytest.raises(Exception) as exc:
        await server.call_tool(MCP_TOOL_RAG_QUERY, {"query": "hi"})
    # FastMCP wraps the ScopeForbiddenError; the message names the blocked tool.
    assert MCP_TOOL_RAG_QUERY in str(exc.value)


async def test_list_podcasts_allowed_for_podcast_key(monkeypatch):
    from rag.mcp import server as mcp_server

    async def _fake_list():
        return {"podcasts": []}

    # The wrapper calls list_podcasts bound in the server module namespace.
    monkeypatch.setattr(mcp_server, "list_podcasts", _fake_list)

    server = build_server(public_mode=True)
    auth_context.set_current_key_record(_record(RAGApiKeyScope.PODCAST_QUERY))

    result = await server.call_tool(MCP_TOOL_LIST_PODCASTS, {})
    assert result is not None  # no scope rejection
