"""
Standalone SSE-connection admission counter for the MCP transport (COST-5).

The MCP SSE app (:8765) is a separate uvicorn from the REST app; a flood of
long-lived SSE connections can exhaust the 4GB box independently of the
per-request concurrency guard. This module owns ONE process-wide counter capped
at ``settings.rag.mcp_max_sse_connections`` with the same non-blocking-admission
contract as the concurrency guard.

It is deliberately a NEW, standalone helper so the SSE auth middleware (whose
body is owned by the auth layer) can enforce the cap by importing and calling
``try_open()`` on connect and ``close()`` on disconnect WITHOUT this change
touching the middleware body. Enforcement wiring lives in that middleware; this
module is the single source of truth for the counter and the cap.
"""

import asyncio
import logging

from config import get_settings

logger = logging.getLogger(__name__)

_lock: asyncio.Lock | None = None
_open: int = 0
_cap: int | None = None


def _ensure_state() -> None:
    global _lock, _cap
    if _lock is None:
        _lock = asyncio.Lock()
    if _cap is None:
        _cap = get_settings().rag.mcp_max_sse_connections


def current_open() -> int:
    """Return the current number of held SSE connection slots."""
    return _open


async def try_open() -> bool:
    """Non-blocking reserve of one SSE connection slot; False if at capacity."""
    global _open
    _ensure_state()
    assert _lock is not None and _cap is not None
    async with _lock:
        if _open >= _cap:
            logger.warning(
                "MCP SSE connection admission rejected at capacity",
                extra={"event": "mcp_sse_cap_rejected", "open": _open, "cap": _cap},
            )
            return False
        _open += 1
        return True


def close() -> None:
    """Release one previously-opened SSE connection slot (fail-fast on underflow)."""
    global _open
    if _open <= 0:
        logger.error("MCP SSE close called with no connection held", extra={"open": _open})
        raise RuntimeError("MCP SSE close called with no connection held")
    _open -= 1


def _reset_for_tests() -> None:
    global _lock, _open, _cap
    _lock = None
    _open = 0
    _cap = None
