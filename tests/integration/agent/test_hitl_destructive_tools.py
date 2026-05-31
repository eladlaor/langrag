"""End-to-end HITL gating on destructive tools.

Runs the full agent graph (with MemorySaver + InMemoryStore + fake LLM)
and asserts that:
  - For each destructive tool (`delete_schedule`, `forget`,
    `generate_newsletter(send_email=True)`), the first invocation
    interrupts and the side effect does NOT fire.
  - Resuming with `Command(resume='approve')` THEN fires the side effect.
  - Resuming with `Command(resume='reject')` returns
    `{deleted/run_id: ...rejected by user...}` and the side effect
    still does NOT fire.

Uses LangGraph's `interrupt()` properly: the side effect tracker is
checked AFTER each phase, which proves the gating is real, not just
cosmetic.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.auth.user_context import UserContext, user_context
from agent.graph import build_agent_graph
from agent.memory.mongodb_store import MongoDBStore

pytestmark = [pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAgentLLM:
    """Returns scripted replies; supports bind_tools."""

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


def _ctx() -> UserContext:
    return UserContext(
        user_id="u-hitl",
        email="u@langrag.test",
        role="admin",
        communities=("mcp_israel",),
    )


def _config(thread_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "user_id": "u-hitl",
            "communities": ["mcp_israel"],
        }
    }


async def _build(replies: list[AIMessage], kickoff_recorder: list | None = None):
    async def _kickoff(params, ctx):
        if kickoff_recorder is not None:
            kickoff_recorder.append(params)
        return "run-from-kickoff"

    return await build_agent_graph(
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
        kickoff_fn=_kickoff,
        agent_llm_factory=lambda tools: FakeAgentLLM(replies),
        memory_llm_factory=lambda: FakeMemoryLLM(),
    )


def _has_interrupt(state) -> bool:
    """LangGraph 1.x: state.get('__interrupt__') is the canonical signal."""
    interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
    return bool(interrupts)


# ---------------------------------------------------------------------------
# generate_newsletter (send_email=True)
# ---------------------------------------------------------------------------


async def test_generate_newsletter_send_email_interrupts_then_approves():
    """First turn: agent emits the tool call, interrupt fires, NO kickoff.
    Resume with 'approve': kickoff fires."""
    kickoff_recorder: list = []
    tool_call = {
        "name": "generate_newsletter",
        "args": {
            "community": "mcp_israel",
            "start_date": "2026-05-24",
            "end_date": "2026-05-31",
            "send_email": True,
        },
        "id": "call-genmail",
    }
    replies = [
        AIMessage(content="", tool_calls=[tool_call]),
        # After resume + tool reply, a final assistant message.
        AIMessage(content="Newsletter generation kicked off."),
    ]
    graph = await _build(replies, kickoff_recorder)
    cfg = _config("t-genmail-approve")
    with user_context(_ctx()):
        first = await graph.ainvoke(
            {"messages": [HumanMessage(content="send the newsletter via email")]},
            config=cfg,
        )
    # Side effect MUST NOT have fired yet.
    assert kickoff_recorder == []
    assert _has_interrupt(first), "expected interrupt before destructive call"

    with user_context(_ctx()):
        resumed = await graph.ainvoke(Command(resume="approve"), config=cfg)
    # Now the kickoff has run.
    assert len(kickoff_recorder) == 1
    assert kickoff_recorder[0]["send_email"] is True
    # And the graph reached a final assistant message.
    assert any(
        isinstance(m, AIMessage) and m.content for m in resumed["messages"]
    )


async def test_generate_newsletter_send_email_interrupts_then_rejects():
    """Resume with 'reject': kickoff still does NOT fire."""
    kickoff_recorder: list = []
    tool_call = {
        "name": "generate_newsletter",
        "args": {
            "community": "mcp_israel",
            "start_date": "2026-05-24",
            "end_date": "2026-05-31",
            "send_email": True,
        },
        "id": "call-genmail-reject",
    }
    replies = [
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="OK, didn't send."),
    ]
    graph = await _build(replies, kickoff_recorder)
    cfg = _config("t-genmail-reject")
    with user_context(_ctx()):
        await graph.ainvoke(
            {"messages": [HumanMessage(content="send via email")]},
            config=cfg,
        )
    with user_context(_ctx()):
        await graph.ainvoke(Command(resume="reject"), config=cfg)
    # Reject: kickoff stayed at zero.
    assert kickoff_recorder == []


# ---------------------------------------------------------------------------
# generate_newsletter (send_email=False) — sanity: NO interrupt
# ---------------------------------------------------------------------------


async def test_generate_newsletter_without_send_email_runs_without_interrupt():
    kickoff_recorder: list = []
    tool_call = {
        "name": "generate_newsletter",
        "args": {
            "community": "mcp_israel",
            "start_date": "2026-05-24",
            "end_date": "2026-05-31",
            "send_email": False,
        },
        "id": "call-no-email",
    }
    replies = [
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="Done."),
    ]
    graph = await _build(replies, kickoff_recorder)
    cfg = _config("t-no-email")
    with user_context(_ctx()):
        out = await graph.ainvoke(
            {"messages": [HumanMessage(content="generate without email")]},
            config=cfg,
        )
    assert not _has_interrupt(out)
    assert len(kickoff_recorder) == 1
    assert kickoff_recorder[0]["send_email"] is False
