"""
MongoDB Index Definitions

Defines indexes for all collections to optimize query performance.
Run ensure_indexes() on application startup.

All vector search indexes (rag_chunks, discussions, agent_memories) are created
programmatically by ensure_indexes() using the modern vectorSearch syntax with
scalar quantization. There is no manual Atlas-UI / mongosh setup step: indexes
are code. Vector search requires MongoDB Atlas or the mongot sidecar; when it is
unavailable the per-index builders log and continue.
"""

import asyncio
import logging
import time

from pymongo.asynchronous.database import AsyncDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.operations import SearchIndexModel

from constants import (
    AGENT_MEMORY_LEXICAL_INDEX_NAME,
    AGENT_MEMORY_VECTOR_INDEX_NAME,
    COLLECTION_AGENT_MEMORIES,
    COLLECTION_DISCUSSIONS,
    COLLECTION_MESSAGES,
    COLLECTION_RAG_CHUNKS,
    COLLECTION_RAG_QUERY_QUOTA,
    DEFAULT_EMBEDDING_DIMENSION,
    DISCUSSION_VECTOR_INDEX_NAME,
    MIN_SUPPORTED_SCHEMA_VERSIONS,
    RAG_LEXICAL_INDEX_NAME,
    RAG_VECTOR_INDEX_NAME,
    RAG_VECTOR_INDEX_NAME_LEGACY,
    SCHEMA_VERSION_FIELD,
)
from custom_types.field_keys import AgentMemoryKeys, DbFieldKeys, RAGChunkKeys, RAGQueryQuotaKeys

# Legacy on-disk text index that no longer has a queryer in the codebase.
# Kept here so ensure_indexes() can drop it idempotently from existing
# deployments. New deployments will simply skip the drop.
_LEGACY_DISCUSSIONS_TEXT_INDEX_NAME = "title_text_nutshell_text"

# Auto-generated name of the standalone {run_id: 1} index. It is redundant on
# both `discussions` and `messages` because run_id is the prefix of their
# compound indexes (which already serve equality-on-run_id). Dropped
# idempotently from existing deployments; never recreated.
_REDUNDANT_RUN_ID_INDEX_NAME = "run_id_1"
_REDUNDANT_RUN_ID_PREFIX_COLLECTIONS = (COLLECTION_DISCUSSIONS, COLLECTION_MESSAGES)

