"""
MongoDB Index Definitions

Defines indexes for all collections to optimize query performance.
Run ensure_indexes() on application startup.

Vector Search Index (Manual Setup Required):
-------------------------------------------
For semantic search via embedding_service.py, you need to create a
vector search index on the 'discussions' collection. This must be done
manually through MongoDB Atlas UI or mongosh:

1. Via MongoDB Atlas UI:
   - Go to Atlas > Database > Browse Collections > discussions
   - Click "Search Indexes" tab
   - Create Search Index with this definition:

   {
     "name": "discussion_embeddings",
     "definition": {
       "mappings": {
         "dynamic": true,
         "fields": {
           "embedding": {
             "dimensions": 1536,
             "similarity": "cosine",
             "type": "knnVector"
           }
         }
       }
     }
   }

2. Via mongosh:
   db.discussions.createSearchIndex({
     name: "discussion_embeddings",
     definition: {
       mappings: {
         dynamic: true,
         fields: {
           embedding: {
             dimensions: 1536,
             similarity: "cosine",
             type: "knnVector"
           }
         }
       }
     }
   })

Note: Vector search requires MongoDB Atlas or mongot sidecar service.
"""

import logging
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT

logger = logging.getLogger(__name__)

# Index definitions by collection
INDEXES = {
    "runs": [
        # Primary lookup by run_id
        {"keys": [("run_id", ASCENDING)], "unique": True},
        # Query runs by date range
        {"keys": [("created_at", DESCENDING)]},
        # Filter by status
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        # Filter by data source
        {"keys": [("data_source_name", ASCENDING), ("created_at", DESCENDING)]},
    ],
    "discussions": [
        # Primary lookup
        {"keys": [("discussion_id", ASCENDING)], "unique": True},
        # CRITICAL: Query by run_id (used by API endpoints)
        {"keys": [("run_id", ASCENDING)]},
        # CRITICAL: Query by run_id + ranking score (for sorted results)
        {"keys": [("run_id", ASCENDING), ("ranking_score", DESCENDING)]},
        # Query by run + chat
        {"keys": [("run_id", ASCENDING), ("chat_name", ASCENDING)]},
        # Query by chat
        {"keys": [("chat_name", ASCENDING), ("created_at", DESCENDING)]},
        # Text search on title/content
        {"keys": [("title", TEXT), ("nutshell", TEXT)]},
        # Ranking queries (global)
        {"keys": [("ranking_score", DESCENDING)]},
    ],
    "messages": [
        # Primary lookup
        {"keys": [("message_id", ASCENDING)], "unique": True},
        # CRITICAL: Query by run_id (used by API endpoints)
        {"keys": [("run_id", ASCENDING)]},
        # CRITICAL: Query by run_id + chat_name (most common query pattern)
        {"keys": [("run_id", ASCENDING), ("chat_name", ASCENDING)]},
        # Query by run + timestamp (for chronological ordering)
        {"keys": [("run_id", ASCENDING), ("timestamp", ASCENDING)]},
        # Lookup by original Matrix event ID
        {"keys": [("matrix_event_id", ASCENDING)]},
        # Query by discussion (deprecated - kept for backward compatibility)
        {"keys": [("discussion_id", ASCENDING)]},
        # Query by chat and time range
        {"keys": [("chat_name", ASCENDING), ("timestamp", DESCENDING)]},
        # Query by sender
        {"keys": [("sender", ASCENDING), ("timestamp", DESCENDING)]},
    ],
    "cache": [
        # Primary lookup for cache hits
        {"keys": [("cache_key", ASCENDING)], "unique": True},
        # TTL index for automatic expiration
        {"keys": [("expires_at", ASCENDING)], "expireAfterSeconds": 0},
        # Query by operation type
        {"keys": [("operation_type", ASCENDING)]},
    ],
    "analytics": [
        # Query by date range
        {"keys": [("date", DESCENDING)]},
        # Query by event type
        {"keys": [("event_type", ASCENDING), ("date", DESCENDING)]},
        # Query by data source
        {"keys": [("data_source", ASCENDING), ("date", DESCENDING)]},
    ],
    "batch_jobs": [
        # Primary lookup by job_id (UUID)
        {"keys": [("job_id", ASCENDING)], "unique": True},
        # Query pending jobs for worker (oldest first)
        {"keys": [("status", ASCENDING), ("created_at", ASCENDING)]},
        # Query by status and date (for UI/monitoring)
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        # TTL index for automatic cleanup (30 days after completion)
        # Only applies to completed/failed/cancelled jobs
        {"keys": [("completed_at", ASCENDING)], "expireAfterSeconds": 2592000},
    ],
    "newsletters": [
        # Primary lookup by newsletter_id
        {"keys": [("newsletter_id", ASCENDING)], "unique": True},
        # CRITICAL: Query by run_id (get all newsletters for a run)
        {"keys": [("run_id", ASCENDING)]},
        # Query by run + type (filter per-chat vs consolidated)
        {"keys": [("run_id", ASCENDING), ("newsletter_type", ASCENDING)]},
        # Find recent newsletters by format (for LLM examples)
        {"keys": [("summary_format", ASCENDING), ("created_at", DESCENDING)]},
        # Find newsletters by data source + date range (for similar examples)
        {"keys": [("data_source_name", ASCENDING), ("start_date", ASCENDING), ("end_date", ASCENDING)]},
        # Query by status (find completed newsletters)
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        # CRITICAL: Query for anti-repetition (data source + end date)
        # Used by load_previous_newsletters_from_mongodb()
        {"keys": [("data_source_name", ASCENDING), ("end_date", DESCENDING)]},
    ],
    "extraction_cache": [
        # Primary lookup for cache hits
        {"keys": [("cache_key", ASCENDING)], "unique": True},
        # Query by chat + date range (alternative lookup)
        {"keys": [("chat_name", ASCENDING), ("start_date", ASCENDING), ("end_date", ASCENDING)]},
        # Overlap-aware cache lookup (normalized name + date range for range intersection queries)
        {"keys": [("chat_name_normalized", ASCENDING), ("start_date", ASCENDING), ("end_date", ASCENDING)]},
        # TTL index for automatic expiration
        {"keys": [("expires_at", ASCENDING)], "expireAfterSeconds": 0},
        # Query by creation date (for monitoring)
        {"keys": [("created_at", DESCENDING)]},
    ],
    "polls": [
        # Primary lookup
        {"keys": [("poll_id", ASCENDING)], "unique": True},
        # CRITICAL: Query by run_id (get all polls for a run)
        {"keys": [("run_id", ASCENDING)]},
        # Query by run + chat
        {"keys": [("run_id", ASCENDING), ("chat_name", ASCENDING)]},
        # Query by chat + time range (for dashboard chronological view)
        {"keys": [("chat_name", ASCENDING), ("timestamp", DESCENDING)]},
        # Query by data source + time range (cross-chat dashboard)
        {"keys": [("data_source_name", ASCENDING), ("timestamp", DESCENDING)]},
    ],
    "translation_cache": [
        # Primary lookup: unique per message + target language
        {"keys": [("matrix_event_id", ASCENDING), ("target_language", ASCENDING)], "unique": True},
        # TTL index for automatic expiration
        {"keys": [("expires_at", ASCENDING)], "expireAfterSeconds": 0},
        # Query by chat name (for stats/invalidation)
        {"keys": [("chat_name", ASCENDING)]},
        # Query by chat + language (for targeted invalidation)
        {"keys": [("chat_name", ASCENDING), ("target_language", ASCENDING)]},
    ],
    "sender_maps": [
        # Primary lookup: unique per data source + chat
        {"keys": [("data_source_name", ASCENDING), ("chat_name", ASCENDING)], "unique": True},
    ],
    "room_id_cache": [
        # Primary lookup - UNIQUE constraint prevents duplicates
        {"keys": [("chat_name", ASCENDING)], "unique": True},
        # Reverse lookup (room_id -> chat_name)
        {"keys": [("room_id", ASCENDING)]},
        # Fuzzy matching (case-insensitive, normalized)
        {"keys": [("normalized_name", ASCENDING)]},
        # Analytics/monitoring
        {"keys": [("created_at", DESCENDING)]},
        {"keys": [("last_accessed_at", DESCENDING)]},
    ],
}


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create all indexes for all collections.

    Safe to run multiple times - MongoDB ignores duplicate index creation.

    Args:
        db: AsyncIOMotorDatabase instance
    """
    try:
        for collection_name, indexes in INDEXES.items():
            collection = db[collection_name]
            logger.info(f"Ensuring indexes for collection: {collection_name}")

            for index_def in indexes:
                keys = index_def["keys"]
                options = {k: v for k, v in index_def.items() if k != "keys"}

                await collection.create_index(keys, **options)
                logger.debug(f"  Created index: {keys}")

        logger.info("All indexes created successfully")

    except Exception as e:
        logger.error(f"Failed to create indexes: {e}")
        raise RuntimeError(f"Index creation failed: {e}") from e


async def drop_all_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Drop all non-_id indexes. Use with caution.

    Args:
        db: AsyncIOMotorDatabase instance
    """
    for collection_name in INDEXES.keys():
        collection = db[collection_name]
        await collection.drop_indexes()
        logger.warning(f"Dropped all indexes for collection: {collection_name}")
