"""Tests for the agent `StateGraph` routing.

Uses fake LLMs (no Anthropic) and `MemorySaver` + `InMemoryStore` so the
test runs without any external services. The two paths the test
exercises are:

  1. No-tool-call flow: agent → extract_memory → END.
  2. One-tool-call flow: agent → tools → check_budget → agent → extract_memory.

The headline assertions:
  - `user_id` + `communities` reach the state from `configurable`.
  - Tool calls dispatch correctly and the ToolMessage is added to state.
  - ACL denials surface as `ToolMessage(status="error")`, NOT as crashes.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from agent.auth.user_context import UserContext, user_context
from agent.graph import build_agent_graph
from graphs.state_keys import AgentStateKeys as Keys

pytestmark = [pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAgentLLM:
    """Returns a queued AIMessage per `ainvoke`. Supports `bind_tools`."""

    def __init__(self, replies: list[AIMessage]) -> None:
        self._replies = list(replies)
        self.calls: list[Any] = []
        self.bound_tools: list[Any] | None = None

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        self.calls.append(input)
        if not self._replies:
            return AIMessage(content="")
        return self._replies.pop(0)


class FakeMemoryLLM:
    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        # Extractor expects a JSON array; return [] so nothing is persisted.
        return AIMessage(content="[]")


async def _kickoff(params, ctx) -> str:
    return "stub-run-id"


def _ctx() -> UserContext:
    return UserContext(
        user_id="u-real",
        email="u@langrag.test",
        role="admin",
        communities=("mcp_israel",),
    )


async def _build(replies):
    fake_llm = FakeAgentLLM(replies)
    graph = await build_agent_graph(
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
        kickoff_fn=_kickoff,
        agent_llm_factory=lambda tools: fake_llm,
        memory_llm_factory=lambda: FakeMemoryLLM(),
    )
    return graph, fake_llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_no_tool_call_flow_propagates_user_context_to_state():
    """Smoke test for the happy path. The user_id from `configurable`
    must surface into the state — that's how the system prompt's memory
    block and downstream nodes know who's talking."""
    graph, llm = await _build([AIMessage(content="Hello!")])
    with user_context(_ctx()):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="hi")]},
            config={
                "configurable": {
                    "thread_id": "t1",
                    Keys.USER_ID: "u-real",
                    Keys.COMMUNITIES: ["mcp_israel"],
                }
            },
        )
    assert result.get(Keys.USER_ID) == "u-real"
    assert result.get(Keys.COMMUNITIES) == ["mcp_israel"]
    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert last.content == "Hello!"
    # The agent node ran once with the system prompt + 1 human message.
    assert len(llm.calls) == 1


async def test_tool_call_flow_round_trips_through_tools_node():
    """When the LLM emits a tool call, the tools node runs the tool and
    the result becomes a ToolMessage in state; the loop returns to the
    agent for a final reply."""
    # First LLM reply: a tool call to list_my_communities. Second reply:
    # a plain assistant message that ends the turn.
    tool_call = {"name": "list_my_communities", "args": {}, "id": "call-1"}
    replies = [
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="You own mcp_israel."),
    ]
    graph, _ = await _build(replies)
    with user_context(_ctx()):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="what can I do?")]},
            config={
                "configurable": {
                    "thread_id": "t2",
                    Keys.USER_ID: "u-real",
                    Keys.COMMUNITIES: ["mcp_israel"],
                }
            },
        )
    msgs = result["messages"]
    # Sequence: [user, ai(tool_call), tool_message, ai(final)]
    assert any(isinstance(m, ToolMessage) for m in msgs), [
        type(m).__name__ for m in msgs
    ]
    tool_msg = next(m for m in msgs if isinstance(m, ToolMessage))
    # The tool returned the user's communities (from the contextvar).
    assert "mcp_israel" in tool_msg.content
    # Final assistant message present.
    final_ai = [m for m in msgs if isinstance(m, AIMessage)][-1]
    assert "mcp_israel" in final_ai.content
    # tool_call_count incremented.
    assert result.get(Keys.TOOL_CALL_COUNT) == 1


