"""REST-path refusal tests for the RAG chat endpoints.

Proves the empty-context guard on the two handlers the web UI / admins use:
`POST /rag/chat` (non-streaming) and `POST /rag/chat/stream` (SSE). When
retrieval yields empty context the handler MUST return the canonical refusal
and MUST NOT call the LLM.

Retrieval, the conversation manager, and the LLM are all faked, so these tests
are deterministic and need neither MongoDB nor OpenAI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

# NOTE: app-level imports (api.rag_conversation, rag.auth.*, constants) are
# deliberately deferred into the fixture below. This test package is
# `tests/integration/rag`, whose directory shadows the top-level `rag` package
# during pytest collection under prepend import mode; importing `rag.auth` at
# module top resolves against the test dir and fails. The other integration/rag
# tests follow the same defer-into-functions pattern.


_SESSION_ID = "test-session-refusal"


class _FakeManager:
    """In-memory stand-in for ConversationManager: records the assistant message."""

    last_assistant_content: str | None = None
    last_assistant_citations: list | None = None

    async def create_session(self, *args, **kwargs):
        return _SESSION_ID

    async def get_session(self, session_id, *args, **kwargs):
        return {"session_id": session_id}

    async def add_user_message(self, *args, **kwargs):
        return None

    async def get_conversation_history(self, *args, **kwargs):
        return []

    async def add_assistant_message(self, *, session_id, content, citations):
        type(self).last_assistant_content = content
        type(self).last_assistant_citations = citations
        return "msg-1"


def _empty_retrieval() -> dict[str, Any]:
    return {
        "context": "",
        "citations": [],
        "freshness_warning": False,
        "oldest_source_date": None,
        "newest_source_date": None,
    }


@dataclass
class _Ctx:
    """Fixture context: the test ASGI app plus the constants the assertions need."""

    app: Any
    prefix: str
    refusal_no_content: str
    refusal_out_of_range: str
    route_chat: str
    route_chat_stream: str
    event_token: str
    event_done: str
    event_citation: str


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


@pytest.fixture
def ctx(monkeypatch) -> _Ctx:
    # Deferred app imports (see module docstring for why).
    _ensure_src_rag_package()
    import api.rag_conversation as rag_api
    from constants import (
        API_V1_PREFIX,
        RAG_REFUSAL_NO_CONTENT,
        RAG_REFUSAL_OUT_OF_RANGE,
        ROUTE_RAG_CHAT,
        ROUTE_RAG_CHAT_STREAM,
        RAGEventType,
    )
    from custom_types.field_keys import RAGApiKeyKeys
    from fastapi import FastAPI
    from rag.auth.dependencies import require_api_key

    # Stub the constructor so we don't build a real embedder (needs an API key).
    monkeypatch.setattr(rag_api.RetrievalPipeline, "__init__", lambda self: None)

    async def _fake_retrieve(self, *args, **kwargs):
        return _empty_retrieval()

    monkeypatch.setattr(rag_api.RetrievalPipeline, "retrieve", _fake_retrieve)
    monkeypatch.setattr(rag_api, "ConversationManager", _FakeManager)

    async def _boom_generate(*args, **kwargs):
        raise AssertionError("generate_answer must not be called on empty context")

    async def _boom_stream(*args, **kwargs):
        raise AssertionError("generate_answer_stream must not be called on empty context")
        yield  # pragma: no cover

    monkeypatch.setattr(rag_api, "generate_answer", _boom_generate)
    monkeypatch.setattr(rag_api, "generate_answer_stream", _boom_stream)

    _FakeManager.last_assistant_content = None
    _FakeManager.last_assistant_citations = None

    test_app = FastAPI()
    test_app.include_router(rag_api.router, prefix=API_V1_PREFIX)
    test_app.dependency_overrides[require_api_key] = lambda: {
        RAGApiKeyKeys.OWNER: "test-owner",
        RAGApiKeyKeys.KEY_ID: "test-key",
    }

    return _Ctx(
        app=test_app,
        prefix=API_V1_PREFIX,
        refusal_no_content=RAG_REFUSAL_NO_CONTENT,
        refusal_out_of_range=RAG_REFUSAL_OUT_OF_RANGE,
        route_chat=ROUTE_RAG_CHAT,
        route_chat_stream=ROUTE_RAG_CHAT_STREAM,
        event_token=str(RAGEventType.TOKEN),
        event_done=str(RAGEventType.DONE),
        event_citation=str(RAGEventType.CITATION),
    )


async def _post(ctx: _Ctx, route: str, payload: dict):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=ctx.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"{ctx.prefix}{route}", json=payload)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE byte stream into (event, data-dict) tuples."""
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if event is not None:
            events.append((event, data))
    return events


class TestNonStreamingRefusal:
    async def test_no_date_filter_refuses_with_no_content(self, ctx):
        resp = await _post(ctx, ctx.route_chat, {"query": "anything"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == ctx.refusal_no_content
        assert body["citations"] == []
        # Persisted to session history just like a normal answer.
        assert _FakeManager.last_assistant_content == ctx.refusal_no_content
        assert _FakeManager.last_assistant_citations == []

    async def test_date_filter_refuses_with_out_of_range(self, ctx):
        resp = await _post(
            ctx,
            ctx.route_chat,
            {"query": "anything", "date_start": "2030-01-01", "date_end": "2030-12-31"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == ctx.refusal_out_of_range
        assert body["citations"] == []


class TestStreamingRefusal:
    async def test_stream_emits_single_refusal_token_then_done(self, ctx):
        resp = await _post(ctx, ctx.route_chat_stream, {"query": "anything"})
        assert resp.status_code == 200
        events = _parse_sse(resp.text)

        token_events = [d for e, d in events if e == ctx.event_token]
        done_events = [d for e, d in events if e == ctx.event_done]
        citation_events = [d for e, d in events if e == ctx.event_citation]

        assert len(token_events) == 1
        assert token_events[0]["token"] == ctx.refusal_no_content
        assert citation_events == []
        assert len(done_events) == 1

    async def test_stream_with_date_filter_emits_out_of_range(self, ctx):
        resp = await _post(
            ctx,
            ctx.route_chat_stream,
            {"query": "anything", "date_start": "2030-01-01", "date_end": "2030-12-31"},
        )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        token_events = [d for e, d in events if e == ctx.event_token]
        assert len(token_events) == 1
        assert token_events[0]["token"] == ctx.refusal_out_of_range
