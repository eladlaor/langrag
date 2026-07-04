"""
MongoDB Connection Management

Provides connection pooling and database client management for MongoDB 8.x.
Uses PyMongo's native async client (AsyncMongoClient) for FastAPI compatibility.

Connection URL priority:
1. MONGODB_URI environment variable (recommended for Docker)
2. Settings from config.py (local development)
"""

import asyncio
import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from config import get_settings

logger = logging.getLogger(__name__)

# Global client instances (connection pool)
_client: AsyncMongoClient | None = None
_database: AsyncDatabase | None = None
_db_init_lock: asyncio.Lock = asyncio.Lock()
_sync_client = None
_sync_database = None


def _get_db_lock() -> asyncio.Lock:
    """Get the database initialization lock."""
    return _db_init_lock


def get_mongodb_url() -> str:
    """
    Get MongoDB connection URL from config.

    Priority:
    1. MONGODB_URI (set in docker-compose, e.g., mongodb://mongodb:27017/?replicaSet=rs0)
    2. Build from config settings (host/port/username/password)
    """
    settings = get_settings()
    return settings.get_mongodb_url()


def get_database_name() -> str:
    """Get database name from config."""
    settings = get_settings()
    return settings.database.database


async def get_database() -> AsyncDatabase:
    """
    Get the MongoDB database instance.

    Uses connection pooling - creates client on first call, reuses afterward.
    Protected by asyncio.Lock to prevent duplicate client creation during
    concurrent initialization from parallel graph workers.

    Returns:
        AsyncDatabase instance
    """
    global _client, _database

    # Fast path: already initialized (no lock needed)
    if _database is not None:
        return _database

    # Slow path: acquire lock for initialization
    async with _get_db_lock():
        # Double-check after acquiring lock (another coroutine may have initialized)
        if _database is not None:
            return _database

        try:
            settings = get_settings()
            url = get_mongodb_url()
            db_name = get_database_name()

            from observability.metrics import MongoPoolMetricsListener, PoolClientLabel

            _client = AsyncMongoClient(
                url,
                maxPoolSize=settings.database.max_pool_size,
                minPoolSize=settings.database.min_pool_size,
                serverSelectionTimeoutMS=settings.database.server_selection_timeout_ms,
                event_listeners=[MongoPoolMetricsListener(PoolClientLabel.ASYNC)],
            )

            # Verify connection
            await _client.admin.command("ping")
            from urllib.parse import urlparse

            parsed = urlparse(url)
            safe_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}{parsed.path}"
            logger.info(f"Connected to MongoDB at {safe_url}")

            _database = _client[db_name]
            logger.info(f"Using database: {db_name}")

        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise RuntimeError(f"MongoDB connection failed: {e}") from e

    return _database


async def get_client() -> AsyncMongoClient:
    """Return the shared async MongoDB client (for multi-document transactions).

    Ensures the connection pool is initialized first via get_database(), then
    returns the underlying client. Callers use this to open a session and run a
    transaction across collections, e.g.::

        client = await get_client()
        async with client.start_session() as session:
            async with await session.start_transaction():
                ...

    Raises:
        RuntimeError: if the client failed to initialize.
    """
    await get_database()
    if _client is None:
        raise RuntimeError("MongoDB client is not initialized after get_database()")
    return _client


async def close_connection() -> None:
    """Close the MongoDB connection."""
    global _client, _database

    if _client is not None:
        await _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed")


def get_sync_database():
    """
    Get synchronous MongoDB client for non-async contexts.

    Uses a cached client to avoid creating unbounded connections.
    Prefer async operations with get_database().
    """
    global _sync_client, _sync_database

    if _sync_database is None:
        from pymongo import MongoClient

        from observability.metrics import MongoPoolMetricsListener, PoolClientLabel

        settings = get_settings()
        url = get_mongodb_url()
        db_name = get_database_name()

        _sync_client = MongoClient(
            url,
            maxPoolSize=settings.database.max_pool_size,
            minPoolSize=settings.database.min_pool_size,
            serverSelectionTimeoutMS=settings.database.server_selection_timeout_ms,
            event_listeners=[MongoPoolMetricsListener(PoolClientLabel.SYNC)],
        )
        _sync_database = _sync_client[db_name]

    return _sync_database
