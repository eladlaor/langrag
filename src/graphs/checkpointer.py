"""
LangGraph Checkpointer (MongoDB-backed).

Uses MongoDBSaver from langgraph-checkpoint-mongodb (0.4.0+) to persist
graph checkpoints in the same MongoDB cluster as the rest of the app's
durable state. Eliminates SQLite as a second source of truth and unlocks
horizontal scaling (checkpoints shared across replicas).

The MongoDBSaver accepts a sync MongoClient and exposes both sync and
async methods. Async methods wrap the sync ops via thread executor —
acceptable for our LLM-bound workload (per-run latency dominated by 30-90
seconds of LLM calls, not checkpoint I/O).
"""

import asyncio
import logging

from langgraph.checkpoint.mongodb import MongoDBSaver

from config import get_settings
from db.connection import get_database_name, get_sync_database

logger = logging.getLogger(__name__)

_checkpointer: MongoDBSaver | None = None
_init_lock: asyncio.Lock = asyncio.Lock()


def _get_lock() -> asyncio.Lock:
    """Get the checkpointer initialization lock."""
    return _init_lock


async def get_checkpointer() -> MongoDBSaver:
    """
    Get the singleton MongoDBSaver instance.

    Lazily constructs on first call, reuses afterward. Protected by an
    asyncio.Lock to prevent duplicate init under concurrent access from
    parallel graph workers.

    Fail-Fast Conditions:
        - MongoDB sync client unavailable (raised from get_sync_database)
        - setup() (collection/index creation) fails
    """
    global _checkpointer

    if _checkpointer is not None:
        return _checkpointer

    async with _get_lock():
        if _checkpointer is not None:
            return _checkpointer

        settings = get_settings()
        db = get_sync_database()
        client = db.client
        db_name = settings.checkpointer.db_name or get_database_name()

        _checkpointer = MongoDBSaver(
            client=client,
            db_name=db_name,
            checkpoint_collection_name=settings.checkpointer.checkpoint_collection,
            writes_collection_name=settings.checkpointer.writes_collection,
            ttl=settings.checkpointer.ttl_seconds,
        )
        _checkpointer.setup()
        logger.info(
            "Checkpointer initialized (MongoDB)",
            extra={
                "db_name": db_name,
                "checkpoint_collection": settings.checkpointer.checkpoint_collection,
                "writes_collection": settings.checkpointer.writes_collection,
                "ttl_seconds": settings.checkpointer.ttl_seconds,
            },
        )

    return _checkpointer


async def close_checkpointer() -> None:
    """
    Release the checkpointer reference.

    The underlying sync MongoClient is owned by db.connection and closed
    there during application shutdown. We drop our singleton reference so a
    subsequent get_checkpointer() reconstructs cleanly if needed.
    """
    global _checkpointer
    if _checkpointer is not None:
        _checkpointer = None
        logger.info("Checkpointer released")
