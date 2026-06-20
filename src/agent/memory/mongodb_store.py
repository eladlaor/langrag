"""MongoDB-backed implementation of LangGraph's `BaseStore`.

Stores agent long-term memories in the `agent_memories` collection. The
namespace convention is `(user_id, memory_namespace)` where
`memory_namespace` is one of the `MemoryNamespace` `StrEnum` values
("semantic" / "episodic" / "procedural").

Embeddings are computed on `aput` (using whatever embedder the store was
constructed with) and stored as BSON Binary subtype 9, matching the
`rag_chunks` convention so Atlas Vector Search can serve them directly.

`asearch` delegates to `hybrid_search_memories` for $rankFusion hybrid
retrieval; namespace_prefix MUST start with `user_id` so multi-tenant
isolation is enforced at the aggregation layer, not in Python.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from bson.binary import Binary, BinaryVectorDtype
from langgraph.store.base import BaseStore, Item, NotProvided, SearchItem
from pymongo.asynchronous.collection import AsyncCollection

from constants import (
    AGENT_EPISODIC_MEMORY_TTL_DAYS,
    CURRENT_SCHEMA_VERSION_AGENT_MEMORY,
    SCHEMA_VERSION_FIELD,
)
from custom_types.db_schemas import MemoryNamespace
from custom_types.field_keys import AgentMemoryKeys as Keys

from .hybrid_memory_search import hybrid_search_memories

logger = logging.getLogger(__name__)

# Conventional keys inside the `value` dict passed to `aput`. The store
# unpacks these into top-level document fields so the index + retriever
# stay schema-aware.
VALUE_CONTENT = "content"
VALUE_IMPORTANCE = "importance"
VALUE_METADATA = "metadata"
VALUE_TTL_DAYS = "ttl_days"


def _allowed_namespaces() -> set[str]:
    return {str(n) for n in MemoryNamespace}


class MongoDBStore(BaseStore):
    """LangGraph `BaseStore` backed by the `agent_memories` collection.

    The store is async-only. Sync wrappers raise NotImplementedError so a
    misuse from non-async code surfaces loudly instead of falling back to
    a broken blocking path. The agent runtime is fully async, so the sync
    methods should never be exercised in practice.
    """

    def __init__(
        self,
        collection: AsyncCollection,
        embedder: Any,
        embedding_model: str,
    ) -> None:
        """
        Args:
            collection: AsyncCollection for `agent_memories`.
            embedder: Anything with an `embed_text(text) -> list[float]`
                method. The project's `EmbeddingProviderInterface` fits.
                A duck-typed object is also accepted so tests can pass a
                stub without standing up an OpenAI client.
            embedding_model: Identifier of the embedding model in use,
                stored alongside each memory for future migrations.
        """
        self._collection = collection
        self._embedder = embedder
        self._embedding_model = embedding_model

    # ------------------------------------------------------------------
    # Async API (the one we actually use)
    # ------------------------------------------------------------------

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: bool | list[str] | None = None,
        *,
        ttl: float | None | NotProvided = NotProvided(),
    ) -> None:
        """Insert or replace a memory under `(user_id, memory_namespace)`.

        `value` must carry at least `"content"`. Optional keys:
          - `"importance"` — float in [0, 1]; defaults to 0.5.
          - `"metadata"` — free-form dict.
          - `"ttl_days"` — set ONLY on episodic memories (sparse TTL).
            Defaults to AGENT_EPISODIC_MEMORY_TTL_DAYS for episodic and
            None for the other namespaces.

        The `index` and `ttl` arguments from BaseStore's signature are
        accepted for compatibility; we always embed the content (`index`)
        and source the TTL from `value["ttl_days"]` / the namespace
        default (`ttl` is ignored — sliding session TTL lives on the
        sessions collection, not on memories).
        """
        del index, ttl  # See docstring.

        user_id, ns = self._unpack_namespace(namespace)
        content = value.get(VALUE_CONTENT)
        if not content:
            raise ValueError(
                f"MongoDBStore.aput requires value['{VALUE_CONTENT}'] (got {value!r})"
            )

        importance = float(value.get(VALUE_IMPORTANCE, 0.5))
        metadata = dict(value.get(VALUE_METADATA, {}))

        # Episodic memories TTL by default; semantic/procedural persist.
        ttl_days = value.get(VALUE_TTL_DAYS)
        if ttl_days is None and ns == str(MemoryNamespace.EPISODIC):
            ttl_days = AGENT_EPISODIC_MEMORY_TTL_DAYS
        expires_at = None
        if ttl_days is not None:
            from datetime import timedelta  # local import: only on TTL path

            expires_at = datetime.now(UTC) + timedelta(days=int(ttl_days))

        embedding = self._embedder.embed_text(content)
        if embedding is None:
            raise RuntimeError(
                f"Embedder returned None for memory content (user_id={user_id}); "
                "refusing to write a memory without an embedding."
            )
        embedding_bin = Binary.from_vector(
            list(embedding),
            dtype=BinaryVectorDtype.FLOAT32,
        )

        now = datetime.now(UTC)
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_AGENT_MEMORY,
            Keys.MEMORY_ID: key,
            Keys.USER_ID: user_id,
            Keys.NAMESPACE: ns,
            Keys.CONTENT: content,
            Keys.EMBEDDING: embedding_bin,
            Keys.EMBEDDING_MODEL: self._embedding_model,
            Keys.IMPORTANCE: importance,
            Keys.METADATA: metadata,
            Keys.CREATED_AT: now,
            Keys.LAST_ACCESSED_AT: None,
            Keys.ACCESS_COUNT: 0,
            Keys.EXPIRES_AT: expires_at,
        }
        # Upsert by (user_id, memory_id) — `memory_id` is unique globally,
        # but the extra user_id clause prevents one tenant from replacing
        # another's row by guessing a key.
        await self._collection.replace_one(
            {Keys.MEMORY_ID: key, Keys.USER_ID: user_id},
            document,
            upsert=True,
        )
        logger.debug(f"aput memory: user_id={user_id} ns={ns} key={key}")

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> Item | None:
        """Fetch one memory by key, scoped to its owning user."""
        del refresh_ttl  # No per-key TTL beyond the namespace default.

        user_id, ns = self._unpack_namespace(namespace)
        row = await self._collection.find_one(
            {Keys.MEMORY_ID: key, Keys.USER_ID: user_id, Keys.NAMESPACE: ns},
            projection={Keys.EMBEDDING: 0},
        )
        if row is None:
            return None
        return _row_to_item(row, namespace)

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[SearchItem]:
        """Hybrid-search memories for a user.

        `namespace_prefix` MUST start with `user_id`; a second element is
        interpreted as a namespace restriction. Multi-tenant safety relies
        on this — calling without a user_id raises.

        When `query` is provided we run hybrid retrieval. When it is None
        we degrade to a plain Mongo query sorted by `created_at desc`
        (LangGraph's `BaseStore` callers sometimes use asearch as a "list
        recent" operation by passing only a filter).
        """
        del refresh_ttl, offset, filter  # Filter pass-through not used yet.

        if not namespace_prefix:
            raise ValueError(
                "MongoDBStore.asearch requires namespace_prefix starting with user_id"
            )
        user_id = namespace_prefix[0]
        ns: str | None = None
        if len(namespace_prefix) >= 2:
            ns = namespace_prefix[1]
            if ns not in _allowed_namespaces():
                raise ValueError(f"Unknown memory namespace: {ns!r}")

        if query:
            embedding = self._embedder.embed_text(query)
            if embedding is None:
                raise RuntimeError(
                    f"Embedder returned None for asearch query (user_id={user_id})"
                )
            rows = await hybrid_search_memories(
                self._collection,
                user_id=user_id,
                query_text=query,
                query_embedding=embedding,
                namespace=ns,
                top_k=limit,
            )
        else:
            q: dict[str, Any] = {Keys.USER_ID: user_id}
            if ns is not None:
                q[Keys.NAMESPACE] = ns
            cursor = (
                self._collection.find(q, projection={Keys.EMBEDDING: 0})
                .sort(Keys.CREATED_AT, -1)
                .limit(limit)
            )
            rows = await cursor.to_list()

        return [_row_to_search_item(r, user_id) for r in rows]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        """Delete one memory. User-scoped to prevent cross-tenant deletion."""
        user_id, ns = self._unpack_namespace(namespace)
        await self._collection.delete_one(
            {Keys.MEMORY_ID: key, Keys.USER_ID: user_id, Keys.NAMESPACE: ns},
        )

    async def alist_namespaces(
        self,
        *,
        prefix: tuple[str, ...] | None = None,
        suffix: tuple[str, ...] | None = None,
        max_depth: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        """List distinct `(user_id, namespace)` pairs.

        Prefix-filtering on `user_id` lets a caller enumerate "what
        namespaces does this user have memories in?" (the realistic
        production use case). Other filters are accepted for BaseStore
        compatibility but treated leniently.
        """
        del suffix, max_depth  # Tier 1 namespace shape is always 2 deep.

        match: dict[str, Any] = {}
        if prefix:
            match[Keys.USER_ID] = prefix[0]
            if len(prefix) >= 2:
                match[Keys.NAMESPACE] = prefix[1]

        pipeline: list[dict[str, Any]] = [
            {"$match": match} if match else {"$match": {}},
            {"$group": {"_id": {"user": f"${Keys.USER_ID}", "ns": f"${Keys.NAMESPACE}"}}},
            {"$skip": offset},
            {"$limit": limit},
        ]
        rows = (await self._collection.aggregate(pipeline)).to_list()
        return [(r["_id"]["user"], r["_id"]["ns"]) for r in rows]

    async def abatch(self, ops):  # pragma: no cover — not exercised at v1.13.0
        """Sequential fallback for batch ops; LangGraph's only requirement
        is that *some* implementation exists. We don't need batch
        throughput at v1.13.0 scale, so do them one at a time."""
        results = []
        for op in ops:
            results.append(await self._dispatch_op(op))
        return results

    async def _dispatch_op(self, op):  # pragma: no cover
        # `Op` is a sealed union in langgraph.store.base — when we want
        # real batch parallelism, route per Op subtype. For now keep this
        # explicitly minimal so an accidental caller fails fast.
        raise NotImplementedError(
            "MongoDBStore.abatch is a stub at v1.13.0; the agent runtime "
            "calls aput/aget/asearch/adelete directly."
        )

    # ------------------------------------------------------------------
    # Sync API (intentionally not implemented)
    # ------------------------------------------------------------------

    def batch(self, ops):
        raise NotImplementedError("MongoDBStore is async-only; use abatch.")

    # Helpers --------------------------------------------------------------

    @staticmethod
    def _unpack_namespace(namespace: tuple[str, ...]) -> tuple[str, str]:
        """Validate and return (user_id, namespace_str)."""
        if not namespace or len(namespace) < 2:
            raise ValueError(
                f"MongoDBStore namespace must be (user_id, memory_namespace); got {namespace!r}"
            )
        user_id, ns = namespace[0], namespace[1]
        if ns not in _allowed_namespaces():
            raise ValueError(f"Unknown memory namespace: {ns!r}")
        return user_id, ns


def _row_to_item(row: dict[str, Any], namespace: tuple[str, ...]) -> Item:
    return Item(
        value={
            VALUE_CONTENT: row.get(Keys.CONTENT, ""),
            VALUE_IMPORTANCE: row.get(Keys.IMPORTANCE, 0.5),
            VALUE_METADATA: row.get(Keys.METADATA, {}),
        },
        key=row.get(Keys.MEMORY_ID, ""),
        namespace=namespace,
        created_at=row.get(Keys.CREATED_AT),
        updated_at=row.get(Keys.CREATED_AT),
    )


def _row_to_search_item(row: dict[str, Any], user_id: str) -> SearchItem:
    ns_str = row.get(Keys.NAMESPACE, str(MemoryNamespace.SEMANTIC))
    return SearchItem(
        value={
            VALUE_CONTENT: row.get(Keys.CONTENT, ""),
            VALUE_IMPORTANCE: row.get(Keys.IMPORTANCE, 0.5),
            VALUE_METADATA: row.get(Keys.METADATA, {}),
        },
        key=row.get(Keys.MEMORY_ID, ""),
        namespace=(user_id, ns_str),
        created_at=row.get(Keys.CREATED_AT),
        updated_at=row.get(Keys.CREATED_AT),
        score=row.get("score"),
    )


def new_memory_id() -> str:
    """Return a fresh memory_id (uuid4 string).

    Lives on the module so the extractor + tools can share a single
    convention without each reinventing it.
    """
    return str(uuid.uuid4())