# Server-side $jsonSchema validators for the high-value collections. They are a
# belt-and-suspenders complement to the Pydantic models: because the models use
# extra="allow" and some writers build dicts directly, MongoDB is the only layer
# that can guarantee shape regardless of which code path inserts. The validators
# deliberately enforce ONLY the always-present key fields and their bsonType,
# with additionalProperties: true — they must NOT encode a closed shape, or they
# would reject the legitimate documents the pipeline writes (two-pass messages,
# BinData embeddings, open-ended metadata). Applied with validationLevel:
# "moderate" + validationAction: "error" so existing non-conforming documents
# are never retroactively rejected, only new/updated conforming ones are guarded.
_COLLECTION_VALIDATORS: dict[str, dict] = {
    COLLECTION_MESSAGES: {
        "$jsonSchema": {
            "bsonType": "object",
            # Only fields written by BOTH the raw and translated passes. timestamp
            # is intentionally NOT required (it can be absent/null mid-pipeline).
            "required": [SCHEMA_VERSION_FIELD, DbFieldKeys.MESSAGE_ID, DbFieldKeys.RUN_ID, DbFieldKeys.CHAT_NAME, DbFieldKeys.SENDER],
            "properties": {
                SCHEMA_VERSION_FIELD: {"bsonType": "int"},
                DbFieldKeys.MESSAGE_ID: {"bsonType": "string"},
                DbFieldKeys.RUN_ID: {"bsonType": "string"},
                DbFieldKeys.CHAT_NAME: {"bsonType": "string"},
                DbFieldKeys.SENDER: {"bsonType": "string"},
                DbFieldKeys.TIMESTAMP: {"bsonType": ["long", "int", "null"]},
            },
            "additionalProperties": True,
        }
    },
    COLLECTION_DISCUSSIONS: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [SCHEMA_VERSION_FIELD, DbFieldKeys.DISCUSSION_ID, DbFieldKeys.RUN_ID, DbFieldKeys.CHAT_NAME, DbFieldKeys.MESSAGE_IDS],
            "properties": {
                SCHEMA_VERSION_FIELD: {"bsonType": "int"},
                DbFieldKeys.DISCUSSION_ID: {"bsonType": "string"},
                DbFieldKeys.RUN_ID: {"bsonType": "string"},
                DbFieldKeys.CHAT_NAME: {"bsonType": "string"},
                DbFieldKeys.MESSAGE_IDS: {"bsonType": "array"},
                # Embedding, when present, is BinData (subtype 9 FLOAT32 vector).
                DbFieldKeys.EMBEDDING: {"bsonType": ["binData", "null"]},
            },
            "additionalProperties": True,
        }
    },
    COLLECTION_RAG_CHUNKS: {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [SCHEMA_VERSION_FIELD, RAGChunkKeys.CHUNK_ID, RAGChunkKeys.CONTENT_SOURCE, RAGChunkKeys.CONTENT, RAGChunkKeys.EMBEDDING],
            "properties": {
                SCHEMA_VERSION_FIELD: {"bsonType": "int"},
                RAGChunkKeys.CHUNK_ID: {"bsonType": "string"},
                RAGChunkKeys.CONTENT_SOURCE: {"bsonType": "string"},
                RAGChunkKeys.CONTENT: {"bsonType": "string"},
                # Stored as BSON Binary subtype-9 FLOAT32 vector.
                RAGChunkKeys.EMBEDDING: {"bsonType": "binData"},
                RAGChunkKeys.SOURCE_DATE_START: {"bsonType": ["date", "null"]},
                RAGChunkKeys.SOURCE_DATE_END: {"bsonType": ["date", "null"]},
            },
            "additionalProperties": True,
        }
    },
}

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
        # NOTE: a standalone {run_id} index is intentionally omitted. Equality
        # on run_id is already served by the {run_id, ranking_score} and
        # {run_id, chat_name} compounds below (run_id is their prefix), so a
        # separate single-field index would only add write amplification + RAM.
        # _drop_redundant_run_id_prefix_indexes() removes it from existing deployments.
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
        # NOTE: a standalone {run_id} index is intentionally omitted — run_id is
        # the prefix of every compound below, which already serves equality on
        # run_id alone. _drop_redundant_run_id_prefix_indexes() removes the
        # legacy single-field index from existing deployments.
        # CRITICAL: Query by run_id + chat_name (most common query pattern)
        {"keys": [("run_id", ASCENDING), ("chat_name", ASCENDING)]},
        # Query by run + timestamp (for chronological ordering)
        {"keys": [("run_id", ASCENDING), ("timestamp", ASCENDING)]},
        # ESR-correct compound for get_messages_by_run and get_messages_page:
        # equality on run_id (+ optional chat_name), then the (timestamp,
        # message_id) sort key. message_id is included so keyset pagination's
        # tiebreaker sort is fully index-covered (no residual in-memory SORT on
        # equal-timestamp groups) and its $or cursor predicate is index-backed.
        {"keys": [("run_id", ASCENDING), ("chat_name", ASCENDING), ("timestamp", ASCENDING), ("message_id", ASCENDING)]},
        # Lookup by original Matrix event ID
        {"keys": [("matrix_event_id", ASCENDING)]},
        # Query by discussion (deprecated - kept for backward compatibility)
        {"keys": [("discussion_id", ASCENDING)]},
        # Query by chat and time range
        {"keys": [("chat_name", ASCENDING), ("timestamp", DESCENDING)]},
        # Query by sender
        {"keys": [("sender", ASCENDING), ("timestamp", DESCENDING)]},
    ],
    "llm_response_cache": [
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
    "extraction_cache_chunks": [
        # Ordered assembly + uniqueness: one chunk per (cache_key, chunk_index).
        {"keys": [("cache_key", ASCENDING), ("chunk_index", ASCENDING)], "unique": True},
        # Bulk delete / count of all chunks for a cache_key (invalidation, re-cache).
        {"keys": [("cache_key", ASCENDING)]},
        # TTL mirrors the parent so orphaned chunks self-clean on the same clock.
        {"keys": [("expires_at", ASCENDING)], "expireAfterSeconds": 0},
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
        # Owner-scoped session listing, sorted by recency (match owner, then sort updated_at desc)
        {"keys": [("owner", ASCENDING), ("updated_at", DESCENDING)]},
        # List sessions by recency
        {"keys": [("created_at", DESCENDING)]},
    ],
    "rag_messages": [
        # Unique message_id guards against duplicate inserts (idempotent migration too)
        {"keys": [("message_id", ASCENDING)], "unique": True},
        # History retrieval: last-N for a session, newest first. Also serves
        # count_for_session and cascade delete_for_session (session_id prefix).
        {"keys": [("session_id", ASCENDING), ("created_at", DESCENDING)]},
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
    "room_id_map": [
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
    # Agentic chatbot layer (v1.13.0+). See knowledge/plans/AGENTIC_CHATBOT_LAYER.md.
    "users": [
        # Primary lookup
        {"keys": [("user_id", ASCENDING)], "unique": True},
        # Unique-by-email gives us idempotent signup + cheap email auth lookups.
        # Email is canonicalized (lowercased + trimmed) at the repository boundary
        # by normalize_email(), so this case-sensitive unique index is sufficient:
        # every stored value is already lowercase. (A case-insensitive collation
        # would be defense-in-depth, but changing an existing index's collation
        # requires an explicit drop+recreate migration; normalization at the one
        # repo chokepoint closes the duplicate-identity hole without that.)
        {"keys": [("email", ASCENDING)], "unique": True},
        # Reverse community lookup (e.g., "who owns mcp_israel?")
        {"keys": [("communities", ASCENDING)]},
        # External-identity lookup for Google sign-in (self-signup, schema v3).
        # sparse=True is required so the many password-only rows (google_sub
        # absent / None) do not collide under the unique constraint.
        {"keys": [("google_sub", ASCENDING)], "unique": True, "sparse": True},
    ],
    "podcast_api_consumers": [
        # Unique email: idempotent request-key upsert + the one identity anchor
        # for the isolated consumer lane (these are NEVER in the users collection).
        {"keys": [("email", ASCENDING)], "unique": True},
        # Verify lookup by the current single-use verification-token hash. sparse
        # so the many verified rows (hash cleared to null) do not bloat the index.
        {"keys": [("verification_token_hash", ASCENDING)], "sparse": True},
        # Hot-path last_used_at update + admin/revocation lookups by the minted
        # key_id. sparse: pending (unverified) rows have key_id null.
        {"keys": [("key_id", ASCENDING)], "sparse": True},
        # Per-email rate-cap bucket lookup. count_recent_requests queries by the
        # canonicalized dedup_key (+tag stripped, gmail dots removed) so plus- and
        # dot-alias variants share one cap; index it so that check is not a scan.
        {"keys": [("dedup_key", ASCENDING)]},
        # NOTE: NO expireAfterSeconds TTL here. The token expiry is enforced in
        # application logic; a TTL on token expiry would delete the whole consumer
        # record (including a verified consumer's key reference), not just the
        # stale token. The token hash is cleared on verify instead.
    ],
    "access_requests": [
        # Primary lookup by request_id
        {"keys": [("request_id", ASCENDING)], "unique": True},
        # Admin review listing: pending first, newest first
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        # Per-email history (newest first)
        {"keys": [("email", ASCENDING), ("created_at", DESCENDING)]},
    ],
    "user_api_keys": [
        # Per-request lookup on the hashed bearer
        {"keys": [("key_hash", ASCENDING)], "unique": True},
        # Admin operations (rotation, revocation)
        {"keys": [("key_id", ASCENDING)], "unique": True},
        # List a user's keys
        {"keys": [("user_id", ASCENDING), ("created_at", DESCENDING)]},
        # Filter enabled keys quickly
        {"keys": [("enabled", ASCENDING), ("created_at", DESCENDING)]},
    ],
    "agent_sessions": [
        # Primary lookup (session_id == LangGraph thread_id)
        {"keys": [("session_id", ASCENDING)], "unique": True},
        # Session browser: a user's sessions, newest first
        {"keys": [("user_id", ASCENDING), ("last_message_at", DESCENDING)]},
        # Sliding TTL: abandoned sessions self-clean
        {"keys": [("expires_at", ASCENDING)], "expireAfterSeconds": 0},
    ],
    "agent_memories": [
        # Primary lookup
        {"keys": [("memory_id", ASCENDING)], "unique": True},
        # User-scoped retrieval (every query MUST pre-filter on user_id)
        {"keys": [("user_id", ASCENDING), ("namespace", ASCENDING)]},
        # Listing: user's memories newest first
        {"keys": [("user_id", ASCENDING), ("created_at", DESCENDING)]},
        # Episodic TTL: only set on namespace=="episodic"
        {"keys": [("expires_at", ASCENDING)], "expireAfterSeconds": 0},
    ],
}

# Per-key daily query-quota counters (COST-1) + global embed breaker (COST-4b).
# Keyed by the constant collection name to avoid a hardcoded literal, and added
# post-dict since the literals above predate the convention. A compound unique
# index on (key_id, day) makes the atomic $inc upsert race-free; the expires_at
# TTL self-cleans stale day-counters.
INDEXES[COLLECTION_RAG_QUERY_QUOTA] = [
    {"keys": [(RAGQueryQuotaKeys.KEY_ID, ASCENDING), (RAGQueryQuotaKeys.DAY, ASCENDING)], "unique": True},
    {"keys": [(RAGQueryQuotaKeys.EXPIRES_AT, ASCENDING)], "expireAfterSeconds": 0},
]


async def ensure_schema_versions(db: AsyncDatabase) -> None:
    """Fail fast if any stored document carries a schema_version BELOW the
    minimum supported version for its collection.

    There is no read-path migration ladder: documents are expected to be at the
    current schema version (migrations are applied offline/eager via scripts).
    This guard refuses to start the process if it finds a document whose
    explicit schema_version is below MIN_SUPPORTED_SCHEMA_VERSIONS, so a stale
    document can never be silently misread by code that assumes the current
    shape. On a clean or up-to-date database this is a cheap, count-only no-op.

    A document MISSING the field entirely is NOT treated as stale: the stamp was
    introduced additively, so pre-versioning documents read back correctly via
    model defaults. Treating them as stale would block startup on every existing
    deployment for no correctness benefit. Only an explicit, too-low version
    indicates a document that genuinely predates a non-additive shape change.
    """
    try:
        for collection_name, min_version in MIN_SUPPORTED_SCHEMA_VERSIONS.items():
            collection = db[collection_name]
            stale_count = await collection.count_documents({SCHEMA_VERSION_FIELD: {"$lt": min_version}})
            if stale_count:
                raise RuntimeError(
                    f"Schema-version guard: {stale_count} document(s) in "
                    f"'{collection_name}' are below the minimum supported "
                    f"schema_version ({min_version}). There is no read-path "
                    f"migration; run the offline migration script for this "
                    f"collection before starting."
                )
        logger.info("Schema-version guard passed for all versioned collections")
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Schema-version guard failed to run: {e}")
        raise RuntimeError(f"Schema-version guard failed: {e}") from e


async def ensure_indexes(db: AsyncDatabase) -> None:
    """
    Create all indexes for all collections.

    Safe to run multiple times - MongoDB ignores duplicate index creation.

    When the RAG hybrid retrieval path is enabled (rag.hybrid_enabled), the
    lexical Atlas Search index is treated as a hard dependency: if it cannot
    be created or doesn't become queryable, this function raises and the
    process refuses to start. That avoids a half-broken state where startup
    only logs a warning but every /api/rag/chat call 500s at query time.

    Args:
        db: AsyncDatabase instance
    """
    try:
        # Refuse to start against documents older than the minimum supported
        # schema version (no lazy migration exists to upgrade them on read).
        await ensure_schema_versions(db)

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

        # Drop the now-redundant standalone {run_id} indexes on discussions /
        # messages (their run_id-prefixed compounds already serve those queries).
        await _drop_redundant_run_id_prefix_indexes(db)

        # Apply server-side $jsonSchema validators on the high-value collections
        # to enforce document shape regardless of which code path writes (the
        # Pydantic models use extra="allow", so this is the only layer that
        # catches drift from non-repo writers).
        await _ensure_collection_validators(db)

        # Create vector search index for RAG chunks (idempotent)
        await _ensure_vector_search_index(db)
        # Create vector search index for discussions (idempotent). Same modern
        # vectorSearch syntax; replaces the former manual Atlas-UI setup step.
        await _ensure_discussion_vector_index(db)
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

        # Agentic chatbot layer (v1.13.0+): paired vector + lexical Atlas
        # Search indexes on agent_memories for $rankFusion hybrid retrieval.
        # Best-effort: when mongot is unavailable (e.g., local dev without
        # the sidecar) the agent runtime falls back to BSON-level queries
        # without hybrid retrieval; the warning is loud enough to notice.
        await _ensure_agent_memory_vector_index(db)
        await _ensure_agent_memory_lexical_index(db)

    except Exception as e:
        logger.error(f"Failed to create indexes: {e}")
        raise RuntimeError(f"Index creation failed: {e}") from e


def _resolve_target_index_dimensions() -> int:
    """Pick the numDimensions to use when CREATING a fresh vector index.

    Prefers the RAG-specific override, then the global embedding override,
    then the model's native dimension from EMBEDDING_MODEL_DIMENSIONS.
    """
    from config import get_settings
    from constants import EMBEDDING_MODEL_DIMENSIONS

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


def _validate_embedding_dims_against_index(index_dims: int | None, index_name: str = RAG_VECTOR_INDEX_NAME) -> None:
    """Fail-fast if the configured RAG embedding dimensions don't match the
    vector index. Mismatched dims silently break HNSW queries; we refuse to
    start in that state so the operator does a deliberate re-ingest.

    index_name only affects the error message; both the RAG chunk index and the
    discussions index are built from the same resolved embedding dimensions.
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
            f"Embedding dimension mismatch: vector index '{index_name}' "
            f"was built with numDimensions={index_dims}, but the configured "
            f"embedding produces {configured_dims}-dim vectors. HNSW requires dim "
            f"equality; queries against this index would return zero recall. "
            f"Either revert the embedding model/dimensions config or run a full "
            f"re-ingest after dropping and rebuilding the vector index."
        )


async def _drop_legacy_discussions_text_index(db: AsyncDatabase) -> None:
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


async def _ensure_collection_validators(db: AsyncDatabase) -> None:
    """Apply (or update) the $jsonSchema validators in _COLLECTION_VALIDATORS.

    Uses `collMod` on existing collections and `create` for missing ones, both
    with validationLevel="moderate" + validationAction="error". Idempotent:
    re-running simply re-asserts the same validator. Best-effort per collection
    — a validator that can't be applied logs a warning rather than blocking
    startup, since the Pydantic layer is still the primary guard.
    """
    for collection_name, validator in _COLLECTION_VALIDATORS.items():
        try:
            existing = await db.list_collection_names()
            if collection_name in existing:
                await db.command(
                    {
                        "collMod": collection_name,
                        "validator": validator,
                        "validationLevel": "moderate",
                        "validationAction": "error",
                    }
                )
            else:
                await db.create_collection(
                    collection_name,
                    validator=validator,
                    validationLevel="moderate",
                    validationAction="error",
                )
            logger.info(f"Applied $jsonSchema validator to {collection_name} (moderate/error)")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Could not apply $jsonSchema validator to {collection_name}: {e}. "
                f"Pydantic-layer validation still applies; fix the validator or run "
                f"collMod manually."
            )


async def _drop_redundant_run_id_prefix_indexes(db: AsyncDatabase) -> None:
    """Drop the standalone {run_id: 1} index on `discussions` and `messages`.

    run_id is the prefix of the compound indexes on both collections, so the
    compounds already serve equality-on-run_id queries. The standalone index is
    pure overhead (write amplification + RAM) with no query it uniquely serves.
    Safe to call repeatedly; a missing index is a no-op.
    """
    for collection_name in _REDUNDANT_RUN_ID_PREFIX_COLLECTIONS:
        collection = db[collection_name]
        try:
            existing = await collection.index_information()
            if _REDUNDANT_RUN_ID_INDEX_NAME not in existing:
                continue
            await collection.drop_index(_REDUNDANT_RUN_ID_INDEX_NAME)
            logger.info(f"Dropped redundant index '{_REDUNDANT_RUN_ID_INDEX_NAME}' on {collection_name} (covered by run_id-prefixed compounds)")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Could not drop redundant index '{_REDUNDANT_RUN_ID_INDEX_NAME}' on {collection_name}: {e}. "
                f"Drop it manually with db.{collection_name}.dropIndex('{_REDUNDANT_RUN_ID_INDEX_NAME}')"
            )


async def _ensure_vector_search_index(db: AsyncDatabase) -> None:
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
        cursor = await collection.list_search_indexes()
        async for idx in cursor:
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
                    # Community pre-filter: top-level data_source_name (promoted
                    # out of metadata so it is filterable). Podcast chunks have
                    # it null and are excluded when a community filter is set.
                    {"type": "filter", "path": "data_source_name"},
                    # Podcast tenant pre-filter (multi-podcast platform): scopes
                    # search_podcasts(podcast=<slug>) to one show inside the
                    # $vectorSearch stage. Null on non-podcast chunks.
                    {"type": "filter", "path": RAGChunkKeys.PODCAST_SLUG},
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


async def _ensure_discussion_vector_index(db: AsyncDatabase) -> None:
    """
    Create the vector search index on the discussions collection if it doesn't
    already exist. Mirrors _ensure_vector_search_index (rag_chunks): modern
    `fields`/vectorSearch syntax with scalar quantization, plus `filter` entries
    on run_id and chat_name so anti-repetition similarity can pre-filter inside
    the $vectorSearch stage rather than with a post-$match.

    Idempotent and best-effort: when mongot/Atlas is unavailable (e.g. local dev
    without the sidecar) it logs and continues, like the RAG chunk index.
    """
    collection = db[COLLECTION_DISCUSSIONS]

    try:
        existing_index_dims: int | None = None
        existing_indexes = []
        cursor = await collection.list_search_indexes()
        async for idx in cursor:
            name = idx.get("name", "")
            existing_indexes.append(name)
            if name == DISCUSSION_VECTOR_INDEX_NAME:
                existing_index_dims = _extract_vector_index_dimensions(idx)

        if DISCUSSION_VECTOR_INDEX_NAME in existing_indexes:
            logger.debug(f"Vector search index '{DISCUSSION_VECTOR_INDEX_NAME}' already exists")
            _validate_embedding_dims_against_index(existing_index_dims, DISCUSSION_VECTOR_INDEX_NAME)
            return

        target_dims = _resolve_target_index_dimensions()
        search_index = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": DbFieldKeys.EMBEDDING,
                        "numDimensions": target_dims,
                        "similarity": "cosine",
                        "quantization": "scalar",
                    },
                    {"type": "filter", "path": DbFieldKeys.RUN_ID},
                    {"type": "filter", "path": DbFieldKeys.CHAT_NAME},
                    # Community pre-filter on discussions (parity with rag_chunks).
                    {"type": "filter", "path": DbFieldKeys.DATA_SOURCE_NAME},
                ]
            },
            name=DISCUSSION_VECTOR_INDEX_NAME,
            type="vectorSearch",
        )

        await collection.create_search_index(search_index)
        logger.info(f"Created vector search index: {DISCUSSION_VECTOR_INDEX_NAME}")
        await _wait_for_search_index_ready(collection, DISCUSSION_VECTOR_INDEX_NAME)

    except Exception as e:
        logger.warning(
            f"Could not create vector search index '{DISCUSSION_VECTOR_INDEX_NAME}': {e}. "
            f"Discussion semantic search / anti-repetition will not work until this "
            f"index is created. If using local MongoDB, ensure the mongot sidecar is running."
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
            cursor = await collection.list_search_indexes()
            async for idx in cursor:
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
        cursor = await collection.list_search_indexes()
        existing = {idx.get("name") async for idx in cursor}
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


async def _ensure_lexical_search_index(db: AsyncDatabase) -> bool:
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
        cursor = await collection.list_search_indexes()
        async for idx in cursor:
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
                        # Community pre-filter (token for exact-match $in).
                        RAGChunkKeys.DATA_SOURCE_NAME: {"type": "token"},
                        # Podcast tenant pre-filter (token for exact-match slug).
                        RAGChunkKeys.PODCAST_SLUG: {"type": "token"},
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


async def _ensure_agent_memory_vector_index(db: AsyncDatabase) -> bool:
    """Create the Atlas Vector Search index on agent_memories.embedding.

    Filter fields (`user_id`, `namespace`) are declared so the agent retriever
    can pre-filter inside `$vectorSearch` itself, which is what makes the
    shared multi-tenant index safe: every query MUST pre-filter on `user_id`.

    Returns True if the index exists and is queryable, False otherwise.
    """
    collection = db[COLLECTION_AGENT_MEMORIES]
    try:
        cursor = await collection.list_search_indexes()
        existing = [idx.get("name", "") async for idx in cursor]
        if AGENT_MEMORY_VECTOR_INDEX_NAME in existing:
            logger.debug(f"Agent memory vector index '{AGENT_MEMORY_VECTOR_INDEX_NAME}' already exists")
            return await _wait_for_search_index_ready(collection, AGENT_MEMORY_VECTOR_INDEX_NAME)

        target_dims = _resolve_target_index_dimensions()
        search_index = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": AgentMemoryKeys.EMBEDDING,
                        "numDimensions": target_dims,
                        "similarity": "cosine",
                        "quantization": "scalar",
                    },
                    {"type": "filter", "path": AgentMemoryKeys.USER_ID},
                    {"type": "filter", "path": AgentMemoryKeys.NAMESPACE},
                ]
            },
            name=AGENT_MEMORY_VECTOR_INDEX_NAME,
            type="vectorSearch",
        )
        await collection.create_search_index(search_index)
        logger.info(f"Created agent memory vector index: {AGENT_MEMORY_VECTOR_INDEX_NAME}")
        return await _wait_for_search_index_ready(collection, AGENT_MEMORY_VECTOR_INDEX_NAME)
    except Exception as e:
        logger.warning(
            f"Could not create agent memory vector index '{AGENT_MEMORY_VECTOR_INDEX_NAME}': {e}. "
            f"Agent long-term memory retrieval will not work until this index is created. "
            f"If using local MongoDB, ensure the mongot sidecar is running."
        )
        return False


async def _ensure_agent_memory_lexical_index(db: AsyncDatabase) -> bool:
    """Create the Atlas Search lexical index on agent_memories.content.

    Paired with the vector index above via `$rankFusion` for hybrid memory
    retrieval. Indexes `content` (text) plus `user_id` and `namespace`
    (token) so the lexical leg of the fusion can pre-filter at mongot level.

    Returns True if queryable, False otherwise.
    """
    collection = db[COLLECTION_AGENT_MEMORIES]
    try:
        cursor = await collection.list_search_indexes()
        existing = [idx.get("name", "") async for idx in cursor]
        if AGENT_MEMORY_LEXICAL_INDEX_NAME in existing:
            logger.debug(f"Agent memory lexical index '{AGENT_MEMORY_LEXICAL_INDEX_NAME}' already exists")
            return await _wait_for_search_index_ready(collection, AGENT_MEMORY_LEXICAL_INDEX_NAME)

        search_index = SearchIndexModel(
            definition={
                "mappings": {
                    "dynamic": False,
                    "fields": {
                        AgentMemoryKeys.CONTENT: {
                            "type": "string",
                            "analyzer": "lucene.standard",
                        },
                        AgentMemoryKeys.USER_ID: {"type": "token"},
                        AgentMemoryKeys.NAMESPACE: {"type": "token"},
                    },
                }
            },
            name=AGENT_MEMORY_LEXICAL_INDEX_NAME,
            type="search",
        )
        await collection.create_search_index(search_index)
        logger.info(f"Created agent memory lexical index: {AGENT_MEMORY_LEXICAL_INDEX_NAME}")
        return await _wait_for_search_index_ready(collection, AGENT_MEMORY_LEXICAL_INDEX_NAME)
    except Exception as e:
        logger.warning(
            f"Could not create agent memory lexical index '{AGENT_MEMORY_LEXICAL_INDEX_NAME}': {e}. "
            f"Hybrid memory retrieval via $rankFusion will be unavailable until this index exists."
        )
        return False


# Search/vector (mongot) indexes per collection. drop_indexes() only removes
# btree indexes, so these would otherwise survive a "drop all" and silently leave
# stale mongot definitions behind. Kept as a map so drop_all_indexes can tear
# them down too. Names come from the same constants the create-side helpers use.
_SEARCH_INDEXES_BY_COLLECTION: dict[str, list[str]] = {
    COLLECTION_RAG_CHUNKS: [RAG_VECTOR_INDEX_NAME, RAG_VECTOR_INDEX_NAME_LEGACY, RAG_LEXICAL_INDEX_NAME],
    COLLECTION_DISCUSSIONS: [DISCUSSION_VECTOR_INDEX_NAME],
    COLLECTION_AGENT_MEMORIES: [AGENT_MEMORY_VECTOR_INDEX_NAME, AGENT_MEMORY_LEXICAL_INDEX_NAME],
}


async def drop_all_indexes(db: AsyncDatabase) -> None:
    """
    Drop all non-_id indexes, INCLUDING mongot search/vector indexes. Use with caution.

    drop_indexes() alone only removes btree indexes; the search/vector indexes
    created by the _ensure_*_index helpers live in mongot and must be dropped
    separately via drop_search_index. We do both here so "drop all" really means
    all, not "all the btree ones".

    Args:
        db: AsyncDatabase instance
    """
    for collection_name in INDEXES.keys():
        collection = db[collection_name]
        await collection.drop_indexes()
        logger.warning(f"Dropped all btree indexes for collection: {collection_name}")

    # Drop mongot search/vector indexes best-effort: list what actually exists
    # (names may be absent on a fresh DB or when mongot is unavailable) and drop
    # only those, per-index guarded so one failure cannot abort the rest. This
    # mirrors the best-effort posture of the create-side helpers.
    for collection_name, index_names in _SEARCH_INDEXES_BY_COLLECTION.items():
        collection = db[collection_name]
        try:
            cursor = await collection.list_search_indexes()
            existing = {idx["name"] async for idx in cursor}
        except Exception as e:
            logger.warning(f"Could not list search indexes for {collection_name} (mongot unavailable?): {e}")
            continue
        for index_name in index_names:
            if index_name not in existing:
                continue
            try:
                await collection.drop_search_index(index_name)
                logger.warning(f"Dropped search/vector index '{index_name}' on collection: {collection_name}")
            except Exception as e:
                logger.warning(f"Failed to drop search/vector index '{index_name}' on {collection_name}: {e}")
