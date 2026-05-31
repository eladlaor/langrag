"""Tests for the community-introspection tools."""

from __future__ import annotations

import pytest

from agent.auth.acl import CommunityPermissionError
from agent.auth.user_context import NoUserContextError, UserContext, user_context
from agent.tools.community_tools import build_community_tools

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


async def test_list_my_communities_returns_user_communities():
    tools = build_community_tools()
    list_mine = _by_name(tools, "list_my_communities")
    with user_context(_ctx("mcp_israel", "langtalks")):
        out = await list_mine.ainvoke({})
    assert out == ["mcp_israel", "langtalks"]


async def test_list_my_communities_without_context_raises():
    tools = build_community_tools()
    list_mine = _by_name(tools, "list_my_communities")
    with pytest.raises(NoUserContextError):
        await list_mine.ainvoke({})


async def test_describe_community_owned_returns_structure():
    tools = build_community_tools()
    describe = _by_name(tools, "describe_community")
    with user_context(_ctx("mcp_israel")):
        out = await describe.ainvoke({"community_key": "mcp_israel"})
    assert out["community_key"] == "mcp_israel"
    assert "groups" in out
    assert isinstance(out["chat_names"], list)
    assert len(out["chat_names"]) > 0


async def test_describe_community_unowned_raises_permission_error():
    """ACL denial: tool must raise CommunityPermissionError, NOT return data."""
    tools = build_community_tools()
    describe = _by_name(tools, "describe_community")
    with user_context(_ctx("mcp_israel")):
        with pytest.raises(CommunityPermissionError) as exc_info:
            await describe.ainvoke({"community_key": "langtalks"})
    assert exc_info.value.community_key == "langtalks"


async def test_describe_community_unknown_raises_value_error():
    tools = build_community_tools()
    describe = _by_name(tools, "describe_community")
    with user_context(_ctx("mcp_israel")):
        with pytest.raises(ValueError, match="Unknown community"):
            await describe.ainvoke({"community_key": "not-a-community"})
