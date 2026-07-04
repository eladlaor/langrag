"""Keyless (anonymous) lane over the real Streamable HTTP MCP app.

Boots the actual FastMCP Starlette app (public mode) wrapped with
ConsumerKeyAuthMiddleware and drives it through starlette's TestClient (which
runs the app lifespan, required by the StreamableHTTP session manager).

Proves, over the wire:
  - a keyless `initialize` + `tools/call list_podcasts` succeed when the
    anonymous flag is on;
  - the same requests 401 when the flag is off;
  - an over-quota keyless `search_podcasts` returns a clean tool error and the
    embedder is NEVER called (zero owner-paid embedding on the rejected path).

No Docker: Mongo-backed pieces (podcast catalog, quota repo) are faked.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio

# NOTE: app-level imports are deferred into fixtures/tests: this package dir
# shadows the top-level `rag` package during collection (see test_rest_refusal).


def _ensure_src_rag_package() -> None:
    """Make `import rag` resolve to src/rag, not this test directory.

    Under pytest's prepend import mode the directory `tests/integration/rag`
    gets bound to the top-level name `rag`, shadowing the real package. Put
    `src` at the front of sys.path and evict any shadow `rag` module so the
    deferred app imports below resolve correctly.
    """
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[3] / "src")
    if sys.path and sys.path[0] != src:
        if src in sys.path:
            sys.path.remove(src)
        sys.path.insert(0, src)

    shadow = sys.modules.get("rag")
    if shadow is not None and "tests" in (getattr(shadow, "__file__", "") or ""):
        for name in [m for m in sys.modules if m == "rag" or m.startswith("rag.")]:
            del sys.modules[name]


_ACCEPT = "application/json, text/event-stream"
_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}


def _tool_call(name: str, arguments: dict | None = None, req_id: int = 2) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


def _parse_result(response) -> dict:
    """Extract the JSON-RPC message from a JSON or SSE-framed response."""
    text = response.text
    payload = text
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            break
    return json.loads(payload)


@pytest.fixture()
def _client_factory(monkeypatch):
    """Build a TestClient over the public-mode MCP app with auth middleware."""
    _ensure_src_rag_package()
    from starlette.testclient import TestClient

    from rag.mcp import auth_context
    from rag.mcp.server import build_server

    def _make() -> TestClient:
        from config import get_settings
        from rag.concurrency import guard

        get_settings.cache_clear()
        # Each TestClient runs its own event loop; process-global asyncio
        # primitives would stay bound to the previous test's loop and raise
        # "bound to a different event loop" on the next tool call. Reset both
        # the RAG concurrency guard and sse_starlette's module-global exit event.
        guard._reset_for_tests()
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
        server = build_server(public_mode=True)
        server.settings.stateless_http = True
        app = server.streamable_http_app()
        app.add_middleware(auth_context.ConsumerKeyAuthMiddleware)
        return TestClient(app, headers={"accept": _ACCEPT})

    yield _make
    from config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def _fake_list_podcasts(monkeypatch):
    _ensure_src_rag_package()
    from rag.mcp import server as mcp_server

    async def _fake():
        return {"podcasts": [{"slug": "langtalks", "title": "LangTalks", "chunk_count": 1}]}

    monkeypatch.setattr(mcp_server, "list_podcasts", _fake)


async def test_keyless_initialize_and_list_podcasts_succeed(monkeypatch, _client_factory, _fake_list_podcasts):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "true")

    with _client_factory() as client:
        init = client.post("/mcp", json=_INIT_BODY)
        assert init.status_code == 200

        resp = client.post("/mcp", json=_tool_call("list_podcasts"))
        assert resp.status_code == 200
        msg = _parse_result(resp)
        assert "error" not in msg
        assert not msg["result"].get("isError", False)
        payload = json.loads(msg["result"]["content"][0]["text"])
        assert payload["podcasts"][0]["slug"] == "langtalks"


async def test_keyless_rejected_when_flag_off(monkeypatch, _client_factory):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "false")

    with _client_factory() as client:
        resp = client.post("/mcp", json=_INIT_BODY)
        assert resp.status_code == 401


async def test_keyless_over_quota_is_clean_error_with_zero_embeddings(monkeypatch, _client_factory):
    monkeypatch.setenv("RAG_MCP_ANONYMOUS_ENABLED", "true")

    # Build the app FIRST: the factory's shadow-eviction can re-import rag.mcp.*,
    # so patches must target the module instances the built server actually uses.
    with _client_factory() as client:
        from unittest.mock import AsyncMock, MagicMock

        from rag.mcp import tools as mcp_tools
        from rag.quota.admission import ADMISSION_REASON_DAILY_QUOTA, QueryAdmissionError

        # Trip the per-IP daily quota; count any attempt to reach retrieval/embedding.
        embed_calls = {"n": 0}

        async def _fake_retrieve(self, *args, **kwargs):
            embed_calls["n"] += 1
            raise AssertionError("retrieval must not run on the rejected path")

        monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)
        monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _fake_retrieve)
        monkeypatch.setattr(mcp_tools, "_get_quota_repo", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(
            mcp_tools,
            "enforce_anonymous_admission",
            AsyncMock(side_effect=QueryAdmissionError("Daily keyless quota exceeded", reason=ADMISSION_REASON_DAILY_QUOTA)),
        )
        monkeypatch.setattr(mcp_tools, "emit_reject", MagicMock())

        resp = client.post("/mcp", json=_tool_call("search_podcasts", {"query": "anything"}))
        assert resp.status_code == 200  # JSON-RPC layer: transport OK, tool errored
        msg = _parse_result(resp)
        assert msg["result"]["isError"] is True
        assert "quota" in msg["result"]["content"][0]["text"].lower()
        assert embed_calls["n"] == 0  # zero owner-paid embeddings on the rejected path
