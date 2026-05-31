"""Integration test for `POST /agent/chat` (non-streaming).

Spins up the FastAPI app with `AGENT_ENABLED=true`, the real
`MongoDBStore` against the docker MongoDB, and a fake agent LLM so we
don't depend on Anthropic.

Tests target three invariants:
  - 401 without an API key.
  - 404 when `AGENT_ENABLED=false`.
  - End-to-end happy path: create session + chat returns the fake
    assistant reply with the user_id correctly propagated.

The end-to-end test uses `httpx.AsyncClient` + `ASGITransport` instead of
the synchronous `TestClient`. `TestClient` runs the FastAPI app on its
own anyio-managed loop while pytest-asyncio runs the test on a separate
loop; that cross-loop arrangement breaks Motor (each Motor client is
bound to the loop it was constructed in). ASGITransport runs the app
in-process on the test's loop, so there's exactly one loop for both
Motor and ASGI.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from tests._helpers.mongo import requires_mongodb

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

pytestmark = [requires_mongodb, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAgentLLM:
    def __init__(self, reply_text: str) -> None:
        self._reply_text = reply_text

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        return AIMessage(content=self._reply_text)


class FakeMemoryLLM:
    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        return AIMessage(content="[]")


def _install_fake_runtime(monkeypatch):
    """Replace agent runtime's builder with a fake-LLM, MemorySaver build."""
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
            agent_llm_factory=lambda tools: FakeAgentLLM("Short."),
            memory_llm_factory=lambda: FakeMemoryLLM(),
        )

    monkeypatch.setattr(agent_runtime, "_build_runtime", _build_runtime)


@pytest_asyncio.fixture
async def agent_enabled_app(monkeypatch):
    monkeypatch.setenv("AGENT_ENABLED", "true")
    from config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    from agent import runtime as agent_runtime

    await agent_runtime.reset_agent_runtime()
    _install_fake_runtime(monkeypatch)

    # Reset connection singletons so the app uses a client bound to the
    # current event loop (the one ASGITransport will run on).
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
    """Create a fresh user + api_key for the duration of one test."""
    import db.connection as conn_mod
    from db.indexes import ensure_indexes
    from db.repositories.user_api_keys import UserApiKeysRepository
    from db.repositories.users import UsersRepository

    conn_mod._client = None
    conn_mod._database = None
    db = await conn_mod.get_database()
    await ensure_indexes(db)

    email = f"agent-it-{uuid.uuid4().hex[:12]}@langrag.test"
    users = UsersRepository(db)
    keys = UserApiKeysRepository(db)
    user_id = await users.create_user(email=email, communities=["mcp_israel"])
    key_id, plaintext = await keys.issue_key(user_id=user_id, name="it")
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_session_create_requires_api_key(agent_enabled_app):
    transport = ASGITransport(app=agent_enabled_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/agent/sessions", json={"title": "x"})
    assert resp.status_code == 401


async def test_routes_absent_when_agent_disabled(monkeypatch):
    """If AGENT_ENABLED=false, /api/agent/* must 404."""
    monkeypatch.setenv("AGENT_ENABLED", "false")
    from config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    import importlib

    import main

    importlib.reload(main)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/agent/sessions", json={"title": "x"})
    get_settings.cache_clear()  # type: ignore[attr-defined]
    assert resp.status_code == 404


async def test_chat_end_to_end_returns_assistant_reply(agent_enabled_app, seeded_user):
    user_id, key = seeded_user
    transport = ASGITransport(app=agent_enabled_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create session.
        r = await client.post(
            "/api/agent/sessions",
            json={"title": "t", "community_context": "mcp_israel"},
            headers={"X-API-Key": key},
        )
        assert r.status_code == 201, r.text
        session_id = r.json()["session_id"]

        # Chat turn.
        r = await client.post(
            "/api/agent/chat",
            json={"session_id": session_id, "message": "hello agent"},
            headers={"X-API-Key": key},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == session_id
        assert body["assistant_message"] == "Short."
        assert body["tool_calls"] == []

        # Session listing must include this session.
        r = await client.get("/api/agent/sessions", headers={"X-API-Key": key})
        assert r.status_code == 200
        titles = [s["title"] for s in r.json()]
        assert "t" in titles
