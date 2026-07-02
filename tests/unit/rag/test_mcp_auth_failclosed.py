"""Fail-closed + live-revocation + POST-fallback auth-context tests (C1/H1/H2/C2).

These exercise the async authorize_current_tool across the transport distinction
and the TTL re-resolve — behaviors the synchronous ContextVar-only test cannot
reach. No Docker: the DB re-resolve is stubbed.
"""

import asyncio
import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest

from constants import (
    MCP_TOOL_RAG_QUERY,
    MCP_TOOL_SEARCH_PODCASTS,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys
from rag.auth.scopes import ScopeForbiddenError
from rag.mcp import auth_context

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_context():
    auth_context.set_current_key_record(None)
    # Reset the transport flag to stdio for each test unless it opts into HTTP.
    auth_context._http_transport_active.set(False)
    yield
    auth_context.set_current_key_record(None)
    auth_context._http_transport_active.set(False)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _podcast_key(key_id="consumer-1"):
    return {RAGApiKeyKeys.KEY_ID: key_id, RAGApiKeyKeys.SCOPES: [str(RAGApiKeyScope.PODCAST_QUERY)]}


# ---- C1: fail-closed on HTTP, no-op on stdio ---------------------------------


async def test_stdio_no_record_is_noop():
    # stdio (HTTP transport flag off): no record -> enforcement skipped.
    await auth_context.authorize_current_tool(MCP_TOOL_RAG_QUERY)


async def test_http_no_record_fails_closed(monkeypatch):
    auth_context.mark_http_transport_active()
    # No ContextVar record and no request-context bearer -> REJECT (not allow).
    monkeypatch.setattr(auth_context, "_record_from_request_context", _none_coro)
    with pytest.raises(ScopeForbiddenError):
        await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)


async def _none_coro():
    return None


# ---- H2: POST-bearer fallback when ContextVar did not propagate ---------------


async def test_http_falls_back_to_request_context_record(monkeypatch):
    auth_context.mark_http_transport_active()

    async def _fake_reqctx():
        # The real _record_from_request_context stamps the record; mirror that so
        # the fresh record is within TTL and no DB re-resolve is attempted.
        return auth_context._stamp(_podcast_key())

    monkeypatch.setattr(auth_context, "_record_from_request_context", _fake_reqctx)
    # No ContextVar record, but the POST-bearer fallback yields a PODCAST_QUERY
    # key -> a public tool is allowed, an internal tool is rejected.
    await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)

    monkeypatch.setattr(auth_context, "_record_from_request_context", _fake_reqctx)
    with pytest.raises(ScopeForbiddenError):
        await auth_context.authorize_current_tool(MCP_TOOL_RAG_QUERY)


# ---- H1: short-TTL re-resolve rejects a revoked key --------------------------


async def test_revoked_key_rejected_after_ttl(monkeypatch):
    monkeypatch.setenv("RAG_MCP_KEY_REAUTH_TTL_SECONDS", "0")  # re-resolve every call
    from config import get_settings

    get_settings.cache_clear()

    revoked = {"value": False}

    class _Repo:
        def __init__(self, *a, **k):
            pass

        async def find_enabled_by_key_id(self, key_id):
            return None if revoked["value"] else _podcast_key(key_id)

    async def _fake_db():
        return object()

    monkeypatch.setattr(auth_context, "get_database", _fake_db)
    monkeypatch.setattr(auth_context, "RAGApiKeysRepository", _Repo)

    auth_context.set_current_key_record(auth_context._stamp(_podcast_key()))

    # Still enabled -> allowed.
    await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)

    # Revoke mid-session -> next call (TTL=0 forces re-resolve) is rejected.
    revoked["value"] = True
    with pytest.raises(ScopeForbiddenError):
        await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)


async def test_fresh_record_within_ttl_not_reresolved(monkeypatch):
    monkeypatch.setenv("RAG_MCP_KEY_REAUTH_TTL_SECONDS", "60")
    from config import get_settings

    get_settings.cache_clear()

    calls = {"n": 0}

    class _Repo:
        def __init__(self, *a, **k):
            pass

        async def find_enabled_by_key_id(self, key_id):
            calls["n"] += 1
            return _podcast_key(key_id)

    async def _fake_db():
        return object()

    monkeypatch.setattr(auth_context, "get_database", _fake_db)
    monkeypatch.setattr(auth_context, "RAGApiKeysRepository", _Repo)

    auth_context.set_current_key_record(auth_context._stamp(_podcast_key()))
    await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)
    # Within TTL: no DB re-resolve happened.
    assert calls["n"] == 0


# ---- C2 (GC-able task): touch holds a strong ref ----------------------------


async def test_touch_holds_strong_ref(monkeypatch):
    started = asyncio.Event()

    async def _fake_touch(key_id):
        started.set()

    monkeypatch.setattr(auth_context, "_touch_last_used", _fake_touch)
    auth_context._background_tasks.clear()

    auth_context.set_current_key_record(_podcast_key())
    auth_context.touch_current_consumer_last_used()

    # A strong ref is retained until the task completes.
    assert len(auth_context._background_tasks) == 1
    await asyncio.wait_for(started.wait(), timeout=1)
    # Let the done-callback run to discard the ref.
    await asyncio.sleep(0)
    assert len(auth_context._background_tasks) == 0
