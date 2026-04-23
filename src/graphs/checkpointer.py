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
_checkpointer_cm = None
_init_lock: asyncio.Lock = asyncio.Lock()


def _get_lock() -> asyncio.Lock:
    """Get the checkpointer initialization lock."""
    return _init_lock


async def get_checkpointer() -> AsyncSqliteSaver:
    """
    Get the singleton AsyncSqliteSaver instance.

    Creates the checkpointer on first call, reuses afterward.
    Protected by asyncio.Lock to prevent duplicate initialization
    during concurrent access from parallel graph workers.

    Note: AsyncSqliteSaver.from_conn_string() is an async context manager
    in langgraph-checkpoint-sqlite >= 3.x. We enter the context manager
    and hold it open for the application lifetime, closing it in close_checkpointer().

    Fail-Fast Conditions:
        - SQLite database directory cannot be created
        - Checkpointer setup (table creation) fails
    """
    global _checkpointer, _checkpointer_cm

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

        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(db_path)
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()
        logger.info(f"Checkpointer initialized: {db_path}")

    return _checkpointer


async def close_checkpointer() -> None:
    """Close the checkpointer connection. Called during application shutdown."""
    global _checkpointer, _checkpointer_cm

    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer = None
        _checkpointer_cm = None
        logger.info("Checkpointer closed")
