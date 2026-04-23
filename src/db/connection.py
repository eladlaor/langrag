"""
MongoDB Connection Management

Provides connection pooling and database client management for MongoDB 8.x.
Uses motor (async driver) for FastAPI compatibility.

Connection URL priority:
1. MONGODB_URI environment variable (recommended for Docker)
2. Settings from config.py (local development)
"""

import asyncio
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import get_settings

logger = logging.getLogger(__name__)

# Global client instances (connection pool)
_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None
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


async def get_database() -> AsyncIOMotorDatabase:
    """
    Get the MongoDB database instance.

    Uses connection pooling - creates client on first call, reuses afterward.
    Protected by asyncio.Lock to prevent duplicate client creation during
    concurrent initialization from parallel graph workers.

    Returns:
        AsyncIOMotorDatabase instance
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

            _client = AsyncIOMotorClient(
                url,
                maxPoolSize=settings.database.max_pool_size,
                minPoolSize=settings.database.min_pool_size,
                serverSelectionTimeoutMS=settings.database.server_selection_timeout_ms,
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


async def close_connection() -> None:
    """Close the MongoDB connection."""
    global _client, _database

    if _client is not None:
        _client.close()
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

        settings = get_settings()
        url = get_mongodb_url()
        db_name = get_database_name()

        _sync_client = MongoClient(
            url,
            maxPoolSize=settings.database.max_pool_size,
            minPoolSize=settings.database.min_pool_size,
            serverSelectionTimeoutMS=settings.database.server_selection_timeout_ms,
        )
        _sync_database = _sync_client[db_name]

    return _sync_database
