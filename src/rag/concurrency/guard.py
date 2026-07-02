"""
Process-wide hard concurrency admission control for the RAG surface.

Single-responsibility module owning ONE process-wide counter capped at
``get_settings().rag.max_concurrent_requests`` (default 50). It enforces a
NON-BLOCKING acquire contract: when the cap is reached, an acquire fails
immediately (returns False / raises ``RagCapacityExceeded``) instead of queuing.
This is admission control, not throttling — the caller rejects the (N+1)th
request with HTTP 503 + Retry-After rather than waiting for a slot.

Design notes:
  - Implemented as a manual integer counter guarded by an ``asyncio.Lock`` rather
    than ``asyncio.wait_for(sem.acquire(), timeout=0)``, which is racy across
    Python versions (a timeout=0 can still schedule a loop cycle and, under
    contention, is not reliably non-blocking). The counter+lock gives exact,
    deterministic non-blocking semantics with an identical public API.
  - The counter/lock are built LAZILY on first use (never at import time) so they
    bind to the running event loop and so tests can reset them via
    ``_reset_for_tests()``. An import-time asyncio primitive bound to the wrong
    loop raises "bound to a different event loop" under pytest-asyncio.
  - The cap is read once at first build for the process lifetime. Changing the
    setting afterwards has no effect until ``_reset_for_tests()`` rebuilds it
    (documented, tests-only reset).

This is a PER-PROCESS cap. REST (uvicorn :8000) and MCP HTTP (:8765) are separate
processes, so each enforces its own budget; the nginx edge layer bounds the
aggregate. See RAGSettings.max_concurrent_requests.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from config import get_settings

logger = logging.getLogger(__name__)


class RagCapacityExceeded(Exception):
    """Raised when a RAG slot cannot be acquired because the cap is reached.

    Carries the observed ``in_flight`` count and the ``cap`` for logging. Used on
    the MCP path (no HTTPException context) and by ``rag_slot()``; REST handlers
    translate it into an HTTP 503 + Retry-After.
    """

    def __init__(self, in_flight: int, cap: int) -> None:
        self.in_flight = in_flight
        self.cap = cap
        super().__init__(f"RAG capacity exceeded: {in_flight}/{cap} in-flight")


# Lazily-initialised process-wide state. Never build at import time.
_lock: asyncio.Lock | None = None
_in_flight: int = 0
_cap: int | None = None


def _ensure_state() -> None:
    """Build the lock and read the cap from settings on first use (idempotent)."""
    global _lock, _cap
    if _lock is None:
        _lock = asyncio.Lock()
    if _cap is None:
        try:
            _cap = get_settings().rag.max_concurrent_requests
        except Exception as e:
            logger.error("Failed to resolve RAG concurrency cap from settings", extra={"error": str(e)})
            raise


def capacity() -> int:
    """Return the configured hard cap on simultaneous in-flight RAG executions."""
    _ensure_state()
    assert _cap is not None
    return _cap


def current_in_flight() -> int:
    """Return the current number of held RAG slots (for logging / metrics / tests)."""
    return _in_flight


async def try_acquire() -> bool:
    """Non-blocking acquire of one RAG slot.

    Returns True if a slot was reserved, False immediately if the cap is reached.
    Never waits for a slot to free up. The caller owns the matching ``release()``.
    """
    global _in_flight
    _ensure_state()
    assert _lock is not None and _cap is not None
    async with _lock:
        if _in_flight >= _cap:
            logger.warning(
                "RAG slot acquire rejected at capacity",
                extra={"in_flight": _in_flight, "cap": _cap},
            )
            return False
        _in_flight += 1
        return True


def release() -> None:
    """Release exactly one previously-acquired RAG slot.

    Fail-fast: releasing without a matching acquire (count would go negative) is a
    programming error and raises rather than silently clamping.
    """
    global _in_flight
    if _in_flight <= 0:
        logger.error("RAG slot release called with no slot held", extra={"in_flight": _in_flight})
        raise RuntimeError("RAG slot release called with no slot held")
    _in_flight -= 1


@asynccontextmanager
async def rag_slot():
    """Acquire a RAG slot for the duration of the block, release in ``finally``.

    Raises ``RagCapacityExceeded`` (with in_flight/cap) if no slot is available.
    Primary API for ``rag_chat`` and the MCP tools. For the SSE path the acquire
    and release straddle the handler/generator boundary, so that path uses the raw
    ``try_acquire()`` / ``release()`` pair instead of this context manager.
    """
    acquired = await try_acquire()
    if not acquired:
        raise RagCapacityExceeded(in_flight=current_in_flight(), cap=capacity())
    try:
        yield
    finally:
        release()


def _reset_for_tests() -> None:
    """Drop cached state so a test can rebuild the guard with a patched cap.

    Tests-only. Resets the in-flight counter, forces the cap to be re-read from
    settings, and drops the lock so it rebinds to the next event loop.
    """
    global _lock, _in_flight, _cap
    _lock = None
    _in_flight = 0
    _cap = None
