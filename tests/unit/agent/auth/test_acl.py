"""Tests for `assert_user_owns_community` and `filter_communities`."""

from __future__ import annotations

import pytest

from agent.auth.acl import (
    CommunityPermissionError,
    assert_user_owns_community,
    filter_communities,
)
from agent.auth.user_context import UserContext


def _ctx(*communities: str) -> UserContext:
    return UserContext(
        user_id="u1",
        email="u1@langrag.test",
        role="admin",
        communities=tuple(communities),
    )


# ---------------------------------------------------------------------------
# assert_user_owns_community
# ---------------------------------------------------------------------------


def test_owned_community_passes():
    ctx = _ctx("mcp_israel", "langtalks")
    # Must not raise.
    assert_user_owns_community(ctx, "mcp_israel")
    assert_user_owns_community(ctx, "langtalks")


def test_unowned_community_raises():
    ctx = _ctx("mcp_israel")
    with pytest.raises(CommunityPermissionError) as exc_info:
        assert_user_owns_community(ctx, "langtalks")
    err = exc_info.value
    assert err.user_id == "u1"
    assert err.community_key == "langtalks"
    # Subclass of PermissionError so a generic except catches it.
    assert isinstance(err, PermissionError)


def test_unknown_community_raises_value_error():
    """A typo from the LLM should not silently pass auth."""
    ctx = _ctx("mcp_israel")
    with pytest.raises(ValueError, match="Unknown community"):
        assert_user_owns_community(ctx, "not-a-community")


def test_empty_communities_always_denies():
    ctx = _ctx()
    with pytest.raises(CommunityPermissionError):
        assert_user_owns_community(ctx, "mcp_israel")


# ---------------------------------------------------------------------------
# filter_communities
# ---------------------------------------------------------------------------


def test_filter_strips_unauthorized():
    ctx = _ctx("mcp_israel")
    out = filter_communities(ctx, ["mcp_israel", "langtalks"])
    assert out == ["mcp_israel"]


def test_filter_drops_unknown_silently():
    """filter_communities does NOT raise on unknown keys; it logs+drops."""
    ctx = _ctx("mcp_israel", "langtalks")
    out = filter_communities(ctx, ["mcp_israel", "not-a-thing", "langtalks"])
    assert out == ["mcp_israel", "langtalks"]


def test_filter_preserves_order():
    ctx = _ctx("ail", "mcp_israel", "langtalks")
    out = filter_communities(ctx, ["langtalks", "mcp_israel"])
    assert out == ["langtalks", "mcp_israel"]


def test_filter_with_empty_request_returns_empty():
    assert filter_communities(_ctx("mcp_israel"), []) == []
