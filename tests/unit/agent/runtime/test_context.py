"""Tests for the `UserContext` `ContextVar` plumbing.

The big invariant: two concurrent agent turns running under the same
event loop must each see THEIR OWN `UserContext`, never the other's.
This is the production safety property — if one async task could read
another's context, a long-running tool could leak user_id across
tenants.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.auth.user_context import (
    NoUserContextError,
    UserContext,
    current_user_context,
    user_context,
)


def _ctx(name: str) -> UserContext:
    return UserContext(
        user_id=f"u-{name}",
        email=f"{name}@langrag.test",
        role="admin",
        communities=("mcp_israel",),
    )


def test_no_context_raises():
    with pytest.raises(NoUserContextError):
        current_user_context()


def test_context_manager_binds_and_clears():
    with user_context(_ctx("alice")) as ctx:
        assert current_user_context() is ctx
    with pytest.raises(NoUserContextError):
        current_user_context()


def test_context_manager_clears_on_exception():
    with pytest.raises(RuntimeError, match="boom"):
        with user_context(_ctx("alice")):
            raise RuntimeError("boom")
    with pytest.raises(NoUserContextError):
        current_user_context()


def test_nested_context_restores_outer():
    outer = _ctx("outer")
    inner = _ctx("inner")
    with user_context(outer):
        assert current_user_context() is outer
        with user_context(inner):
            assert current_user_context() is inner
        # Outer must be restored after the inner block exits.
        assert current_user_context() is outer
    with pytest.raises(NoUserContextError):
        current_user_context()


@pytest.mark.asyncio
async def test_concurrent_tasks_have_isolated_contexts():
    """Two concurrent tasks each set their own context and must read back
    their own — never the other's. This is the multi-tenant safety
    guarantee."""

    async def task(name: str, results: dict, gate: asyncio.Event) -> None:
        ctx = _ctx(name)
        with user_context(ctx):
            # Wait until both tasks have entered the with-block before
            # reading, so any leak would be observable.
            await gate.wait()
            results[name] = current_user_context().user_id

    results: dict[str, str] = {}
    gate = asyncio.Event()
    a = asyncio.create_task(task("alice", results, gate))
    b = asyncio.create_task(task("bob", results, gate))
    # Let both tasks bind their contexts before either reads.
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(a, b)
    assert results == {"alice": "u-alice", "bob": "u-bob"}


@pytest.mark.asyncio
async def test_child_task_inherits_parent_context():
    """ContextVar semantics: a task launched inside `with user_context(ctx)`
    inherits the binding (Python copies the context at task creation).
    This is the property that lets the agent graph's nodes read the
    user context without having to thread it through state explicitly."""
    parent_ctx = _ctx("parent")

    async def child() -> str:
        return current_user_context().user_id

    with user_context(parent_ctx):
        result = await asyncio.create_task(child())
    assert result == "u-parent"
