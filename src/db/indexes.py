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

import asyncio
import logging
import time

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.operations import SearchIndexModel

from constants import (
    COLLECTION_DISCUSSIONS,
    COLLECTION_RAG_CHUNKS,
    DEFAULT_EMBEDDING_DIMENSION,
    RAG_LEXICAL_INDEX_NAME,
    RAG_VECTOR_INDEX_NAME,
    RAG_VECTOR_INDEX_NAME_LEGACY,
)
from custom_types.field_keys import RAGChunkKeys

# Legacy on-disk text index that no longer has a queryer in the codebase.
# Kept here so ensure_indexes() can drop it idempotently from existing
# deployments. New deployments will simply skip the drop.
_LEGACY_DISCUSSIONS_TEXT_INDEX_NAME = "title_text_nutshell_text"

# Atlas Search builds indexes asynchronously. Poll the index until mongot
# reports it as queryable before serving traffic, with a bounded wait so a
# stuck mongot does not block process startup forever.
_SEARCH_INDEX_READY_TIMEOUT_SECONDS = 120
_SEARCH_INDEX_READY_POLL_INTERVAL_SECONDS = 2

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
    "rag_chunks": [
        # Primary lookup by chunk_id
        {"keys": [("chunk_id", ASCENDING)], "unique": True},
        # Query by source type + source ID (e.g., all chunks from a podcast episode)
        {"keys": [("content_source", ASCENDING), ("source_id", ASCENDING)]},
        # Query by source type + creation date (listing sources)
        {"keys": [("content_source", ASCENDING), ("created_at", DESCENDING)]},
        # Query by source ID + chunk order (reconstruct full document)
        {"keys": [("source_id", ASCENDING), ("chunk_index", ASCENDING)]},
        # Date-range filtering ("AI info melts like ice cream" — caller scopes by source date)
        {"keys": [("content_source", ASCENDING), ("source_date_start", ASCENDING), ("source_date_end", ASCENDING)]},
        {"keys": [("source_date_end", DESCENDING)]},
    ],
    "rag_conversations": [
        # Primary lookup by session_id
        {"keys": [("session_id", ASCENDING)], "unique": True},
        # List sessions by recency
        {"keys": [("created_at", DESCENDING)]},
    ],
    "rag_api_keys": [
        # Primary lookup by hashed key (used on every authenticated request)
        {"keys": [("key_hash", ASCENDING)], "unique": True},
        # Per-key admin lookups (rotation, revocation)
        {"keys": [("key_id", ASCENDING)], "unique": True},
        # Filter enabled keys quickly
        {"keys": [("enabled", ASCENDING), ("created_at", DESCENDING)]},
    ],
    "rag_evaluations": [
        # Primary lookup by evaluation_id
        {"keys": [("evaluation_id", ASCENDING)], "unique": True},
        # Query evaluations by session
        {"keys": [("session_id", ASCENDING)]},
        # Query specific message evaluation
        {"keys": [("session_id", ASCENDING), ("message_id", ASCENDING)]},
        # TTL index for automatic cleanup (90 days)
        {"keys": [("created_at", ASCENDING)], "expireAfterSeconds": 7776000},
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

    When the RAG hybrid retrieval path is enabled (rag.hybrid_enabled), the
    lexical Atlas Search index is treated as a hard dependency: if it cannot
    be created or doesn't become queryable, this function raises and the
    process refuses to start. That avoids a half-broken state where startup
    only logs a warning but every /api/rag/chat call 500s at query time.

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

        # Drop the legacy discussions TEXT index if it lingers on existing
        # deployments. No code path queries $text on discussions anymore;
        # keeping the index just costs RAM on every write.
        await _drop_legacy_discussions_text_index(db)

        # Create vector search index for RAG chunks (idempotent)
        await _ensure_vector_search_index(db)
        # Create lexical Atlas Search index for hybrid retrieval via $rankFusion.
        # Required when hybrid_enabled=True; otherwise best-effort.
        from config import get_settings  # local import to avoid cycles at module load

        lexical_required = get_settings().rag.hybrid_enabled
        lexical_ready = await _ensure_lexical_search_index(db)
        if lexical_required and not lexical_ready:
            raise RuntimeError(
                f"Lexical Atlas Search index '{RAG_LEXICAL_INDEX_NAME}' is not "
                f"queryable, but rag.hybrid_enabled=True requires it. Refusing "
                f"to start in a half-broken state. Verify mongot is running and "
                f"capable of building search indexes, then restart."
            )

    except Exception as e:
        logger.error(f"Failed to create indexes: {e}")
        raise RuntimeError(f"Index creation failed: {e}") from e


def _resolve_target_index_dimensions() -> int:
    """Pick the numDimensions to use when CREATING a fresh vector index.

    Prefers the RAG-specific override, then the global embedding override,
    then the model's native dimension from EMBEDDING_MODEL_DIMENSIONS.
    """
    from config import get_settings
    from constants import DEFAULT_EMBEDDING_DIMENSION, EMBEDDING_MODEL_DIMENSIONS

    settings = get_settings()
    if settings.rag_embedding.dimensions is not None:
        return settings.rag_embedding.dimensions
    if settings.embedding.output_dimensions is not None:
        return settings.embedding.output_dimensions
    rag_model = settings.rag_embedding.model or settings.embedding.default_model
    return EMBEDDING_MODEL_DIMENSIONS.get(rag_model, DEFAULT_EMBEDDING_DIMENSION)


def _extract_vector_index_dimensions(idx_info: dict) -> int | None:
    """Pull numDimensions out of a list_search_indexes() entry.

    Atlas Search returns the definition under either 'latestDefinition' or
    'definition' depending on the API version. We accept both.
    """
    definition = idx_info.get("latestDefinition") or idx_info.get("definition") or {}
    for field in definition.get("fields", []) or []:
        if field.get("type") == "vector":
            return field.get("numDimensions")
    return None


def _validate_embedding_dims_against_index(index_dims: int | None) -> None:
    """Fail-fast if the configured RAG embedding dimensions don't match the
    vector index. Mismatched dims silently break HNSW queries; we refuse to
    start in that state so the operator does a deliberate re-ingest.
    """
    if index_dims is None:
        return
    from config import get_settings  # avoid import cycle at module load

    settings = get_settings()
    configured_dims = (
        settings.rag_embedding.dimensions
        if settings.rag_embedding.dimensions is not None
        else settings.embedding.output_dimensions
    )
    if configured_dims is None:
        rag_model = settings.rag_embedding.model or settings.embedding.default_model
        from constants import DEFAULT_EMBEDDING_DIMENSION, EMBEDDING_MODEL_DIMENSIONS

        configured_dims = EMBEDDING_MODEL_DIMENSIONS.get(rag_model, DEFAULT_EMBEDDING_DIMENSION)

    if configured_dims != index_dims:
        raise RuntimeError(
            f"Embedding dimension mismatch: vector index '{RAG_VECTOR_INDEX_NAME}' "
            f"was built with numDimensions={index_dims}, but the configured RAG "
            f"embedding produces {configured_dims}-dim vectors. HNSW requires dim "
            f"equality; queries against this index would return zero recall. "
            f"Either revert the embedding model/dimensions config or run a full "
            f"re-ingest after dropping and rebuilding the vector index."
        )


async def _drop_legacy_discussions_text_index(db: AsyncIOMotorDatabase) -> None:
    """Drop the legacy compound TEXT index on discussions.(title, nutshell).

    The endpoint that used to call $text on this collection has been removed
    in favor of $vectorSearch. The index now costs write amplification and
    RAM for no readers. Safe to call repeatedly; a missing index is a no-op.
    """
    collection = db[COLLECTION_DISCUSSIONS]
    try:
        existing = await collection.index_information()
        if _LEGACY_DISCUSSIONS_TEXT_INDEX_NAME not in existing:
            return
        await collection.drop_index(_LEGACY_DISCUSSIONS_TEXT_INDEX_NAME)
        logger.info(
            f"Dropped legacy text index '{_LEGACY_DISCUSSIONS_TEXT_INDEX_NAME}' on {COLLECTION_DISCUSSIONS}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"Could not drop legacy text index '{_LEGACY_DISCUSSIONS_TEXT_INDEX_NAME}' on {COLLECTION_DISCUSSIONS}: {e}. "
            f"Drop it manually with db.{COLLECTION_DISCUSSIONS}.dropIndex('{_LEGACY_DISCUSSIONS_TEXT_INDEX_NAME}')"
        )


async def _ensure_vector_search_index(db: AsyncIOMotorDatabase) -> None:
    """
    Create the vector search index on rag_chunks if it doesn't already exist.

    Uses MongoDB's create_search_index API (requires mongot sidecar or Atlas).
    Idempotent: checks existing search indexes first.

    Also fail-fast validates that the configured RAG embedding dimensions match
    the dimensions stored in the existing vector index. Mismatched dimensions
    silently produce zero-recall queries because HNSW requires dim equality,
    so we refuse to start in that state and require a re-ingest under the new
    config.
    """
    collection = db[COLLECTION_RAG_CHUNKS]

    try:
        # Check if vector search index already exists
        existing_index_dims: int | None = None
        existing_indexes = []
        async for idx in collection.list_search_indexes():
            name = idx.get("name", "")
            existing_indexes.append(name)
            if name == RAG_VECTOR_INDEX_NAME:
                existing_index_dims = _extract_vector_index_dimensions(idx)

        if RAG_VECTOR_INDEX_NAME in existing_indexes:
            logger.debug(f"Vector search index '{RAG_VECTOR_INDEX_NAME}' already exists")
            _validate_embedding_dims_against_index(existing_index_dims)
            return

        # Create the vector search index using the modern $vectorSearch schema:
        # a `fields` array with one `vector` entry plus `filter` entries for any
        # field we want to pre-filter on inside the $vectorSearch stage.
        # `quantization: "scalar"` (MongoDB 8.0.4+) reduces index RAM ~3.75x by
        # quantizing float32 embeddings to int8 at index build time, with negligible
        # recall loss for OpenAI text-embedding-3-* vectors.
        target_dims = _resolve_target_index_dimensions()
        search_index = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": target_dims,
                        "similarity": "cosine",
                        "quantization": "scalar",
                    },
                    {"type": "filter", "path": "content_source"},
                    {"type": "filter", "path": "source_date_start"},
                    {"type": "filter", "path": "source_date_end"},
                ]
            },
            name=RAG_VECTOR_INDEX_NAME,
            type="vectorSearch",
        )

        await collection.create_search_index(search_index)
        logger.info(f"Created vector search index: {RAG_VECTOR_INDEX_NAME}")

        # Atlas Search builds asynchronously. Wait until mongot reports the
        # index as queryable before returning so the first queries after
        # process startup don't race the build.
        ready = await _wait_for_search_index_ready(collection, RAG_VECTOR_INDEX_NAME)
        if ready:
            # Once _v2 is queryable, the legacy index is silent dead weight
            # in mongot RAM. Drop it idempotently.
            await _drop_legacy_vector_index(collection)

    except Exception as e:
        # Vector search index creation can fail if mongot is not available
        # (e.g., local dev without Atlas or mongot sidecar). Log and continue.
        logger.warning(
            f"Could not create vector search index '{RAG_VECTOR_INDEX_NAME}': {e}. "
            f"RAG vector search will not work until this index is created. "
            f"If using local MongoDB, ensure the mongot sidecar service is running."
        )


