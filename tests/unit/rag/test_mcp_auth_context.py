"""Per-request MCP auth-context tests (no Docker).

Covers:
  - authorize_current_tool enforces the ContextVar key record's scope, and is a
    no-op when no record is set (stdio path).
  - resolve_key_record maps the shared internal bearer to a FULL record.
  - the internal bearer / no-record cases for touch_current_consumer_last_used.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest

from constants import (
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_RAG_QUERY,
    MCP_TOOL_SEARCH_PODCASTS,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys
from rag.auth.scopes import ScopeForbiddenError
from rag.mcp import auth_context


@pytest.fixture(autouse=True)
def _clear_context():
    auth_context.set_current_key_record(None)
    yield
    auth_context.set_current_key_record(None)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _podcast_key():
    return {RAGApiKeyKeys.KEY_ID: "consumer-1", RAGApiKeyKeys.SCOPES: [str(RAGApiKeyScope.PODCAST_QUERY)]}


def _full_key():
    return {RAGApiKeyKeys.KEY_ID: "internal-1", RAGApiKeyKeys.SCOPES: [str(RAGApiKeyScope.FULL)]}


async def test_no_record_is_noop():
    # stdio path: no record set + HTTP transport not active -> enforcement
    # skipped, no raise. authorize_current_tool is async now (it may re-resolve
    # a stamped record against the DB on the HTTP path).
    await auth_context.authorize_current_tool(MCP_TOOL_RAG_QUERY)


async def test_podcast_key_allows_public_tool():
    auth_context.set_current_key_record(_podcast_key())
    await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)
    await auth_context.authorize_current_tool(MCP_TOOL_LIST_PODCASTS)


async def test_podcast_key_rejects_internal_tool():
    auth_context.set_current_key_record(_podcast_key())
    with pytest.raises(ScopeForbiddenError):
        await auth_context.authorize_current_tool(MCP_TOOL_RAG_QUERY)


async def test_full_key_allows_internal_tool():
    auth_context.set_current_key_record(_full_key())
    await auth_context.authorize_current_tool(MCP_TOOL_RAG_QUERY)


async def test_resolve_internal_bearer_is_full(monkeypatch):
    monkeypatch.setenv("RAG_MCP_API_KEY", "shared-internal-bearer")
    from config import get_settings

    get_settings.cache_clear()

    record = await auth_context.resolve_key_record("shared-internal-bearer")
    assert record is not None
    assert record[RAGApiKeyKeys.SCOPES] == [str(RAGApiKeyScope.FULL)]
    # A FULL record may invoke internal tools.
    auth_context.set_current_key_record(record)
    await auth_context.authorize_current_tool(MCP_TOOL_RAG_QUERY)


async def test_resolve_unknown_key_returns_none(monkeypatch):
    monkeypatch.setenv("RAG_MCP_API_KEY", "shared-internal-bearer")
    from config import get_settings

    get_settings.cache_clear()

    # Stub the DB lookup so an unknown key resolves to None without Mongo.
    class _Repo:
        def __init__(self, *a, **k):
            pass

        async def find_by_hash(self, _h):
            return None

    async def _fake_db():
        return object()

    monkeypatch.setattr(auth_context, "get_database", _fake_db)
    monkeypatch.setattr(auth_context, "RAGApiKeysRepository", _Repo)

    record = await auth_context.resolve_key_record("some-unknown-key")
    assert record is None


def test_touch_noop_for_internal_and_missing(monkeypatch):
    # No record -> no-op, no crash.
    auth_context.set_current_key_record(None)
    auth_context.touch_current_consumer_last_used()

    # Internal bearer record -> no consumer touch scheduled.
    auth_context.set_current_key_record({RAGApiKeyKeys.KEY_ID: auth_context._INTERNAL_BEARER_KEY_ID, RAGApiKeyKeys.SCOPES: [str(RAGApiKeyScope.FULL)]})
    auth_context.touch_current_consumer_last_used()
