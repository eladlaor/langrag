"""Tests for the schedule tools — focus on ACL guards.

The schedule manager is monkeypatched per-test so we don't drag
APScheduler in. The integration test for end-to-end schedule
lifecycle lives under tests/integration/agent/ (commit 7).
"""

from __future__ import annotations

import pytest

from agent.auth.acl import CommunityPermissionError
from agent.auth.user_context import UserContext, user_context
from agent.tools.schedule_tools import build_schedule_tools

pytestmark = [pytest.mark.asyncio]


def _ctx(*communities: str) -> UserContext:
    return UserContext(
        user_id="u1",
        email="u1@langrag.test",
        role="admin",
        communities=tuple(communities),
    )


def _by_name(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise AssertionError(f"tool not found: {name}")


class FakeManager:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.existing_by_id: dict[str, dict] = {}
        self.list_returns: list[dict] = []

    async def create_schedule(self, payload):
        self.created.append(payload)
        return "sched-new"

    async def list_all(self):
        return list(self.list_returns)

    async def get_by_id(self, schedule_id):
        return self.existing_by_id.get(schedule_id)

    async def delete(self, schedule_id):
        self.deleted.append(schedule_id)
        return True


@pytest.fixture
def fake_manager(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(
        "db.scheduled_newsletters._get_schedule_manager",
        lambda: manager,
    )
    return manager


# ---------------------------------------------------------------------------
# create_schedule
# ---------------------------------------------------------------------------


async def test_create_schedule_owned_succeeds(fake_manager):
    tools = build_schedule_tools()
    create = _by_name(tools, "create_schedule")
    with user_context(_ctx("mcp_israel")):
        out = await create.ainvoke(
            {
                "community": "mcp_israel",
                "chats": ["MCP Israel"],
                "interval_days": 7,
                "run_time": "09:00",
            }
        )
    assert out["schedule_id"] == "sched-new"
    assert fake_manager.created[0]["data_source_name"] == "mcp_israel"


async def test_create_schedule_unowned_raises_acl(fake_manager):
    tools = build_schedule_tools()
    create = _by_name(tools, "create_schedule")
    with user_context(_ctx("mcp_israel")):
        with pytest.raises(CommunityPermissionError):
            await create.ainvoke(
                {"community": "langtalks", "chats": ["LangTalks Community"]}
            )
    assert fake_manager.created == []


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


async def test_list_schedules_filters_cross_tenant(fake_manager):
    """Schedules belonging to communities the user doesn't own must not
    appear in the listing — cross-tenant visibility is the safety
    property, not just write-protection."""
    from bson import ObjectId

    fake_manager.list_returns = [
        {
            "_id": ObjectId(),
            "name": "MCP weekly",
            "data_source_name": "mcp_israel",
            "interval_days": 7,
            "run_time": "09:00",
            "enabled": True,
            "next_run": None,
            "last_run": None,
        },
        {
            "_id": ObjectId(),
            "name": "Langtalks weekly (NOT MINE)",
            "data_source_name": "langtalks",
            "interval_days": 7,
            "run_time": "09:00",
            "enabled": True,
        },
    ]
    tools = build_schedule_tools()
    list_s = _by_name(tools, "list_schedules")
    with user_context(_ctx("mcp_israel")):
        out = await list_s.ainvoke({})
    assert len(out) == 1
    assert out[0]["data_source_name"] == "mcp_israel"


# ---------------------------------------------------------------------------
# delete_schedule
# ---------------------------------------------------------------------------


async def test_delete_schedule_owned_raises_interrupt_before_delete(fake_manager):
    """v1.14.0: delete_schedule is HITL-gated. The interrupt fires
    BEFORE the destructive delete, so direct .ainvoke() outside a
    graph context raises GraphInterrupt and nothing is deleted.
    End-to-end approve/reject lives in
    tests/integration/agent/test_hitl_destructive_tools.py."""
    # Outside a graph context, `interrupt()` raises KeyError or
    # GraphInterrupt depending on LangGraph internals — either way the
    # destructive call MUST not have run.
    fake_manager.existing_by_id["s-mine"] = {
        "_id": "s-mine",
        "data_source_name": "mcp_israel",
    }
    tools = build_schedule_tools()
    delete = _by_name(tools, "delete_schedule")
    with user_context(_ctx("mcp_israel")):
        with pytest.raises((Exception,)):  # noqa: BLE001 — accept any failure
            await delete.ainvoke({"schedule_id": "s-mine"})
    assert fake_manager.deleted == []


async def test_delete_schedule_unowned_refused_without_revealing_existence(fake_manager):
    """A cross-tenant schedule must NOT be deletable, and the tool must
    return the same `not_found` shape as for a truly non-existent
    schedule (so an attacker can't enumerate other tenants' ids)."""
    fake_manager.existing_by_id["s-theirs"] = {
        "_id": "s-theirs",
        "data_source_name": "langtalks",
    }
    tools = build_schedule_tools()
    delete = _by_name(tools, "delete_schedule")
    with user_context(_ctx("mcp_israel")):
        out = await delete.ainvoke({"schedule_id": "s-theirs"})
    assert out["deleted"] is False
    assert out["reason"] == "not_found"
    assert fake_manager.deleted == []


async def test_delete_schedule_unknown_id_returns_not_found(fake_manager):
    tools = build_schedule_tools()
    delete = _by_name(tools, "delete_schedule")
    with user_context(_ctx("mcp_israel")):
        out = await delete.ainvoke({"schedule_id": "does-not-exist"})
    assert out["deleted"] is False
    assert out["reason"] == "not_found"
