"""Tests for `maybe_summarize`.

Pure-function tests against a fake LLM — no MongoDB needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage

from agent.memory.summarizer import (
    DEFAULT_KEEP_RECENT,
    DEFAULT_SUMMARIZE_THRESHOLD,
    maybe_summarize,
)

pytestmark = [pytest.mark.asyncio]


@dataclass
class _FakeLLMResponse:
    content: str


class FakeLLM:
    def __init__(self, response: str = "- decision A\n- decision B") -> None:
        self.response = response
        self.calls: list[Any] = []

    async def ainvoke(self, input, /, **kwargs):  # noqa: A002
        self.calls.append(input)
        return _FakeLLMResponse(content=self.response)


def _conversation(n: int) -> list:
    """Build n alternating user/assistant messages with stable IDs."""
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append(HumanMessage(content=f"user {i}", id=f"u-{i}"))
        else:
            msgs.append(AIMessage(content=f"assistant {i}", id=f"a-{i}"))
    return msgs


# ---------------------------------------------------------------------------


async def test_under_threshold_is_noop():
    msgs = _conversation(10)
    llm = FakeLLM()
    out = await maybe_summarize(msgs, llm)
    assert out is None
    assert llm.calls == []


async def test_over_threshold_triggers_summary():
    msgs = _conversation(DEFAULT_SUMMARIZE_THRESHOLD + 5)
    llm = FakeLLM(response="- preserved decision X")
    out = await maybe_summarize(msgs, llm)
    assert out is not None
    assert isinstance(out["summary_message"], SystemMessage)
    assert "preserved decision X" in out["summary_message"].content
    # The number of RemoveMessages equals the number summarized.
    summarized_count = len(msgs) - DEFAULT_KEEP_RECENT
    assert len(out["remove_messages"]) == summarized_count
    assert all(isinstance(r, RemoveMessage) for r in out["remove_messages"])


async def test_keep_recent_messages_intact():
    msgs = _conversation(DEFAULT_SUMMARIZE_THRESHOLD + 5)
    out = await maybe_summarize(msgs, FakeLLM())
    assert out is not None
    # The IDs of the kept-recent half must NOT appear in remove_messages.
    summarized_ids = {r.id for r in out["remove_messages"]}
    recent_ids = {m.id for m in msgs[-DEFAULT_KEEP_RECENT:]}
    assert summarized_ids.isdisjoint(recent_ids)


async def test_custom_threshold():
    msgs = _conversation(20)
    out = await maybe_summarize(msgs, FakeLLM(), threshold=10, keep_recent=4)
    assert out is not None
    assert len(out["remove_messages"]) == 20 - 4


async def test_keep_recent_larger_than_messages_is_noop():
    msgs = _conversation(DEFAULT_SUMMARIZE_THRESHOLD + 5)
    out = await maybe_summarize(msgs, FakeLLM(), keep_recent=1000)
    assert out is None


async def test_messages_without_ids_are_not_removed():
    """If a message has no `id`, we can't safely emit a RemoveMessage for it.
    The summarizer must skip those rather than crashing."""
    msgs = _conversation(DEFAULT_SUMMARIZE_THRESHOLD + 5)
    # Strip ids from the first few messages.
    for m in msgs[:5]:
        m.id = None
    out = await maybe_summarize(msgs, FakeLLM())
    assert out is not None
    # The RemoveMessage list won't include the id-less ones.
    removed_ids = {r.id for r in out["remove_messages"]}
    for m in msgs[:5]:
        assert m.id not in removed_ids
