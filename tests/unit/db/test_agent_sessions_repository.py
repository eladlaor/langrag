"""Tests for AgentSessionsRepository (agentic chatbot layer)."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_types.field_keys import AgentSessionKeys
from db.repositories.agent_sessions import AgentSessionsRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_create_session_round_trip(db, unique_user_id):
    repo = AgentSessionsRepository(db)
    session_id = await repo.create_session(
        user_id=unique_user_id,
        title="test session",
        community_context="mcp_israel",
    )
    try:
        row = await repo.find_by_session_id(session_id)
        assert row is not None
        assert row[AgentSessionKeys.USER_ID] == unique_user_id
        assert row[AgentSessionKeys.TITLE] == "test session"
        assert row[AgentSessionKeys.COMMUNITY_CONTEXT] == "mcp_israel"
        assert row[AgentSessionKeys.MESSAGE_COUNT] == 0
        # Mongo returns naive UTC datetimes; compare against naive now()
        assert row[AgentSessionKeys.EXPIRES_AT] > datetime.utcnow()
    finally:
        await repo.delete_session(session_id)


async def test_touch_session_slides_ttl_and_increments_count(db, unique_user_id):
    repo = AgentSessionsRepository(db)
    session_id = await repo.create_session(user_id=unique_user_id)
    try:
        before = await repo.find_by_session_id(session_id)
        before_expires = before[AgentSessionKeys.EXPIRES_AT]
        before_count = before[AgentSessionKeys.MESSAGE_COUNT]
        ok = await repo.touch_session(session_id)
        assert ok is True
        after = await repo.find_by_session_id(session_id)
        assert after[AgentSessionKeys.EXPIRES_AT] >= before_expires
        assert after[AgentSessionKeys.MESSAGE_COUNT] == before_count + 1
    finally:
        await repo.delete_session(session_id)


async def test_find_for_user_sorted_newest_first(db, unique_user_id):
    repo = AgentSessionsRepository(db)
    s1 = await repo.create_session(user_id=unique_user_id, title="first")
    s2 = await repo.create_session(user_id=unique_user_id, title="second")
    try:
        # Touching s1 makes it the most recent
        await repo.touch_session(s1)
        listing = await repo.find_for_user(unique_user_id)
        assert listing[0][AgentSessionKeys.SESSION_ID] == s1
        assert any(r[AgentSessionKeys.SESSION_ID] == s2 for r in listing)
    finally:
        await repo.delete_session(s1)
        await repo.delete_session(s2)


async def test_update_cost(db, unique_user_id):
    repo = AgentSessionsRepository(db)
    session_id = await repo.create_session(user_id=unique_user_id)
    try:
        ok = await repo.update_cost(session_id, {"tokens_in": 100, "tokens_out": 50})
        assert ok is True
        row = await repo.find_by_session_id(session_id)
        assert row[AgentSessionKeys.COST_SO_FAR]["tokens_in"] == 100
    finally:
        await repo.delete_session(session_id)
