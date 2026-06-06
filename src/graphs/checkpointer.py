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

NOTE (P2, deferred): a fully-async AsyncMongoDBSaver backed by Motor would
remove the second sync connection pool and the thread-executor hops, but it
is NOT available in the pinned langgraph-checkpoint-mongodb 0.4.0 range
(0.4.0 exports only MongoDBSaver). This is an elegance/consistency win, not a
correctness fix, and is gated on a dependency bump — intentionally not done.
TTL bounding (set via CheckpointerSettings.ttl_seconds) is the change that
actually matters and is applied.
"""

import asyncio
import logging

import bson
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


def log_checkpoint_stats(thread_id: str) -> None:
    """
    Emit a lightweight per-run observability log of checkpoint churn for a thread.

    Logs the number of checkpoint + checkpoint_writes documents and the largest
    single document size (bytes). The two real failure modes of this saver are
    (a) write volume on long graphs and (b) a single super-step's state nearing
    the 16MB BSON cap if graph state grows large — this surfaces both.

    Fail-soft: observability must never break a run, so any error is logged at
    debug and swallowed (the run already completed by the time this is called).
    """
    try:
        settings = get_settings()
        db = get_sync_database()
        stats: dict[str, int] = {}
        for collection_name in (settings.checkpointer.checkpoint_collection, settings.checkpointer.writes_collection):
            collection = db[collection_name]
            count = 0
            max_size = 0
            for doc in collection.find({"thread_id": thread_id}):
                count += 1
                doc_size = len(bson.BSON.encode(doc))
                if doc_size > max_size:
                    max_size = doc_size
            stats[f"{collection_name}_count"] = count
            stats[f"{collection_name}_max_doc_bytes"] = max_size

        logger.info(
            "Checkpoint stats for thread",
            extra={"thread_id": thread_id, **stats},
        )
    except Exception as exc:
        logger.debug(
            "Failed to compute checkpoint stats (non-fatal)",
            extra={"thread_id": thread_id, "error": str(exc)},
        )


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
