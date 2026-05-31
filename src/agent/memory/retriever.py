"""Load relevant memories at the start of an agent turn.

The retriever runs the user's current message (or a synthesized query) as
a hybrid search across all three memory namespaces, dedupes the union,
and returns the top-K by fused score. Results are rendered into the
system prompt by the agent node (commit 7).
"""

from __future__ import annotations

import logging
from typing import Any

from custom_types.db_schemas import MemoryNamespace

from .mongodb_store import MongoDBStore

logger = logging.getLogger(__name__)

# How many memories to load per turn by default. Conservative because each
# memory consumes ~100 prompt tokens (content + metadata) once rendered.
DEFAULT_TOP_K = 6


async def load_relevant_memories(
    store: MongoDBStore,
    user_id: str,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    namespaces: list[MemoryNamespace] | None = None,
) -> list[dict[str, Any]]:
    """Return the top-K most relevant memories for `user_id` given `query`.

    Args:
        store: The configured `MongoDBStore` instance.
        user_id: The owning user. Required — empty user_id is rejected.
        query: Natural-language query (typically the user's latest turn).
        top_k: Max memories returned across all namespaces combined.
        namespaces: Restrict to a subset of namespaces. None = all three.

    Returns:
        List of memory `value` dicts (with `_score` and `_namespace`
        injected for the caller's convenience), sorted by score desc.
    """
    if not user_id:
        raise ValueError("load_relevant_memories requires a non-empty user_id")
    if not query:
        return []

    target_namespaces: list[MemoryNamespace] = list(namespaces) if namespaces else list(MemoryNamespace)

    collected: list[tuple[float, dict[str, Any]]] = []
    seen_keys: set[str] = set()
    # Search each namespace individually so the per-namespace candidate
    # pool isn't dominated by one tier (e.g., a chatty episodic history
    # shouldn't crowd out a critical semantic preference).
    per_ns_k = max(1, top_k)
    for ns in target_namespaces:
        items = await store.asearch(
            (user_id, str(ns)),
            query=query,
            limit=per_ns_k,
        )
        for item in items:
            if item.key in seen_keys:
                continue
            seen_keys.add(item.key)
            score = float(item.score) if item.score is not None else 0.0
            payload = dict(item.value)
            payload["_score"] = score
            payload["_namespace"] = str(ns)
            payload["_memory_id"] = item.key
            collected.append((score, payload))

    collected.sort(key=lambda t: t[0], reverse=True)
    top = [p for _, p in collected[:top_k]]
    logger.info(
        "load_relevant_memories: user_id=%s query_len=%d candidates=%d returned=%d",
        user_id,
        len(query),
        len(collected),
        len(top),
    )
    return top
