"""LLM-driven memory extractor.

Runs at the end of an agent turn. The extractor asks the configured LLM
to inspect the latest user + assistant exchange and decide which facts /
events / preferences are worth persisting to long-term memory. Items
above the configured importance threshold are written through
`MongoDBStore.aput`.

The extractor is generic over the chat-model object: anything with an
`ainvoke(messages)` returning an `AIMessage`-shaped object works, so
tests can drive it with `FakeListChatModel`.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from custom_types.db_schemas import MemoryNamespace

from .mongodb_store import MongoDBStore, new_memory_id

logger = logging.getLogger(__name__)

# Memories below this importance score are dropped. The agent doesn't
# need to remember "user said hello" — only signal-bearing facts.
DEFAULT_IMPORTANCE_THRESHOLD = 0.4

_EXTRACTOR_PROMPT_TEMPLATE = (
    "You are the agent's memory extractor. Inspect the latest exchange and "
    "decide which durable facts about the user, their communities, or their "
    "preferences are worth remembering across future sessions.\n\n"
    "Output STRICT JSON: an array of objects with these fields:\n"
    "  - namespace: one of 'semantic' (durable facts about the user / their "
    "communities / their preferences), 'episodic' (timestamped events "
    "worth recalling later, e.g. 'on 2026-05-28 user rejected the first "
    "draft of the MCP Israel newsletter'), or 'procedural' (learned "
    "patterns / defaults, e.g. 'always use 5 discussions, not 10').\n"
    "  - content: one short sentence stating the memory, in third person "
    "about the user.\n"
    "  - importance: float in [0, 1]. Use 0 for trivial chit-chat, 0.5 for "
    "useful context, 1.0 for must-remember preferences.\n"
    "  - ttl_days (optional): integer; set only for episodic memories that "
    "should expire faster than the default.\n\n"
    "Skip greetings, tool-call mechanics, and anything already settled in a "
    "previous memory. Return [] when nothing is worth saving. Output ONLY "
    "the JSON array — no markdown fences, no prose."
)


class _ChatModel(Protocol):
    async def ainvoke(self, input: Any, /, **kwargs: Any) -> Any: ...


async def extract_and_persist_memories(
    user_id: str,
    recent_exchange: list[BaseMessage],
    llm: _ChatModel,
    store: MongoDBStore,
    *,
    importance_threshold: float = DEFAULT_IMPORTANCE_THRESHOLD,
    community_context: str | None = None,
) -> list[str]:
    """Extract memories from `recent_exchange` and persist the keepers.

    Args:
        user_id: Owning user. Empty user_id is rejected (no orphan memories).
        recent_exchange: The just-completed turn's messages (typically the
            last user message + the assistant's reply + any tool messages).
        llm: A chat model with `.ainvoke(messages)`. The agent runtime
            wires Opus 4.7 here per plan §P.
        store: Configured `MongoDBStore`.
        importance_threshold: Items below this score are dropped silently.
        community_context: Optional community key, stamped on each memory's
            metadata so cross-community retrieval can later filter.

    Returns:
        List of persisted `memory_id`s.
    """
    if not user_id:
        raise ValueError("extract_and_persist_memories requires a non-empty user_id")
    if not recent_exchange:
        return []

    transcript = _render_exchange(recent_exchange)
    prompt: list[BaseMessage] = [
        SystemMessage(content=_EXTRACTOR_PROMPT_TEMPLATE),
        HumanMessage(content=transcript),
    ]
    response = await llm.ainvoke(prompt)
    raw = getattr(response, "content", str(response))
    items = _parse_extractor_response(raw)
    if not items:
        return []

    persisted: list[str] = []
    for item in items:
        try:
            importance = float(item.get("importance", 0.0))
        except (TypeError, ValueError):
            continue
        if importance < importance_threshold:
            continue

        content = str(item.get("content", "")).strip()
        if not content:
            continue

        ns_raw = str(item.get("namespace", "")).lower()
        try:
            namespace = MemoryNamespace(ns_raw)
        except ValueError:
            logger.warning(
                "extractor emitted unknown namespace=%r; skipping content=%r",
                ns_raw,
                content[:80],
            )
            continue

        value: dict[str, Any] = {
            "content": content,
            "importance": importance,
            "metadata": {
                "extracted_at_user_id": user_id,
                **({"community_key": community_context} if community_context else {}),
            },
        }
        ttl_days = item.get("ttl_days")
        if ttl_days is not None and namespace == MemoryNamespace.EPISODIC:
            value["ttl_days"] = int(ttl_days)

        memory_id = new_memory_id()
        await store.aput((user_id, str(namespace)), memory_id, value)
        persisted.append(memory_id)
        try:
            from observability.metrics import agent_metrics as _am

            _am.record_memory_write(str(namespace))
        except Exception:
            pass  # best-effort observability

    logger.info(
        "extracted memories: user_id=%s candidates=%d persisted=%d (threshold=%.2f)",
        user_id,
        len(items),
        len(persisted),
        importance_threshold,
    )
    return persisted


def _render_exchange(messages: list[BaseMessage]) -> str:
    lines: list[str] = []
    for m in messages:
        role = getattr(m, "type", "other")
        content = getattr(m, "content", "")
        if isinstance(content, list):
            # Flatten content blocks to text parts only.
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            content = " ".join(p for p in parts if p)
        text = str(content).strip()
        if not text:
            continue
        lines.append(f"[{role}] {text}")
    return "\n".join(lines)


_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_extractor_response(raw: str) -> list[dict[str, Any]]:
    """Robustly parse the extractor's response into a list of dicts.

    The system prompt asks for raw JSON, but LLMs occasionally wrap the
    array in ```json fences. Try a direct json.loads first, then fall
    back to the first `[...]` substring.
    """
    if not raw:
        return []
    text = raw.strip()
    # Strip common markdown fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(text)
        if not match:
            logger.warning("extractor response did not contain a JSON array: %r", text[:200])
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.warning("extractor response failed JSON parse after fence-strip: %s", e)
            return []
    if not isinstance(parsed, list):
        logger.warning("extractor response was not a JSON array: %s", type(parsed).__name__)
        return []
    return [p for p in parsed if isinstance(p, dict)]
