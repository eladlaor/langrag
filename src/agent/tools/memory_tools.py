"""Memory-management tools.

The agent can explicitly write or forget long-term memories. These tools
operate ONLY on the current user's memories — the `user_id` is read
from the `UserContext`, never accepted as a parameter, so the LLM
cannot tamper with another user's memory store.

The actual `MongoDBStore` is bound at registry-build time via a factory
parameter so tests can inject a stub. The agent runtime (commit 7) will
wire the production store.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from langchain_core.tools import BaseTool, tool

from agent.auth.user_context import current_user_context
from agent.memory.mongodb_store import VALUE_CONTENT, new_memory_id
from custom_types.db_schemas import MemoryNamespace

logger = logging.getLogger(__name__)


class _StoreLike(Protocol):
    async def aput(self, namespace, key, value, index=None, *, ttl=None) -> None: ...
    async def asearch(self, namespace_prefix, /, *, query=None, limit=10, **kwargs): ...
    async def adelete(self, namespace, key) -> None: ...


def build_memory_tools(store_factory: Callable[[], _StoreLike]) -> list[BaseTool]:
    """Construct the memory tools bound to `store_factory()`.

    `store_factory` is called lazily on each tool invocation so the store
    instance lives within the per-turn FastAPI dependency lifecycle.
    """

    @tool
    async def remember(
        content: str,
        namespace: str = "semantic",
        importance: float = 0.7,
    ) -> dict[str, Any]:
        """Explicitly persist a long-term memory for the current user.

        Use this when the user says "remember that ...", or when the agent
        wants to capture a durable preference that the implicit extractor
        might miss.

        Args:
            content: One short sentence stating the memory in third person
                about the user.
            namespace: One of "semantic" (durable facts / preferences),
                "episodic" (timestamped events; expire after 30 days),
                or "procedural" (learned patterns / defaults).
            importance: Float in [0, 1]; informs future retrieval ranking.

        Returns:
            Dict with the new `memory_id` and the resolved namespace.
        """
        ctx = current_user_context()
        try:
            ns = MemoryNamespace(namespace.lower())
        except ValueError as e:
            raise ValueError(
                f"Unknown memory namespace: {namespace!r}. "
                f"Valid: {[str(n) for n in MemoryNamespace]}"
            ) from e

        store = store_factory()
        memory_id = new_memory_id()
        await store.aput(
            (ctx.user_id, str(ns)),
            memory_id,
            {VALUE_CONTENT: content, "importance": float(importance)},
        )
        logger.info(
            "remember: user_id=%s ns=%s memory_id=%s",
            ctx.user_id,
            ns,
            memory_id,
        )
        return {"memory_id": memory_id, "namespace": str(ns)}

    @tool
    async def forget(memory_id: str) -> dict[str, Any]:
        """Delete one of the current user's long-term memories.

        Deletion is user-scoped: the `MongoDBStore.adelete` query filters
        on (user_id, memory_id), so a memory belonging to another user
        cannot be removed via this tool even if its id is guessed.

        Args:
            memory_id: The memory_id returned from `remember` or surfaced
                in a `list_memories` listing.

        Returns:
            Dict with `deleted: true` (always — the operation is
            idempotent at this layer; the underlying delete is a no-op
            when no matching row exists).
        """
        ctx = current_user_context()
        store = store_factory()
        # We don't know the namespace from just memory_id; try all three.
        # adelete is cheap (one Mongo round-trip with a unique index).
        for ns in MemoryNamespace:
            await store.adelete((ctx.user_id, str(ns)), memory_id)
        logger.info("forget: user_id=%s memory_id=%s", ctx.user_id, memory_id)
        return {"deleted": True, "memory_id": memory_id}

    @tool
    async def list_memories(
        namespace: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List the current user's most recent long-term memories.

        Args:
            namespace: Optional filter — one of "semantic", "episodic",
                "procedural". If omitted, returns memories across all
                three namespaces (most recent first).
            limit: Max items to return.

        Returns:
            List of memory dicts with `memory_id`, `namespace`, `content`,
            and `importance`. Embeddings are NOT included.
        """
        ctx = current_user_context()
        if namespace is not None:
            try:
                ns = MemoryNamespace(namespace.lower())
            except ValueError as e:
                raise ValueError(
                    f"Unknown memory namespace: {namespace!r}. "
                    f"Valid: {[str(n) for n in MemoryNamespace]}"
                ) from e
            prefix: tuple[str, ...] = (ctx.user_id, str(ns))
        else:
            prefix = (ctx.user_id,)

        store = store_factory()
        items = await store.asearch(prefix, query=None, limit=limit)
        return [
            {
                "memory_id": item.key,
                "namespace": item.namespace[1] if len(item.namespace) > 1 else "",
                "content": (item.value or {}).get(VALUE_CONTENT, ""),
                "importance": (item.value or {}).get("importance", 0.5),
            }
            for item in items
        ]

    return [remember, forget, list_memories]