async def _wait_for_search_index_ready(collection, index_name: str) -> bool:
    """
    Poll list_search_indexes() until the given index reports queryable=True.
    Returns True if the index became queryable within the timeout, False otherwise.

    Atlas Search exposes both `status` (one of PENDING/BUILDING/READY/FAILED)
    and the more reliable `queryable` boolean. We trust `queryable` because
    READY status can briefly precede true query readiness on cold mongot.
    """
    deadline = time.monotonic() + _SEARCH_INDEX_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            async for idx in collection.list_search_indexes():
                if idx.get("name") != index_name:
                    continue
                if idx.get("queryable") is True:
                    logger.info(f"Search index ready: {index_name}")
                    return True
                status = idx.get("status", "unknown")
                logger.debug(f"Search index '{index_name}' not yet queryable (status={status})")
                break
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Polling search index '{index_name}' failed: {e}")
        await asyncio.sleep(_SEARCH_INDEX_READY_POLL_INTERVAL_SECONDS)

    logger.warning(
        f"Search index '{index_name}' did not become queryable within "
        f"{_SEARCH_INDEX_READY_TIMEOUT_SECONDS}s. RAG queries may fail until it is."
    )
    return False


async def _drop_legacy_vector_index(collection) -> None:
    """
    Drop the pre-quantization vector index (rag_chunk_embeddings) if present.
    Safe to call repeatedly: a missing legacy index is a no-op.
    """
    try:
        existing = {idx.get("name") async for idx in collection.list_search_indexes()}
        if RAG_VECTOR_INDEX_NAME_LEGACY not in existing:
            return
        await collection.drop_search_index(RAG_VECTOR_INDEX_NAME_LEGACY)
        logger.info(f"Dropped legacy vector search index: {RAG_VECTOR_INDEX_NAME_LEGACY}")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"OPERATOR ACTION REQUIRED: failed to drop legacy vector search "
            f"index '{RAG_VECTOR_INDEX_NAME_LEGACY}': {e}. The new index "
            f"'{RAG_VECTOR_INDEX_NAME}' is queryable so retrieval is unaffected, "
            f"but the legacy index will keep consuming mongot RAM until it is "
            f"dropped manually with: "
            f"db.{COLLECTION_RAG_CHUNKS}.dropSearchIndex('{RAG_VECTOR_INDEX_NAME_LEGACY}')"
        )


