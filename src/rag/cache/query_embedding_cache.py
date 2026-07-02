"""
In-process query-embedding cache (COST-4a).

Each embedded query is one owner-paid OpenAI text-embedding-3-large call. A
repeated query (common under agent retry loops and adversarial replay) re-pays
for an identical vector. This bounded, TTL'd LRU cache maps a NORMALIZED query
string to its embedding so a repeat within the TTL reuses the cached vector,
cutting both cost and replay abuse.

Bounded (LRU eviction at max_size) and TTL'd (stale entries dropped on read) so
memory stays bounded on the 4GB box. The clock is injectable for deterministic
TTL tests. Single-process, single-event-loop: get/put are synchronous and atomic
w.r.t. the loop, so no lock is needed (per-process by construction, like the
concurrency guard and rate limiter).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable

logger = logging.getLogger(__name__)


def normalize_query(query: str) -> str:
    """Canonicalize a query for cache keying: lowercase, collapse whitespace.

    Case- and spacing-insensitive so trivially-different spellings of the same
    query share one cache entry (and one embedding).
    """
    return " ".join(query.lower().split())


class QueryEmbeddingCache:
    """A bounded, TTL'd LRU cache of query-text -> embedding vector."""

    def __init__(
        self,
        *,
        max_size: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._clock = clock
        # key -> (inserted_at, vector)
        self._store: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self._ttl > 0 and self._max_size > 0

    def get(self, query: str) -> list[float] | None:
        """Return the cached embedding for ``query`` if fresh, else None."""
        if not self.enabled:
            return None
        key = normalize_query(query)
        entry = self._store.get(key)
        if entry is None:
            return None
        inserted_at, vector = entry
        if self._clock() - inserted_at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)  # mark as most-recently-used
        return vector

    def put(self, query: str, vector: list[float]) -> None:
        """Cache ``vector`` for ``query``, evicting the LRU entry if at capacity."""
        if not self.enabled:
            return
        key = normalize_query(query)
        self._store[key] = (self._clock(), vector)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def _reset_for_tests(self) -> None:
        self._store.clear()
