"""Tests for the newsletter tools (focus on ACL and kickoff_fn wiring).

The repo-backed reads (`get_run_status`, `list_recent_runs`, `get_newsletter`)
are exercised in commit 7's integration tests against real Mongo data.
Here we test the ACL guards and the kickoff_fn protocol — the parts
that wouldn't be caught by the live-run integration tests.
"""

from __future__ import annotations

import pytest

from agent.auth.acl import CommunityPermissionError
from agent.auth.user_context import UserContext, user_context
from agent.tools.newsletter_tools import build_newsletter_tools

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


# ---------------------------------------------------------------------------
# generate_newsletter — ACL + kickoff_fn dispatch
# ---------------------------------------------------------------------------


async def test_generate_newsletter_owned_invokes_kickoff_and_returns_run_id():
    captured: list[tuple] = []

    async def kickoff(params, ctx):
        captured.append((params, ctx.user_id))
        return "run-abc"

    tools = build_newsletter_tools(kickoff_fn=kickoff)
    gen = _by_name(tools, "generate_newsletter")
    with user_context(_ctx("mcp_israel")):
        out = await gen.ainvoke(
            {
                "community": "mcp_israel",
                "start_date": "2026-05-20",
                "end_date": "2026-05-27",
                "desired_language": "hebrew",
            }
        )
    assert out["run_id"] == "run-abc"
    assert len(captured) == 1
    params, user_id = captured[0]
    assert params["community"] == "mcp_israel"
    assert params["desired_language"] == "hebrew"
    assert params["consolidate_chats"] is True
    assert user_id == "u1"


async def test_generate_newsletter_unowned_raises_acl_and_does_not_kickoff():
    """ACL must run BEFORE the kickoff_fn — a denied request must not
    fire the side effect at all."""
    kickoff_called = []

    async def kickoff(params, ctx):
        kickoff_called.append(True)
        return "should-not-be-returned"

    tools = build_newsletter_tools(kickoff_fn=kickoff)
    gen = _by_name(tools, "generate_newsletter")
    with user_context(_ctx("mcp_israel")):
        with pytest.raises(CommunityPermissionError):
            await gen.ainvoke(
                {
                    "community": "langtalks",
                    "start_date": "2026-05-20",
                    "end_date": "2026-05-27",
                }
            )
    assert kickoff_called == []


async def test_generate_newsletter_send_email_raises_interrupt_before_kickoff():
    """v1.14.0: send_email=True is HITL-gated; the interrupt fires
    BEFORE the kickoff so a rejected request never triggers the
    pipeline. End-to-end approve/reject in
    tests/integration/agent/test_hitl_destructive_tools.py."""
    captured: list[dict] = []

    async def kickoff(params, ctx):
        captured.append(params)
        return "run-x"

    tools = build_newsletter_tools(kickoff_fn=kickoff)
    gen = _by_name(tools, "generate_newsletter")
    with user_context(_ctx("mcp_israel")):
        with pytest.raises((Exception,)):  # noqa: BLE001
            await gen.ainvoke(
                {
                    "community": "mcp_israel",
                    "start_date": "2026-05-20",
                    "end_date": "2026-05-27",
                    "send_email": True,
                }
            )
    # Kickoff must NOT have fired — the interrupt is BEFORE the side effect.
    assert captured == []


async def test_generate_newsletter_without_send_email_skips_interrupt():
    """Non-destructive variant (send_email=False, the default) must run
    end-to-end without an interrupt."""
    captured: list[dict] = []

    async def kickoff(params, ctx):
        captured.append(params)
        return "run-x"

    tools = build_newsletter_tools(kickoff_fn=kickoff)
    gen = _by_name(tools, "generate_newsletter")
    with user_context(_ctx("mcp_israel")):
        out = await gen.ainvoke(
            {
                "community": "mcp_israel",
                "start_date": "2026-05-20",
                "end_date": "2026-05-27",
            }
        )
    assert out["run_id"] == "run-x"
    assert captured[0]["send_email"] is False
