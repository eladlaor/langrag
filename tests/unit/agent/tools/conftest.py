"""Shared fixtures for the agent tool suite."""

from __future__ import annotations

import os

import pytest

from agent.auth.user_context import UserContext, user_context

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")


def _ctx(communities: tuple[str, ...] = ("mcp_israel",)) -> UserContext:
    return UserContext(
        user_id="u-test",
        email="u@langrag.test",
        role="admin",
        communities=communities,
    )


@pytest.fixture
def active_user_context():
    """Set up a UserContext for tools that read the contextvar."""
    return _ctx


@pytest.fixture
def bound_user(active_user_context):
    """Convenience: yield a bound context for the duration of the test."""
    ctx = active_user_context()
    with user_context(ctx):
        yield ctx
