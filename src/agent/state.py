"""TypedDict definitions for the agent graph state."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State carried through the agent graph for one turn.

    LangGraph's `total=False` makes every key optional; the `load_memory`
    entry node populates the principal-bound fields from `configurable`,
    and `add_messages` is the standard message-list reducer.
    """

    # Conversation
    messages: Annotated[list[BaseMessage], add_messages]

    # Principal (read from `configurable`, never from the LLM)
    user_id: str
    communities: list[str]

    # Long-term memory injected into the system prompt at turn start
    retrieved_memories: list[dict[str, Any]]

    # Per-turn budget tracking
    tool_call_count: int
    chat_input_tokens: int
    chat_output_tokens: int
    memory_tokens: int
    quota_remaining: dict[str, int]

    # Control flow
    pending_interrupt: dict[str, Any] | None
    artifact_events: list[dict[str, Any]]

    # Observability
    session_id: str
    langfuse_trace_id: str | None
