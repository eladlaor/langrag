"""Anonymous (keyless) MCP lane: auth-layer tests (no Docker).

Covers the BYOA keyless lane added to the Streamable HTTP auth path:
  - middleware admits a bearer-less request as an anonymous principal when
    rag.mcp_anonymous_enabled is true, and 401s it when false;
  - a PRESENT but invalid bearer still 401s (no silent downgrade to anonymous);
  - an EMPTY bearer ("Authorization: Bearer ") lands in the anonymous lane;
  - the anonymous record's shape and, critically, the scope-safety regression:
    it must resolve to exactly {PODCAST_QUERY}, never FULL (the legacy
    empty-scopes carve-out must be unreachable);
  - the H1 TTL re-resolve and last_used touch no-op for anonymous ids.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

import pytest

from constants import (
    HTTP_STATUS_UNAUTHORIZED,
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_RAG_QUERY,
    MCP_TOOL_SEARCH_PODCASTS,
    RAG_ANON_KEY_ID_PREFIX,
    RAG_ANON_OWNER,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys
from rag.auth.scopes import ScopeForbiddenError, authorize_tool, is_full_scope, resolve_scopes
from rag.mcp import auth_context


@pytest.fixture(autouse=True)
def _clean_context():
    auth_context.set_current_key_record(None)
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


# ---- ASGI harness -------------------------------------------------------------


def _http_scope(headers: list[tuple[bytes, bytes]] | None = None, client_ip: str = "203.0.113.7") -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": headers or [],
        "client": (client_ip, 54321),
        "query_string": b"",
    }


async def _call_middleware(scope: dict) -> tuple[int | None, dict | None]:
    """Drive ConsumerKeyAuthMiddleware over a fake inner app.

    Returns (rejection_status_or_None, record_seen_by_inner_app_or_None).
    """
    seen: dict = {"record": None, "called": False}
    sent: list = []

    async def inner_app(scope, receive, send):
        seen["called"] = True
        seen["record"] = auth_context.get_current_key_record()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    middleware = auth_context.ConsumerKeyAuthMiddleware(inner_app)
    await middleware(scope, receive, send)

    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    if seen["called"]:
        return status, seen["record"]
    return status, None


# ---- Middleware: keyless lane ---------------------------------------------------


async def test_no_bearer_admitted_as_anonymous_when_enabled(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    status, record = await _call_middleware(_http_scope())
    assert status == 200
    assert record is not None
    assert record[RAGApiKeyKeys.KEY_ID].startswith(RAG_ANON_KEY_ID_PREFIX)
    assert record[RAGApiKeyKeys.OWNER] == RAG_ANON_OWNER
    assert record[RAGApiKeyKeys.SCOPES] == [str(RAGApiKeyScope.PODCAST_QUERY)]


async def test_no_bearer_rejected_when_disabled(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "false")
    from config import get_settings

    get_settings.cache_clear()

    status, record = await _call_middleware(_http_scope())
    assert status == HTTP_STATUS_UNAUTHORIZED
    assert record is None


async def test_invalid_bearer_never_downgrades_to_anonymous(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    class _Repo:
        def __init__(self, *a, **k):
            pass

        async def find_by_hash(self, _h):
            return None

    async def _fake_db():
        return object()

    monkeypatch.setattr(auth_context, "get_database", _fake_db)
    monkeypatch.setattr(auth_context, "RAGApiKeysRepository", _Repo)

    scope = _http_scope(headers=[(b"authorization", b"Bearer definitely-not-a-real-key")])
    status, record = await _call_middleware(scope)
    assert status == HTTP_STATUS_UNAUTHORIZED
    assert record is None


async def test_empty_bearer_lands_in_anonymous_lane(monkeypatch):
    # An unset ${LANGRAG_MCP_API_KEY} expansion produces "Authorization: Bearer ".
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    scope = _http_scope(headers=[(b"authorization", b"Bearer ")])
    status, record = await _call_middleware(scope)
    assert status == 200
    assert record is not None
    assert record[RAGApiKeyKeys.KEY_ID].startswith(RAG_ANON_KEY_ID_PREFIX)


async def test_distinct_ips_get_distinct_anonymous_ids(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()

    _, record_a = await _call_middleware(_http_scope(client_ip="198.51.100.1"))
    _, record_b = await _call_middleware(_http_scope(client_ip="198.51.100.2"))
    assert record_a[RAGApiKeyKeys.KEY_ID] != record_b[RAGApiKeyKeys.KEY_ID]


# ---- Record shape + scope safety (the FULL-promotion regression) ---------------


def test_anonymous_key_id_hashes_ip():
    key_id = auth_context.anonymous_key_id_for_ip("203.0.113.7")
    assert key_id.startswith(RAG_ANON_KEY_ID_PREFIX)
    assert "203.0.113.7" not in key_id
    # Stable per IP.
    assert key_id == auth_context.anonymous_key_id_for_ip("203.0.113.7")
    assert auth_context.is_anonymous_key_id(key_id)
    assert not auth_context.is_anonymous_key_id("consumer-1")
    assert not auth_context.is_anonymous_key_id(None)


def test_anonymous_record_resolves_to_podcast_query_only():
    record = auth_context.build_anonymous_record("203.0.113.7")
    assert resolve_scopes(record) == {str(RAGApiKeyScope.PODCAST_QUERY)}
    assert not is_full_scope(record)


def test_anonymous_record_cannot_invoke_internal_tools():
    record = auth_context.build_anonymous_record("203.0.113.7")
    authorize_tool(record, MCP_TOOL_SEARCH_PODCASTS)
    authorize_tool(record, MCP_TOOL_LIST_PODCASTS)
    with pytest.raises(ScopeForbiddenError):
        authorize_tool(record, MCP_TOOL_RAG_QUERY)


def test_anonymous_record_never_has_empty_scopes():
    # The legacy carve-out promotes empty-scopes+no-created_at records to FULL;
    # the builder must be structurally unable to produce that shape.
    record = auth_context.build_anonymous_record("203.0.113.7")
    assert record[RAGApiKeyKeys.SCOPES], "anonymous record must carry explicit non-empty scopes"
    # Document the trap this guards against: the poisoned shape DOES resolve FULL.
    poisoned = {RAGApiKeyKeys.KEY_ID: "anon:poison", RAGApiKeyKeys.SCOPES: []}
    assert is_full_scope(poisoned)


# ---- H1 TTL re-resolve + last_used touch ----------------------------------------


async def test_stale_reresolve_skips_anonymous(monkeypatch):
    monkeypatch.setenv("RAG_MCP_KEY_REAUTH_TTL_SECONDS", "0")  # re-resolve every call
    from config import get_settings

    get_settings.cache_clear()

    calls = {"n": 0}

    class _Repo:
        def __init__(self, *a, **k):
            pass

        async def find_enabled_by_key_id(self, key_id):
            calls["n"] += 1
            return None

    async def _fake_db():
        return object()

    monkeypatch.setattr(auth_context, "get_database", _fake_db)
    monkeypatch.setattr(auth_context, "RAGApiKeysRepository", _Repo)

    record = auth_context._stamp(auth_context.build_anonymous_record("203.0.113.7"))
    auth_context.set_current_key_record(record)
    # TTL=0 would force a DB re-resolve for a keyed record; anonymous must skip
    # it (no rag_api_keys row) instead of fail-closing.
    await auth_context.authorize_current_tool(MCP_TOOL_SEARCH_PODCASTS)
    assert calls["n"] == 0


def test_touch_noop_for_anonymous():
    auth_context.set_current_key_record(auth_context.build_anonymous_record("203.0.113.7"))
    auth_context._background_tasks.clear()
    auth_context.touch_current_consumer_last_used()
    assert len(auth_context._background_tasks) == 0