async def _ensure_lexical_search_index(db: AsyncIOMotorDatabase) -> bool:
    """
    Create an Atlas Search lexical index over rag_chunks.content for hybrid
    retrieval. Paired with the vector index via $rankFusion (MongoDB 8.1+).

    Returns:
        True if the index exists and is queryable, False otherwise. Callers
        decide whether a False here is fatal (see ensure_indexes()).
    """
    collection = db[COLLECTION_RAG_CHUNKS]

    try:
        existing_indexes = []
        async for idx in collection.list_search_indexes():
            existing_indexes.append(idx.get("name", ""))

        if RAG_LEXICAL_INDEX_NAME in existing_indexes:
            logger.debug(f"Lexical search index '{RAG_LEXICAL_INDEX_NAME}' already exists")
            # Even if present, verify it's queryable before declaring success
            return await _wait_for_search_index_ready(collection, RAG_LEXICAL_INDEX_NAME)

        search_index = SearchIndexModel(
            definition={
                "mappings": {
                    "dynamic": False,
                    "fields": {
                        RAGChunkKeys.CONTENT: {
                            "type": "string",
                            "analyzer": "lucene.standard",
                        },
                        RAGChunkKeys.CONTENT_SOURCE: {"type": "token"},
                        RAGChunkKeys.SOURCE_DATE_START: {"type": "date"},
                        RAGChunkKeys.SOURCE_DATE_END: {"type": "date"},
                    },
                }
            },
            name=RAG_LEXICAL_INDEX_NAME,
            type="search",
        )

        await collection.create_search_index(search_index)
        logger.info(f"Created lexical search index: {RAG_LEXICAL_INDEX_NAME}")
        return await _wait_for_search_index_ready(collection, RAG_LEXICAL_INDEX_NAME)

    except Exception as e:
        logger.warning(
            f"Could not create lexical search index '{RAG_LEXICAL_INDEX_NAME}': {e}. "
            f"Hybrid retrieval via $rankFusion will be unavailable until this index exists."
        )
        return False


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
