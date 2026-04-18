"""
LangGraph Checkpointer Management

Provides an async singleton AsyncSqliteSaver for production graph checkpointing.
Uses double-checked locking pattern (same as src/db/connection.py) to ensure
thread-safe initialization in concurrent async contexts.

Env override: CHECKPOINTER_SQLITE_PATH (default: data/checkpoints/langgraph.db)
"""

import asyncio
import logging
import os

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config import get_settings

logger = logging.getLogger(__name__)

_checkpointer: AsyncSqliteSaver | None = None
_init_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Get or create the checkpointer initialization lock (bound to current event loop)."""
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


async def get_checkpointer() -> AsyncSqliteSaver:
    """
    Get the singleton AsyncSqliteSaver instance.

    Creates the checkpointer on first call, reuses afterward.
    Protected by asyncio.Lock to prevent duplicate initialization
    during concurrent access from parallel graph workers.

    Fail-Fast Conditions:
        - SQLite database directory cannot be created
        - Checkpointer setup (table creation) fails
    """
    global _checkpointer

    # Fast path: already initialized
    if _checkpointer is not None:
        return _checkpointer

    # Slow path: acquire lock for initialization
    async with _get_lock():
        # Double-check after acquiring lock
        if _checkpointer is not None:
            return _checkpointer

        settings = get_settings()
        db_path = settings.checkpointer.sqlite_path

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        _checkpointer = AsyncSqliteSaver.from_conn_string(db_path)
        await _checkpointer.setup()
        logger.info(f"Checkpointer initialized: {db_path}")

    return _checkpointer


async def close_checkpointer() -> None:
    """Close the checkpointer connection. Called during application shutdown."""
    global _checkpointer

    if _checkpointer is not None:
        await _checkpointer.conn.close()
        _checkpointer = None
        logger.info("Checkpointer closed")
