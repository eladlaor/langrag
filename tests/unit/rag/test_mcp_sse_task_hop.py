"""End-to-end MCP task-hop scope-gate test (C1/H2) — no Docker.

The existing auth-context test sets the ContextVar synchronously and cannot catch
the fail-open bug, because on the SSE transport the tool executes in a SEPARATE
anyio task (dispatched by `_mcp_server.run` via `task_group.start_soon`) from the
request that set the context.

This drives a REAL FastMCP client<->server over the in-memory transport, whose
`server.run` uses the exact same `start_soon` task-dispatch as SSE. So a tool call
here genuinely crosses the task hop. We assert:
  - a PODCAST_QUERY record set before the call is REJECTED at an internal tool
    (scope enforced across the hop, surfaced as a tool error);
  - a FULL record is accepted (tool body stubbed to avoid Mongo);
  - with the HTTP transport active and NO record resolvable, the call FAILS
    CLOSED (rejected), never silently allowed.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from constants import MCP_TOOL_RAG_QUERY, RAGApiKeyScope
from custom_types.field_keys import RAGApiKeyKeys
from rag.mcp import auth_context, server as mcp_server

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    auth_context.set_current_key_record(None)
    auth_context._http_transport_active.set(False)

    # Never let the reqctx fallback reach a real request/Mongo in these tests.
    async def _no_reqctx():
        return None

    monkeypatch.setattr(auth_context, "_record_from_request_context", _no_reqctx)
    yield
    auth_context.set_current_key_record(None)
    auth_context._http_transport_active.set(False)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _record(scope):
    return auth_context._stamp({RAGApiKeyKeys.KEY_ID: "k", RAGApiKeyKeys.SCOPES: [str(scope)]})


def _is_error(result) -> bool:
    return bool(getattr(result, "isError", False))


async def test_podcast_key_rejected_at_internal_tool_across_hop():
    auth_context.mark_http_transport_active()
    auth_context.set_current_key_record(_record(RAGApiKeyScope.PODCAST_QUERY))

    srv = mcp_server.build_server(public_mode=False)
    async with create_connected_server_and_client_session(srv) as client:
        result = await client.call_tool(MCP_TOOL_RAG_QUERY, {"query": "hi"})
        assert _is_error(result)  # ScopeForbiddenError surfaced across the task hop


async def test_full_key_accepted_across_hop(monkeypatch):
    auth_context.mark_http_transport_active()
    auth_context.set_current_key_record(_record(RAGApiKeyScope.FULL))

    async def _fake_rag_query(**kwargs):
        return {"answer": "ok", "citations": []}

    monkeypatch.setattr(mcp_server, "rag_query", _fake_rag_query)

    srv = mcp_server.build_server(public_mode=False)
    async with create_connected_server_and_client_session(srv) as client:
        result = await client.call_tool(MCP_TOOL_RAG_QUERY, {"query": "hi"})
        assert not _is_error(result)


async def test_http_no_record_fails_closed_across_hop():
    auth_context.mark_http_transport_active()
    auth_context.set_current_key_record(None)  # no GET-time record, no reqctx fallback

    srv = mcp_server.build_server(public_mode=False)
    async with create_connected_server_and_client_session(srv) as client:
        result = await client.call_tool(MCP_TOOL_RAG_QUERY, {"query": "hi"})
        assert _is_error(result)  # fail-closed: rejected, not silently allowed
