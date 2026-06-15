"""The agent `StateGraph`.

Topology (per knowledge/plans/AGENTIC_CHATBOT_LAYER.md §D):

    load_memory  ──►  agent  ──conditional──►  tools  ──►  check_budget
                       ▲                                        │
                       └────── (continue, while tool calls) ────┘
                       │
                       └── (no tool calls) ──►  extract_memory  ──►  END

The `agent` node binds the configured tools to the chat model and lets
the LLM decide whether to call more tools or stop. The `tools` node
catches `CommunityPermissionError` from any tool and turns it into a
`ToolMessage(status="error")` so the LLM sees the denial in its next
iteration instead of crashing the turn.

`check_budget` is a placeholder in v1.13.0 (it caps `tool_call_count`
but doesn't yet enforce token quotas — commit 11 adds full
`users.daily_usage` enforcement).
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any
from collections.abc import Callable

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import RetryPolicy

from langgraph.errors import GraphInterrupt

from agent.auth.acl import CommunityPermissionError
from observability.metrics import agent_metrics as _agent_metrics
from agent.memory.extractor import extract_and_persist_memories
from agent.memory.retriever import load_relevant_memories
from agent.memory.summarizer import maybe_summarize
from agent.state import AgentState
from agent.tools.newsletter_tools import KickoffFn
from agent.tools.registry import build_tools_for_session
from config import get_settings
from graphs.state_keys import AgentStateKeys as Keys

logger = logging.getLogger(__name__)


# Node names — exposed so tests can assert on the routing. StrEnum so node
# identifiers are type-checked at the call sites (a typo'd member is an
# AttributeError, not a silently-misrouted string) while still comparing and
# hashing equal to their string values for LangGraph edges/mappings.
class NodeNames(StrEnum):
    LOAD_MEMORY = "load_memory"
    AGENT = "agent"
    TOOLS = "tools"
    CHECK_BUDGET = "check_budget"
    SUMMARIZE = "summarize"
    EXTRACT_MEMORY = "extract_memory"


SYSTEM_PROMPT = (
    "You are LangRAG's agent for community admins. You can:\n"
    "  - generate WhatsApp community newsletters (kick off + monitor + fetch)\n"
    "  - manage recurring newsletter schedules\n"
    "  - query the LangTalks podcast + past-newsletter RAG index\n"
    "  - inspect and edit the user's long-term memories\n"
    "\n"
    "Rules:\n"
    "  - Only act on communities the user owns. If the user requests a "
    "community you can't act on, the tool will return a permission error — "
    "surface it briefly and offer alternatives from list_my_communities.\n"
    "  - Reuse what's in `retrieved_memories` (user preferences, defaults) "
    "instead of re-asking. If the user says 'do it again', read the "
    "memories and act, don't ask.\n"
    "  - When kicking off a newsletter, return the run_id and a one-line "
    "confirmation. Tell the user how to fetch the result later.\n"
)


# Type alias for the LLM-with-tools-bound callable injected at compile time.
# We accept anything async with .ainvoke that returns an AIMessage-shaped
# object so tests can drive the graph with FakeListChatModel without
# building a real Anthropic client.
LLMWithTools = Any


# Factory for the agent LLM. Production wires a real ChatAnthropic via the
# AgentSettings.agent_model; tests inject a fake.
AgentLLMFactory = Callable[[list[BaseTool]], LLMWithTools]


# Factory for the memory LLM (extractor + summarizer). Same shape.
MemoryLLMFactory = Callable[[], Any]


async def build_agent_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    store: BaseStore,
    kickoff_fn: KickoffFn,
    agent_llm_factory: AgentLLMFactory,
    memory_llm_factory: MemoryLLMFactory,
):
    """Compile the agent `StateGraph`.

    All heavy collaborators (the chat-model client, the checkpointer, the
    store, the newsletter kickoff) are injected so tests can swap them.
    """
    settings = get_settings().agent

    # Build the tool list once per compiled graph. The tools' user-context
    # is read lazily from the contextvar at call time, so this list is
    # reusable across sessions even though the principal differs per turn.
    tools = build_tools_for_session(store=store, kickoff_fn=kickoff_fn)
    agent_llm = agent_llm_factory(tools)

    async def load_memory_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
        """Read user_id/communities from config and load relevant memories.

        LangGraph 1.x routes the configurable dict via a contextvar
        (`langgraph.config.get_config()`) when the node is a closure
        rather than a module-level function — the function-signature
        inspector that decides whether to pass `config=` doesn't see
        through closures cleanly, so the parameter arrives as `{}`. The
        helper reads the same data from the contextvar and is the
        documented path forward.
        """
        from langgraph.config import get_config as _lg_get_config

        try:
            cfg = _lg_get_config() or {}
        except Exception:
            cfg = config or {}
        configurable = cfg.get("configurable", {}) or {}
        user_id = configurable.get(Keys.USER_ID) or state.get(Keys.USER_ID, "")
        communities = (
            configurable.get(Keys.COMMUNITIES)
            or state.get(Keys.COMMUNITIES, [])
            or []
        )
        session_id = configurable.get("thread_id") or state.get(Keys.SESSION_ID, "")

        # Use the latest human message as the memory query.
        last_user = _latest_user_text(state.get(Keys.MESSAGES, []))
        memories: list[dict[str, Any]] = []
        if user_id and last_user:
            try:
                memories = await load_relevant_memories(
                    store,  # type: ignore[arg-type]
                    user_id,
                    last_user,
                    top_k=settings.memory_top_k,
                )
            except Exception as e:
                # Memory loading is best-effort; a search failure must not
                # block the turn. The agent simply runs without recall.
                logger.warning("load_relevant_memories failed: %s", e)

        return {
            Keys.USER_ID: user_id,
            Keys.COMMUNITIES: list(communities),
            Keys.SESSION_ID: session_id,
            Keys.RETRIEVED_MEMORIES: memories,
            Keys.TOOL_CALL_COUNT: state.get(Keys.TOOL_CALL_COUNT, 0),
            Keys.ARTIFACT_EVENTS: state.get(Keys.ARTIFACT_EVENTS, []),
        }

    async def agent_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
        """Invoke the LLM (with tools bound) and append its reply."""
        messages = state.get(Keys.MESSAGES, [])
        system = _build_system_message(state.get(Keys.RETRIEVED_MEMORIES, []))
        # Inject the system message inline rather than persisting it to
        # state — every turn rebuilds it from fresh retrieved_memories.
        llm_input: list[BaseMessage] = [system, *messages]
        ai_msg = await agent_llm.ainvoke(llm_input)
        return {Keys.MESSAGES: [ai_msg]}

    async def tools_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
        """Execute any tool calls in the latest AI message.

        ACL denials (CommunityPermissionError) are converted to
        ToolMessage(status='error') so the LLM sees the refusal in its
        next iteration. Other exceptions also surface as error tool
        messages — the graph never crashes mid-turn on a tool failure.
        """
        messages = state.get(Keys.MESSAGES, [])
        last = messages[-1] if messages else None
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return {}

        tools_by_name = {t.name: t for t in tools}
        tool_messages: list[ToolMessage] = []

        # Hard per-turn cap: enforce the ceiling BEFORE executing, not just after.
        # The LLM may emit several tool calls in one step; without this, a batch
        # could blow past max_tool_calls_per_turn by up to (batch_size - 1) before
        # route_after_budget ever runs. We execute only as many calls as the
        # remaining budget allows and short-circuit the rest as error
        # ToolMessages. Every tool_call_id still gets exactly one ToolMessage,
        # which the provider API requires.
        already_used = state.get(Keys.TOOL_CALL_COUNT, 0)
        budget_remaining = max(0, settings.max_tool_calls_per_turn - already_used)

        for index, call in enumerate(tool_calls):
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")

            # Over-budget: do not execute. Emit an error ToolMessage so the LLM
            # learns the call was refused and stops requesting more.
            if index >= budget_remaining:
                _agent_metrics.record_tool_call(name, "error")
                _agent_metrics.record_budget_halt("max_tool_calls_per_turn")
                tool_messages.append(
                    ToolMessage(
                        content=(f"Tool call budget exhausted: the per-turn limit of " f"{settings.max_tool_calls_per_turn} tool calls has been reached. " f"This call was not executed."),
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                continue

            tool = tools_by_name.get(name)
            if tool is None:
                tool_messages.append(
                    ToolMessage(
                        content=f"Unknown tool: {name!r}",
                        tool_call_id=call_id,
                        status="error",
                    )
                )
                continue
            try:
                # Tools read user_context from the ambient contextvar — the
                # route handler set it via `with user_context(ctx):` around
                # `graph.ainvoke`, so it's present here.
                result = await tool.ainvoke(args or {})
            except GraphInterrupt:
                # HITL gate: a destructive tool called `interrupt()`.
                # Re-raise so LangGraph suspends the graph at this
                # checkpoint. The route handler emits an
                # `interrupt_required` SSE event; the user resumes via
                # /agent/chat/resume with Command(resume=<decision>).
                raise
            except CommunityPermissionError as e:
                _agent_metrics.record_tool_call(name, "error")
                _agent_metrics.record_acl_denial(name, e.community_key)
                tool_messages.append(
                    ToolMessage(
                        content=(
                            f"Permission denied: you do not own community "
                            f"{e.community_key!r}."
                        ),
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                continue
            except ValueError as e:
                _agent_metrics.record_tool_call(name, "error")
                tool_messages.append(
                    ToolMessage(
                        content=str(e),
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                continue
            except Exception as e:  # pragma: no cover — defensive
                _agent_metrics.record_tool_call(name, "error")
                logger.exception("Tool %s raised", name)
                tool_messages.append(
                    ToolMessage(
                        content=f"Tool {name!r} raised: {e}",
                        tool_call_id=call_id,
                        status="error",
                        name=name,
                    )
                )
                continue
            _agent_metrics.record_tool_call(name, "success")
            tool_messages.append(
                ToolMessage(
                    content=_serialize_tool_result(result),
                    tool_call_id=call_id,
                    name=name,
                )
            )

        # Count only calls that passed the budget gate (i.e. were actually
        # attempted). Over-budget short-circuited calls do not consume budget —
        # they were never executed — so the count can never exceed the ceiling.
        executed_count = min(len(tool_calls), budget_remaining)
        return {
            Keys.MESSAGES: tool_messages,
            Keys.TOOL_CALL_COUNT: already_used + executed_count,
        }

    async def check_budget_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
        """Stop the loop if the per-turn tool-call ceiling is hit.

        Token-quota enforcement against `users.daily_usage` ships in
        commit 11. For v1.13.0 we cap `tool_call_count` only.
        """
        return {}  # No mutations; routing happens in route_after_budget.

    async def summarize_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
        memory_llm = memory_llm_factory()
        outcome = await maybe_summarize(
            state.get(Keys.MESSAGES, []),
            memory_llm,
            threshold=settings.summarize_threshold,
            keep_recent=settings.summarize_keep_recent,
        )
        if outcome is None:
            return {}
        msgs: list[BaseMessage] = list(outcome["remove_messages"])
        msgs.append(outcome["summary_message"])
        return {Keys.MESSAGES: msgs}

    async def extract_memory_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
        """Run the memory extractor over the just-finished exchange."""
        user_id = state.get(Keys.USER_ID, "")
        if not user_id:
            return {}
        # Use the trailing exchange (last 4 messages) as the extractor input.
        messages = state.get(Keys.MESSAGES, [])
        exchange = messages[-4:] if len(messages) >= 4 else list(messages)
        if not exchange:
            return {}
        memory_llm = memory_llm_factory()
        try:
            await extract_and_persist_memories(
                user_id=user_id,
                recent_exchange=exchange,
                llm=memory_llm,
                store=store,  # type: ignore[arg-type]
                importance_threshold=settings.importance_threshold,
            )
        except Exception as e:
            # Memory extraction is best-effort; never fail a turn on it.
            logger.warning("extract_and_persist_memories failed: %s", e)
        return {}

    # Routing -----------------------------------------------------------

    def route_after_agent(state: AgentState) -> str:
        last = (state.get(Keys.MESSAGES) or [None])[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if tool_calls:
            return NodeNames.TOOLS
        # No tool calls → maybe summarize, then end.
        if len(state.get(Keys.MESSAGES, [])) > settings.summarize_threshold:
            return NodeNames.SUMMARIZE
        return NodeNames.EXTRACT_MEMORY

    def route_after_budget(state: AgentState) -> str:
        if state.get(Keys.TOOL_CALL_COUNT, 0) >= settings.max_tool_calls_per_turn:
            logger.info(
                "Halting agent loop: tool_call_count=%d >= max=%d",
                state.get(Keys.TOOL_CALL_COUNT, 0),
                settings.max_tool_calls_per_turn,
            )
            _agent_metrics.record_budget_halt("max_tool_calls_per_turn")
            return NodeNames.EXTRACT_MEMORY
        return NodeNames.AGENT

    # Wire up ----------------------------------------------------------

    g: StateGraph = StateGraph(AgentState)
    g.add_node(NodeNames.LOAD_MEMORY, load_memory_node)
    g.add_node(NodeNames.AGENT, agent_node, retry_policy=RetryPolicy(max_attempts=2))
    g.add_node(NodeNames.TOOLS, tools_node)
    g.add_node(NodeNames.CHECK_BUDGET, check_budget_node)
    g.add_node(NodeNames.SUMMARIZE, summarize_node)
    g.add_node(NodeNames.EXTRACT_MEMORY, extract_memory_node)

    g.set_entry_point(NodeNames.LOAD_MEMORY)
    g.add_edge(NodeNames.LOAD_MEMORY, NodeNames.AGENT)
    g.add_conditional_edges(
        NodeNames.AGENT,
        route_after_agent,
        {
            NodeNames.TOOLS: NodeNames.TOOLS,
            NodeNames.SUMMARIZE: NodeNames.SUMMARIZE,
            NodeNames.EXTRACT_MEMORY: NodeNames.EXTRACT_MEMORY,
        },
    )
    g.add_edge(NodeNames.TOOLS, NodeNames.CHECK_BUDGET)
    g.add_conditional_edges(
        NodeNames.CHECK_BUDGET,
        route_after_budget,
        {
            NodeNames.AGENT: NodeNames.AGENT,
            NodeNames.EXTRACT_MEMORY: NodeNames.EXTRACT_MEMORY,
        },
    )
    # End-of-turn compaction: the agent has already produced its final answer (no
    # tool calls) before routing here, so summarize → extract_memory → END. Routing
    # back to AGENT would re-answer on a compacted history and, worse, could oscillate
    # SUMMARIZE↔AGENT without ever reaching EXTRACT_MEMORY (memory loss on long turns).
    g.add_edge(NodeNames.SUMMARIZE, NodeNames.EXTRACT_MEMORY)
    g.add_edge(NodeNames.EXTRACT_MEMORY, END)

    return g.compile(checkpointer=checkpointer, store=store)


# Helpers --------------------------------------------------------------


def _latest_user_text(messages: list[BaseMessage]) -> str:
    """Return the content of the most recent HumanMessage, or empty."""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            content = m.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return str(block.get("text", ""))
    return ""


def _build_system_message(memories: list[dict[str, Any]]) -> SystemMessage:
    """Compose the system prompt with the retrieved memories embedded."""
    if not memories:
        return SystemMessage(content=SYSTEM_PROMPT)
    lines = ["Known about the user (long-term memory, most relevant first):"]
    for m in memories[:8]:
        ns = m.get("_namespace", "")
        content = m.get("content", "")
        lines.append(f"  - [{ns}] {content}")
    return SystemMessage(content=SYSTEM_PROMPT + "\n\n" + "\n".join(lines))


def _serialize_tool_result(result: Any) -> str:
    """Tool results are surfaced to the LLM as a ToolMessage string."""
    if isinstance(result, str):
        return result
    try:
        import json

        return json.dumps(result, default=str, ensure_ascii=False)
    except Exception:
        return str(result)
