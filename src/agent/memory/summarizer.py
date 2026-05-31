"""Conversation summarizer: compress old turns when context gets long.

Called from the agent graph when `len(state["messages"]) >
SUMMARIZE_THRESHOLD`. Replaces the oldest half of the message list with
one synthetic `SystemMessage` carrying the LLM-generated summary, leaves
the recent half verbatim, and emits `RemoveMessage` instructions so the
LangGraph state-reducer cleans the checkpoint.

Generic over the chat-model object: anything with an `ainvoke(messages)`
that returns an object with `.content` works (i.e., LangChain BaseChatModel
or a `FakeListChatModel` in tests).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)

logger = logging.getLogger(__name__)

# Default thresholds. Configurable per-deployment via settings (commit 7
# wires this through `settings.agent.summarize_threshold`).
DEFAULT_SUMMARIZE_THRESHOLD = 30
DEFAULT_KEEP_RECENT = 12

_SUMMARY_PROMPT_TEMPLATE = (
    "You are summarizing an in-progress agent conversation so the older "
    "turns can be dropped without losing context.\n\n"
    "Goals (in order):\n"
    "1. Preserve user-facing decisions (e.g., which community / language / "
    "format the user chose).\n"
    "2. Preserve open commitments (e.g., 'still waiting on run_id X').\n"
    "3. Preserve any constraints or preferences the user expressed.\n"
    "4. Drop chit-chat, tool-call mechanics, and anything already settled.\n\n"
    "Produce 4-8 short bullet points. Plain text, no markdown."
)


class _ChatModel(Protocol):
    """The shape we depend on; LangChain BaseChatModel satisfies it."""

    async def ainvoke(self, input: Any, /, **kwargs: Any) -> Any: ...


async def maybe_summarize(
    messages: list[BaseMessage],
    llm: _ChatModel,
    *,
    threshold: int = DEFAULT_SUMMARIZE_THRESHOLD,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> dict[str, Any] | None:
    """If `messages` exceeds `threshold`, summarize the oldest portion.

    Args:
        messages: Current message list from `AgentState`.
        llm: Anything implementing `.ainvoke([messages]) -> AIMessage`.
        threshold: Trigger summarization when len(messages) > threshold.
        keep_recent: How many recent messages to keep verbatim.

    Returns:
        None when no summarization is needed. Otherwise a dict with:
          - `summary_message`: a `SystemMessage` describing the dropped turns.
          - `remove_messages`: list of `RemoveMessage` ops to feed back into
            the state reducer so the checkpointed message list shrinks.
    """
    if len(messages) <= threshold:
        return None
    if keep_recent >= len(messages):
        return None

    to_summarize = messages[:-keep_recent]
    if not to_summarize:
        return None

    transcript = _render_for_summary(to_summarize)
    prompt: list[BaseMessage] = [
        SystemMessage(content=_SUMMARY_PROMPT_TEMPLATE),
        HumanMessage(content=transcript),
    ]
    response = await llm.ainvoke(prompt)
    summary_text = getattr(response, "content", str(response))

    summary_message = SystemMessage(
        content=f"Earlier conversation (summarized):\n{summary_text}"
    )
    remove_messages: list[RemoveMessage] = []
    for m in to_summarize:
        mid = getattr(m, "id", None)
        if mid:
            remove_messages.append(RemoveMessage(id=mid))

    logger.info(
        "summarized %d older messages, kept %d recent",
        len(to_summarize),
        keep_recent,
    )
    return {
        "summary_message": summary_message,
        "remove_messages": remove_messages,
    }


def _render_for_summary(messages: list[BaseMessage]) -> str:
    """Flatten a message list into a single text block for the summarizer."""
    lines: list[str] = []
    for m in messages:
        role = _role_of(m)
        content = _content_as_text(m)
        if not content:
            continue
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _role_of(m: BaseMessage) -> str:
    if isinstance(m, SystemMessage):
        return "system"
    if isinstance(m, HumanMessage):
        return "user"
    if isinstance(m, AIMessage):
        return "assistant"
    return getattr(m, "type", "other")


def _content_as_text(m: BaseMessage) -> str:
    c = getattr(m, "content", "")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        # LangChain content blocks: join text parts only.
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(p for p in parts if p).strip()
    return str(c)
