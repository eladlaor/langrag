"""
Database Module

MongoDB database layer for the newsletter generation pipeline.
Native async architecture for LangGraph 1.0+ workflows.

Structure:
- connection.py: MongoDB client and connection pool
- repositories/: Data access layer (async)
- run_tracker.py: Workflow run tracking (async)
- cache.py: LLM response caching (async)
- batch_jobs.py: Batch job management (async)

Usage (async nodes):
    from db import get_database
    from db.run_tracker import get_tracker
    from db.cache import _get_cache
    from db.batch_jobs import _get_manager
"""

from db.connection import get_database, close_connection
from db.repositories import (
    BaseRepository,
    RunsRepository,
    DiscussionsRepository,
    MessagesRepository,
    CacheRepository,
)
from db.run_tracker import RunTracker, get_tracker
from db.cache import CacheService, _get_cache
from db.batch_jobs import BatchJobManager, BatchJobStatus, _get_manager

__all__ = [
    # Connection
    "get_database",
    "close_connection",
    # Repositories
    "BaseRepository",
    "RunsRepository",
    "DiscussionsRepository",
    "MessagesRepository",
    "CacheRepository",
    # Run Tracker
    "RunTracker",
    "get_tracker",
    # Cache
    "CacheService",
    "_get_cache",
    # Batch Jobs
    "BatchJobManager",
    "BatchJobStatus",
    "_get_manager",
]
