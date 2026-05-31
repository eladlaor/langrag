"""Integration tests for `POST /agent/chat/stream`.

Asserts the SSE event taxonomy and ordering for both the happy-path
one-tool turn and the error path.

Re-uses the `agent_enabled_app` + `seeded_user` fixtures defined in
`test_chat_non_streaming.py` by importing them. The fakes inject a
scripted agent LLM that emits a tool call on the first invocation
followed by a final assistant message.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


class StreamingFakeAgentLLM:
    """Emits a queued AIMessage per ainvoke; supports bind_tools.

    The default script triggers ONE tool call (list_my_communities) then
    a final reply. That's enough to exercise the full SSE taxonomy:
    tool_call_started + tool_call_finished + token + done.
    """

    def __init__(self, replies: list[AIMessage]) -> None:
        self._replies = list(replies)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        if not self._replies:
            return AIMessage(content="")
        return self._replies.pop(0)


class FakeMemoryLLM:
    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        return AIMessage(content="[]")


def _install_runtime(monkeypatch, replies: list[AIMessage]):
    from agent import runtime as agent_runtime
    from agent.graph import build_agent_graph
    from agent.memory.mongodb_store import MongoDBStore
    from constants import COLLECTION_AGENT_MEMORIES
    from langgraph.checkpoint.memory import MemorySaver

    async def _build_runtime():
        import db.connection as conn_mod

        db = await conn_mod.get_database()

        class _Emb:
            def embed_text(self, text):
                h = hash(text) & 0xFFFF
                return [float((h + i) % 17) / 17.0 for i in range(16)]

        store = MongoDBStore(
            collection=db[COLLECTION_AGENT_MEMORIES],
            embedder=_Emb(),
            embedding_model="fake-embedder-v1",
        )
        agent_runtime._store = store

        async def _kickoff(p, c):
            return "stub-run"

        return await build_agent_graph(
            checkpointer=MemorySaver(),
            store=store,
            kickoff_fn=_kickoff,
            agent_llm_factory=lambda tools: StreamingFakeAgentLLM(replies),
            memory_llm_factory=lambda: FakeMemoryLLM(),
        )

    monkeypatch.setattr(agent_runtime, "_build_runtime", _build_runtime)


@pytest_asyncio.fixture
async def app_with_tool_call_then_reply(monkeypatch):
    """Agent script: emit one tool call to list_my_communities, then a final reply."""
    tool_call = {"name": "list_my_communities", "args": {}, "id": "call-1"}
    replies = [
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="You own mcp_israel."),
    ]
    monkeypatch.setenv("AGENT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    from agent import runtime as agent_runtime

    await agent_runtime.reset_agent_runtime()
    _install_runtime(monkeypatch, replies)

    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None

    import importlib

    import main

    importlib.reload(main)
    yield main.app
    await agent_runtime.reset_agent_runtime()
    await conn_mod.close_connection()
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def seeded_user():
    import db.connection as conn_mod
    from db.indexes import ensure_indexes
    from db.repositories.user_api_keys import UserApiKeysRepository
    from db.repositories.users import UsersRepository

    conn_mod._client = None
    conn_mod._database = None
    db = await conn_mod.get_database()
    await ensure_indexes(db)

    email = f"agent-stream-{uuid.uuid4().hex[:12]}@langrag.test"
    users = UsersRepository(db)
    keys = UserApiKeysRepository(db)
    user_id = await users.create_user(email=email, communities=["mcp_israel"])
    key_id, plaintext = await keys.issue_key(user_id=user_id, name="stream")
    try:
        yield user_id, plaintext
    finally:
        from constants import (
            COLLECTION_AGENT_MEMORIES,
            COLLECTION_AGENT_SESSIONS,
            COLLECTION_USER_API_KEYS,
            COLLECTION_USERS,
        )
        from custom_types.field_keys import (
            AgentMemoryKeys,
            AgentSessionKeys,
            UserApiKeyKeys,
            UserKeys,
        )

        await db[COLLECTION_USER_API_KEYS].delete_one({UserApiKeyKeys.KEY_ID: key_id})
        await db[COLLECTION_USERS].delete_one({UserKeys.USER_ID: user_id})
        await db[COLLECTION_AGENT_MEMORIES].delete_many({AgentMemoryKeys.USER_ID: user_id})
        await db[COLLECTION_AGENT_SESSIONS].delete_many({AgentSessionKeys.USER_ID: user_id})


def _parse_sse(text: str) -> list[dict]:
    """Parse a multi-event SSE response body into a list of {event, data} dicts."""
    events: list[dict] = []
    chunks = text.split("\n\n")
    for chunk in chunks:
        if not chunk.strip():
            continue
        event_type = None
        data = None
        for line in chunk.split("\n"):
            if line.startswith("event: "):
                event_type = line[len("event: "):].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    data = line[len("data: "):]
        if event_type is not None:
            events.append({"event": event_type, "data": data})
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_stream_emits_tool_call_round_trip_and_done(
    app_with_tool_call_then_reply, seeded_user
):
    user_id, key = seeded_user
    transport = ASGITransport(app=app_with_tool_call_then_reply)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/agent/sessions",
            json={"title": "stream-t"},
            headers={"X-API-Key": key},
        )
        assert r.status_code == 201
        session_id = r.json()["session_id"]

        r = await client.post(
            "/api/agent/chat/stream",
            json={"session_id": session_id, "message": "what can I do?"},
            headers={"X-API-Key": key},
        )
        assert r.status_code == 200
        events = _parse_sse(r.text)

    types = [e["event"] for e in events]
    # The taxonomy we expect for this scripted turn, in order:
    #   tool_call_started → tool_call_finished → token → done
    assert "tool_call_started" in types, types
    assert "tool_call_finished" in types, types
    assert "token" in types, types
    assert types[-1] == "done", types
    assert types.index("tool_call_started") < types.index("tool_call_finished")
    # Token comes AFTER both tool events.
    assert types.index("tool_call_finished") < types.index("token")

    # Tool call carries name + call_id; finished carries matching call_id.
    started = next(e for e in events if e["event"] == "tool_call_started")
    finished = next(e for e in events if e["event"] == "tool_call_finished")
    assert started["data"]["tool"] == "list_my_communities"
    assert started["data"]["call_id"] == finished["data"]["call_id"]
    # ACL passed → status success; result_summary mentions the user's community.
    assert finished["data"]["status"] == "success"
    assert "mcp_israel" in finished["data"]["result_summary"]


async def test_stream_session_not_found_emits_error(
    app_with_tool_call_then_reply, seeded_user
):
    """A request against a non-existent session must emit one `error`
    event (not 404 — the connection has already opened) and NOT a `done`."""
    user_id, key = seeded_user
    transport = ASGITransport(app=app_with_tool_call_then_reply)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/agent/chat/stream",
            json={"session_id": "does-not-exist", "message": "x"},
            headers={"X-API-Key": key},
        )
    events = _parse_sse(r.text)
    assert any(e["event"] == "error" for e in events)
    assert not any(e["event"] == "done" for e in events)


async def test_stream_requires_api_key(app_with_tool_call_then_reply):
    transport = ASGITransport(app=app_with_tool_call_then_reply)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/agent/chat/stream",
            json={"session_id": "x", "message": "y"},
        )
    # 401 happens BEFORE the stream opens, so this is a plain HTTP error.
    assert r.status_code == 401


async def test_resume_endpoint_exists_and_validates_session(
    app_with_tool_call_then_reply, seeded_user
):
    """v1.13.0 ships the resume endpoint contract; actual interrupt
    routing is wired in commit 10. This test just locks in the path
    + the session-validation behavior so the frontend can target it."""
    user_id, key = seeded_user
    transport = ASGITransport(app=app_with_tool_call_then_reply)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/agent/chat/resume",
            json={"session_id": "does-not-exist", "decision": "approve"},
            headers={"X-API-Key": key},
        )
    assert r.status_code == 200  # stream opens
    events = _parse_sse(r.text)
    assert any(e["event"] == "error" for e in events)
