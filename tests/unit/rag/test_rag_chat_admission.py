"""Admission-control tests for the REST RAG chat handlers.

Mounts only rag_conversation.router on a bare FastAPI app with auth disabled and
ConversationManager / RetrievalPipeline / generate_answer stubbed to fast, DB-free
fakes. Asserts:
  - 503 + Retry-After (not 200/500) when the cap is hit, on BOTH /rag/chat and
    /rag/chat/stream (the latter proving outer-scope acquire before StreamingResponse).
  - the slot is released after success, after a downstream error, after the stream
    completes, and on client disconnect.
Runs WITHOUT Docker.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.rag_conversation as rc
from config import get_settings
from constants import (
    HTTP_DETAIL_INTERNAL_ERROR,
    HTTP_DETAIL_RAG_OVERLOADED,
    HTTP_HEADER_RETRY_AFTER,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
    HTTP_STATUS_OK,
    HTTP_STATUS_SERVICE_UNAVAILABLE,
    ROUTE_RAG_CHAT,
    ROUTE_RAG_CHAT_STREAM,
    API_V1_PREFIX,
    RAGEventType,
)
from rag.concurrency import guard


RETRY_AFTER_SECONDS = 5


class _FakeConversationManager:
    async def create_session(self, *args, **kwargs):
        return "sess-1"

    async def get_session(self, *args, **kwargs):
        return {"session_id": "sess-1"}

    async def add_user_message(self, *args, **kwargs):
        return None

    async def get_conversation_history(self, *args, **kwargs):
        return []

    async def add_assistant_message(self, *args, **kwargs):
        return "msg-1"


class _FakePipeline:
    def __init__(self):
        pass

    async def retrieve(self, *args, **kwargs):
        return {
            "context": "grounded context",
            "citations": [{"index": 0, "chunk_id": "c1"}],
            "freshness_warning": False,
            "oldest_source_date": None,
            "newest_source_date": None,
        }


async def _fake_generate_answer(*args, **kwargs):
    return "the answer"


async def _fake_generate_answer_stream(*args, **kwargs):
    for tok in ("hello ", "world"):
        yield tok


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings().rag, "concurrency_retry_after_seconds", RETRY_AFTER_SECONDS, raising=False)
    monkeypatch.setattr(rc, "ConversationManager", _FakeConversationManager)
    monkeypatch.setattr(rc, "RetrievalPipeline", _FakePipeline)
    monkeypatch.setattr(rc, "generate_answer", _fake_generate_answer)
    monkeypatch.setattr(rc, "generate_answer_stream", _fake_generate_answer_stream)

    app = FastAPI()
    app.include_router(rc.router, prefix=API_V1_PREFIX)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def set_cap(monkeypatch):
    def _set(cap: int) -> None:
        monkeypatch.setattr(get_settings().rag, "max_concurrent_requests", cap, raising=False)
        guard._reset_for_tests()

    yield _set
    guard._reset_for_tests()


def _chat_url() -> str:
    return f"{API_V1_PREFIX}{ROUTE_RAG_CHAT}"


def _stream_url() -> str:
    return f"{API_V1_PREFIX}{ROUTE_RAG_CHAT_STREAM}"


def _prefill_to_cap(cap: int) -> None:
    """Synchronously fill the guard to capacity from a sync test body."""
    import asyncio

    async def _fill():
        for _ in range(cap):
            assert await guard.try_acquire() is True

    asyncio.get_event_loop().run_until_complete(_fill())


def test_rag_chat_returns_503_with_retry_after_when_full(client, set_cap):
    set_cap(1)
    _prefill_to_cap(1)
    resp = client.post(_chat_url(), json={"query": "hi"})
    assert resp.status_code == HTTP_STATUS_SERVICE_UNAVAILABLE
    assert resp.json()["detail"] == HTTP_DETAIL_RAG_OVERLOADED
    assert resp.headers[HTTP_HEADER_RETRY_AFTER] == str(RETRY_AFTER_SECONDS)


def test_rag_chat_succeeds_when_slot_available(client, set_cap):
    set_cap(1)
    resp = client.post(_chat_url(), json={"query": "hi"})
    assert resp.status_code == HTTP_STATUS_OK
    assert guard.current_in_flight() == 0


def test_rag_chat_releases_slot_on_downstream_error(client, set_cap, monkeypatch):
    set_cap(1)

    async def _boom(*args, **kwargs):
        raise RuntimeError("generation exploded")

    monkeypatch.setattr(rc, "generate_answer", _boom)
    resp = client.post(_chat_url(), json={"query": "hi"})
    assert resp.status_code == HTTP_STATUS_INTERNAL_SERVER_ERROR
    assert resp.json()["detail"] == HTTP_DETAIL_INTERNAL_ERROR
    # Slot must NOT leak — proves rag_slot() encloses the error-mapping try.
    assert guard.current_in_flight() == 0


def test_rag_chat_stream_returns_503_before_stream_when_full(client, set_cap):
    set_cap(1)
    _prefill_to_cap(1)
    resp = client.post(_stream_url(), json={"query": "hi"})
    # A 503 status line (not a 200 SSE stream) proves outer-scope acquisition.
    assert resp.status_code == HTTP_STATUS_SERVICE_UNAVAILABLE
    assert resp.headers[HTTP_HEADER_RETRY_AFTER] == str(RETRY_AFTER_SECONDS)


def test_rag_chat_stream_releases_slot_after_stream_completes(client, set_cap):
    set_cap(1)
    resp = client.post(_stream_url(), json={"query": "hi"})
    assert resp.status_code == HTTP_STATUS_OK
    # Drain the whole stream to DONE.
    body = resp.text
    assert str(RAGEventType.DONE) in body
    assert guard.current_in_flight() == 0


def test_rag_chat_stream_releases_slot_on_client_disconnect(client, set_cap):
    set_cap(1)
    # Use the streaming context manager and close it after reading one line,
    # WITHOUT draining. Exiting the context aclose()s the underlying generator,
    # whose finally releases the slot.
    with client.stream("POST", _stream_url(), json={"query": "hi"}) as resp:
        assert resp.status_code == HTTP_STATUS_OK
        for _ in resp.iter_lines():
            break  # read one line, then abandon the stream
    assert guard.current_in_flight() == 0