async def test_acl_denial_surfaces_as_error_tool_message():
    """When the LLM tries a community the user doesn't own, the tool
    raises CommunityPermissionError; the graph must NOT crash — the
    ACL denial appears as a ToolMessage(status='error') so the LLM
    sees it on the next iteration."""
    bad_call = {
        "name": "describe_community",
        "args": {"community_key": "langtalks"},  # user owns only mcp_israel
        "id": "call-bad",
    }
    replies = [
        AIMessage(content="", tool_calls=[bad_call]),
        AIMessage(content="Sorry — you don't own langtalks."),
    ]
    graph, _ = await _build(replies)
    with user_context(_ctx()):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="describe langtalks please")]},
            config={
                "configurable": {
                    "thread_id": "t3",
                    Keys.USER_ID: "u-real",
                    Keys.COMMUNITIES: ["mcp_israel"],
                }
            },
        )
    msgs = result["messages"]
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].status == "error"
    assert "langtalks" in tool_msgs[0].content
    # Final assistant message still present — graph didn't crash.
    final_ai = [m for m in msgs if isinstance(m, AIMessage)][-1]
    assert final_ai.content


async def test_unknown_community_acl_check_is_value_error():
    """If the LLM hallucinates a community key, the tool raises
    ValueError (not CommunityPermissionError). The tool node must turn
    that into an error ToolMessage too."""
    bad_call = {
        "name": "describe_community",
        "args": {"community_key": "not-a-thing"},
        "id": "call-typo",
    }
    replies = [
        AIMessage(content="", tool_calls=[bad_call]),
        AIMessage(content="Let me try again."),
    ]
    graph, _ = await _build(replies)
    with user_context(_ctx()):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="describe X")]},
            config={
                "configurable": {
                    "thread_id": "t4",
                    Keys.USER_ID: "u-real",
                    Keys.COMMUNITIES: ["mcp_israel"],
                }
            },
        )
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].status == "error"
    assert "Unknown community" in tool_msgs[0].content


async def test_tool_call_count_caps_at_max_per_turn():
    """A runaway LLM that always emits a tool call must not loop forever
    — the budget node halts the loop once `tool_call_count` exceeds the
    configured ceiling."""
    # Emit one tool call per turn, each with a UNIQUE id so the add_messages
    # reducer doesn't dedupe them and the loop genuinely iterates. The default
    # AgentSettings.max_tool_calls_per_turn is 12.
    replies = [AIMessage(content="", tool_calls=[{"name": "list_my_communities", "args": {}, "id": f"loop-{i}"}]) for i in range(20)]
    graph, _ = await _build(replies)
    with user_context(_ctx()):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="loop")]},
            config={
                # Each tool iteration costs 3 super-steps (AGENT→TOOLS→CHECK_BUDGET);
                # raise the recursion limit above 12*3 so the BUDGET cap is what
                # halts the loop, not LangGraph's default step ceiling.
                "recursion_limit": 100,
                "configurable": {
                    "thread_id": "t5",
                    Keys.USER_ID: "u-real",
                    Keys.COMMUNITIES: ["mcp_israel"],
                },
            },
        )
    # Loop must have halted at the cap. With single-call turns the count
    # lands exactly on the ceiling and never exceeds it.
    assert result.get(Keys.TOOL_CALL_COUNT) == 12


async def test_tool_call_count_never_exceeds_cap_on_large_batch():
    """A single LLM turn that emits MANY tool calls at once must not blow
    past the per-turn ceiling. The tools node enforces the budget *before*
    executing, short-circuiting over-budget calls as error ToolMessages so
    tool_call_count can never exceed max_tool_calls_per_turn (12).

    This guards the off-by-N overshoot bug: previously the count was
    incremented by len(tool_calls) for the whole batch and only checked
    afterwards, letting an N-call batch overshoot by up to N-1.
    """
    # One AI turn emitting 20 tool calls at once (well over the cap of 12).
    big_batch = [{"name": "list_my_communities", "args": {}, "id": f"b-{i}"} for i in range(20)]
    replies = [
        AIMessage(content="", tool_calls=big_batch),
        AIMessage(content="done"),
    ]
    graph, _ = await _build(replies)
    with user_context(_ctx()):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="do everything at once")]},
            config={
                "configurable": {
                    "thread_id": "t6",
                    Keys.USER_ID: "u-real",
                    Keys.COMMUNITIES: ["mcp_israel"],
                }
            },
        )
    # Hard invariant: count clamped to the ceiling, never above.
    assert result.get(Keys.TOOL_CALL_COUNT) == 12
    # Every one of the 20 tool calls still got exactly one ToolMessage
    # (provider API contract: one response per tool_call_id).
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 20
    # The 8 over-budget calls are error messages; the first 12 executed.
    error_msgs = [m for m in tool_msgs if m.status == "error"]
    assert len(error_msgs) == 8
    assert all("budget" in m.content.lower() for m in error_msgs)
