"""
Database Schemas

Pydantic models for MongoDB documents.
These models define the structure of documents stored in MongoDB collections.
"""

from datetime import datetime, UTC
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field
from constants import (
    CURRENT_SCHEMA_VERSION_ACCESS_REQUEST,
    CURRENT_SCHEMA_VERSION_AGENT_MEMORY,
    CURRENT_SCHEMA_VERSION_AGENT_SESSION,
    CURRENT_SCHEMA_VERSION_DISCUSSION,
    CURRENT_SCHEMA_VERSION_MESSAGE,
    CURRENT_SCHEMA_VERSION_NEWSLETTER,
    CURRENT_SCHEMA_VERSION_RAG_CHUNK,
    CURRENT_SCHEMA_VERSION_RUN,
    CURRENT_SCHEMA_VERSION_USER,
    CURRENT_SCHEMA_VERSION_USER_API_KEY,
    RunStatus,
)


class UserRole(StrEnum):
    """Roles assignable to a `users` document.

    Tier 1 ships with `ADMIN` only. `VIEWER` is reserved for future tiers
    (community members) so authorization checks can branch without a schema
    migration when that work begins.
    """

    ADMIN = "admin"
    VIEWER = "viewer"


class AuthProvider(StrEnum):
    """How a `users` account authenticates.

    PASSWORD: email+password only. GOOGLE: Google OAuth/OIDC only.
    PASSWORD_AND_GOOGLE: both linked to the same email identity.
    """

    PASSWORD = "password"
    GOOGLE = "google"
    PASSWORD_AND_GOOGLE = "password_and_google"


class AccessRequestStatus(StrEnum):
    """Lifecycle status of an `access_requests` document."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemoryNamespace(StrEnum):
    """Namespaces for the long-term `agent_memories` store.

    - `SEMANTIC`: durable facts about the user / their communities / their
      preferences (e.g., "user prefers Hebrew newsletters").
    - `EPISODIC`: timestamped events (e.g., "on 2026-05-20 user rejected
      the first draft of the MCP Israel newsletter"). TTL'd by default.
    - `PROCEDURAL`: learned preferences / patterns inferred over multiple
      sessions (e.g., "always default to 5 discussions, not 10").
    """

    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"


class RunDocument(BaseModel):
    """Schema for pipeline run records."""

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_RUN, description="Document schema version for lazy migration")
    run_id: str = Field(..., description="Unique identifier for the run")
    data_source_name: str = Field(..., description="Data source (e.g., 'langtalks', 'mcp_israel')")
    chat_names: list[str] = Field(..., description="List of chat names included in the run")
    start_date: str = Field(..., description="Start date for message extraction (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date for message extraction (YYYY-MM-DD)")
    config: dict[str, Any] = Field(default_factory=dict, description="Run configuration options")
    status: str = Field(default=RunStatus.PENDING, description="Run status: pending, running, completed, failed")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    started_at: datetime | None = Field(None, description="Start timestamp")
    completed_at: datetime | None = Field(None, description="Completion timestamp")
    error: str | None = Field(None, description="Error message if failed")
    output_path: str | None = Field(None, description="Path to output files")
    stages: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Stage progress")


class DiscussionDocument(BaseModel):
    """Schema for discussion records."""

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_DISCUSSION, description="Document schema version (offline-migrated; see constants)")
    discussion_id: str = Field(..., description="Unique identifier for the discussion")
    run_id: str = Field(..., description="Associated pipeline run ID")
    chat_name: str = Field(..., description="Source chat name (exact WhatsApp group name)")
    data_source_name: str | None = Field(None, description="Community key (e.g. 'langtalks'). Filterable; enables community-scoped retrieval over discussions.")
    title: str = Field(..., description="Discussion title")
    nutshell: str = Field(..., description="Brief summary of the discussion")
    # Embed-vs-reference decision: message_ids is an embedded array, NOT a
    # reference collection. Bound: a single discussion holds at most a few
    # hundred WhatsApp message IDs (~30 bytes each), well under MongoDB's 16MB
    # document limit. Fallback if that ever breaks (e.g. mega-threads): stop
    # embedding and look messages up by {run_id, chat_name} range, or bucket
    # the ids. Embedding is correct here because the ids are always read
    # together with the discussion and never independently queried.
    message_ids: list[str] = Field(..., description="List of message IDs in this discussion")
    message_count: int = Field(..., description="Number of messages in the discussion")
    ranking_score: float = Field(default=0.0, description="Relevance ranking score (0-10)")
    first_message_timestamp: int | None = Field(None, description="Timestamp of first message")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    # Semantic-search fields. Large (a 1536-float embedding is ~6KB BSON), so
    # read/list paths MUST project these out (see DiscussionsRepository); they
    # are only needed by the vector-search index and similarity queries.
    embedding: list[float] | None = Field(None, description="Embedding vector for semantic search")
    embedding_model: str | None = Field(None, description="Model that produced the embedding")
    embedding_timestamp: datetime | None = Field(None, description="When the embedding was generated")


class RawDiscussionDocument(BaseModel):
    """Schema for the `raw_discussions` collection.

    The truly raw, per-chat discussions as produced by `separate_discussions`
    (the LLM segmentation of a single group's messages into threads) — BEFORE
    ranking and BEFORE cross-chat merge. These were previously JSON-only working
    state; persisting them gives an auditable, community-scoped record of the
    pre-merge segmentation. Distinct from the `discussions` collection, which
    holds the per-chat *ranked* discussions.
    """

    schema_version: int = Field(default=1, description="Document schema version")
    raw_discussion_id: str = Field(..., description="Unique key: f'{run_id}_{chat_name}_{local_id}'")
    run_id: str = Field(..., description="Owning pipeline run ID")
    chat_name: str = Field(..., description="Exact source WhatsApp group name")
    data_source_name: str | None = Field(None, description="Community key (e.g. 'langtalks'); filterable.")
    local_id: str = Field(..., description="The per-run discussion id assigned at segmentation (e.g. 'discussion_1')")
    title: str | None = Field(None, description="LLM-generated discussion title")
    nutshell: str | None = Field(None, description="LLM-generated brief summary")
    message_ids: list[str] = Field(default_factory=list, description="Message ids in this raw discussion (when resolvable)")
    message_count: int = Field(default=0, description="Number of messages in the raw discussion")
    first_message_timestamp: int | None = Field(None, description="Timestamp of first message")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")


class MessageDocument(BaseModel):
    """Schema for the `messages` collection.

    A single message document is written in two passes against the same
    `message_id` key (see RunTracker.store_raw_messages then store_messages):

      1. RAW pass (post-extraction): sets `content` and `data_source_name`.
      2. TRANSLATED pass (post-preprocessing): upserts the translated/enriched
         fields (`content_translated`, `is_translated`, `urls`, `mentions`,
         `word_count`, `short_id`, `replies_to`).

    This model documents the UNION of both passes as actually stored, so it is
    the truthful schema for the collection. Fields not yet written by a given
    pass are optional. `extra="allow"` keeps the model non-lossy if a writer
    adds a field before this model is updated, while `model_validate` still
    catches type errors on the declared fields.

    NOTE on `discussion_id`: the extraction/preprocessing writers do NOT set it
    — a message references its discussion only through the discussion's embedded
    `message_ids` array (see DiscussionDocument). It is optional here and set
    only by the legacy MessagesRepository.create_message path.
    """

    model_config = {"extra": "allow"}

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_MESSAGE, description="Document schema version for lazy migration")
    message_id: str = Field(..., description="Unique document key: f'{run_id}_msg_{matrix_event_id}'")
    run_id: str = Field(..., description="Owning pipeline run ID")
    chat_name: str = Field(..., description="Source chat name")
    sender: str = Field(..., description="Sender identifier")
    timestamp: int | None = Field(None, description="Message timestamp (milliseconds)")
    data_source_name: str | None = Field(None, description="Data source key (e.g., 'langtalks'); set on the raw pass")
    discussion_id: str | None = Field(None, description="Associated discussion ID; unset by the extraction path (messages are referenced via DiscussionDocument.message_ids)")

    # Matrix linkage / alternate identifiers
    matrix_event_id: str | None = Field(None, description="Original Matrix event ID (set on the translated pass)")
    short_id: str | None = Field(None, description="Pipeline short_id (set on the translated pass)")

    # RAW-pass content
    content: str | None = Field(None, description="Original message content (raw pass)")

    # TRANSLATED-pass enriched content
    content_translated: str | None = Field(None, description="Translated/preprocessed content (translated pass)")
    is_translated: bool = Field(default=False, description="Whether the translated pass has run for this document")
    urls: list[str] = Field(default_factory=list, description="Extracted URLs (translated pass)")
    mentions: list[str] = Field(default_factory=list, description="Extracted @-mentions (translated pass)")
    word_count: int | None = Field(None, description="Token-ish word count of translated content")
    replies_to: str | None = Field(None, description="ID of message this replies to")

    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp (set on first insert)")
    updated_at: datetime | None = Field(None, description="Last upsert timestamp (set on the translated pass)")


class CacheDocument(BaseModel):
    """Schema for cache entries."""

    cache_key: str = Field(..., description="SHA256 hash cache key")
    operation_type: str = Field(..., description="Type of cached operation")
    input_hash: str = Field(..., description="Short hash of input for debugging")
    response_data: Any = Field(..., description="Cached response data")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    expires_at: datetime = Field(..., description="Expiration timestamp (TTL)")


class NewsletterDocument(BaseModel):
    """Schema for persisted newsletter records.

    The newsletters repository writes documents as dicts (the versioned content
    is dynamic and not easily modeled as a closed Pydantic schema). This class
    documents the canonical shape and carries the schema_version stamp.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_NEWSLETTER, description="Document schema version for lazy migration")
    newsletter_id: str = Field(..., description="Unique newsletter identifier")
    run_id: str = Field(..., description="Associated pipeline run ID")
    newsletter_type: str = Field(..., description="'per_chat' or 'consolidated'")
    data_source_name: str = Field(..., description="Source community key")
    chat_name: str | None = Field(None, description="Source chat name (None for consolidated)")
    start_date: str = Field(..., description="Coverage start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Coverage end date (YYYY-MM-DD)")
    summary_format: str = Field(..., description="Newsletter format identifier")
    desired_language: str = Field(..., description="Target language")
    status: str = Field(..., description="Newsletter status (draft/enriched/completed)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Last update timestamp")


class RAGChunkDocument(BaseModel):
    """Schema for embedded content chunks in the rag_chunks collection.

    The ingestion pipeline writes chunks as dicts (embedding is a BSON Binary,
    metadata is open-ended). This class documents the canonical shape and
    carries the schema_version stamp.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_RAG_CHUNK, description="Document schema version for lazy migration")
    chunk_id: str = Field(..., description="Unique chunk identifier")
    content_source: str = Field(..., description="Source type (podcast/newsletter/chat_message)")
    source_id: str = Field(..., description="Identifier of the parent source")
    source_title: str = Field(..., description="Human-readable source title")
    content: str = Field(..., description="Chunk text content")
    embedding_model: str = Field(..., description="Embedding model identifier used at ingest time")
    chunk_index: int = Field(..., description="0-based chunk index within source")
    source_date_start: datetime = Field(..., description="Inclusive lower bound of source content date range")
    source_date_end: datetime = Field(..., description="Inclusive upper bound of source content date range")
    data_source_name: str | None = Field(None, description="Community key (e.g. 'langtalks'), promoted to top-level so it is filterable in the search indexes. None for podcast chunks (not community-scoped).")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source-specific metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")


class AnalyticsDocument(BaseModel):
    """Schema for analytics events."""

    event_type: str = Field(..., description="Type of event")
    date: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Event date")
    data_source: str | None = Field(None, description="Data source if applicable")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Event metrics")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


# ============================================================================
# Agentic chatbot layer (v1.13.0+)
# See knowledge/plans/AGENTIC_CHATBOT_LAYER.md for the full design.
# ============================================================================


class UserQuotas(BaseModel):
    """Per-user daily quotas for the agent runtime.

    Chat-token-scoped: the dominant cost driver is the conversational
    context an admin streams INTO the agent (WhatsApp message excerpts the
    admin asks the agent to reason over), not the newsletter pipeline itself.
    """

    daily_chat_input_tokens: int = Field(default=300_000, description="Cap on tokens sent into the agent per UTC day")
    daily_chat_output_tokens: int = Field(default=60_000, description="Cap on agent reply tokens per UTC day")
    daily_memory_tokens: int = Field(default=100_000, description="Cap on tokens consumed by the memory extractor + summarizer per UTC day")
    daily_newsletter_runs: int = Field(default=10, description="Soft cap on newsletter generations kicked off by the agent per UTC day")


class UserDailyUsage(BaseModel):
    """Rolling per-UTC-day usage counters, persisted on the user document.

    Updated by `check_budget_node` at the end of every agent turn so quota
    enforcement survives process restarts. Reset implicitly by comparing
    `date` against the current UTC day.
    """

    date: str = Field(..., description="UTC date the counters belong to, formatted YYYY-MM-DD")
    chat_input_tokens: int = Field(default=0)
    chat_output_tokens: int = Field(default=0)
    memory_tokens: int = Field(default=0)
    newsletter_runs: int = Field(default=0)


class RagPreferences(BaseModel):
    """Per-user RAG retrieval preferences, persisted on the user document.

    Optional sub-document: when absent, retrieval falls back to the server
    config defaults (`rag.mmr_lambda`, `rag.enable_mmr_diversity`) under the
    project-wide lazy-migration regime, so no batch migration is required.
    """

    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0, description="MMR relevance/diversity weight (0-1). Higher favors relevance, lower favors diversity.")
    enable_mmr_diversity: bool = Field(default=True, description="When false, retrieval skips MMR and returns fused top-k by relevance.")


class UserDocument(BaseModel):
    """Schema for admin-tier user records.

    Tier 1 (admins only) is the launch scope; the schema accommodates Tier 2
    (community members) without a migration by virtue of the `role` field.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_USER, description="Document schema version for lazy migration")
    user_id: str = Field(..., description="Application-level user identifier (uuid4)")
    email: str = Field(..., description="Unique email (indexed)")
    role: UserRole = Field(default=UserRole.ADMIN, description="User role for authorization branching")
    password_hash: str | None = Field(default=None, description="argon2id PHC hash of the account password; None for accounts without a login (legacy/agent-only)")
    session_epoch: int = Field(default=0, description="Server-side session revocation counter; bumped on password reset to invalidate live sessions")
    disabled: bool = Field(default=False, description="When True the account cannot log in")
    auth_provider: AuthProvider = Field(default=AuthProvider.PASSWORD, description="How this account authenticates (password, google, or both)")
    google_sub: str | None = Field(default=None, description="Google OIDC subject identifier (never the email); set when the account is linked to Google. Sparse-unique-indexed.")
    communities: list[str] = Field(default_factory=list, description="Community keys this user is authorized to act on")
    preferences: dict[str, Any] = Field(default_factory=dict, description="Free-form preferences (language, default community, etc.)")
    quotas: UserQuotas = Field(default_factory=UserQuotas, description="Daily quotas enforced by check_budget_node")
    rag_preferences: RagPreferences | None = Field(default=None, description="Saved per-user RAG MMR setting; None means use the config default (lazy migration, no batch backfill)")
    daily_usage: UserDailyUsage | None = Field(None, description="Rolling per-UTC-day usage counters")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    last_seen_at: datetime | None = Field(None, description="Last time this user authenticated against the agent API")


class AccessRequestDocument(BaseModel):
    """Schema for a self-signup access request.

    Persisted when a non-allowlisted user submits the contact form asking for
    access. Reviewed by an admin out of band; no account is created here.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_ACCESS_REQUEST, description="Document schema version for lazy migration")
    request_id: str = Field(..., description="Application-level request identifier (uuid4)")
    email: str = Field(..., description="Normalized email of the requester")
    name: str | None = Field(default=None, description="Optional display name supplied by the requester")
    message: str | None = Field(default=None, description="Optional free-text message from the requester")
    requested_provider: str | None = Field(default=None, description="AuthProvider value the requester attempted (password/google), if known")
    status: AccessRequestStatus = Field(default=AccessRequestStatus.PENDING, description="Review status")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Submission timestamp")
    reviewed_at: datetime | None = Field(default=None, description="When an admin reviewed this request")
    reviewed_by: str | None = Field(default=None, description="user_id of the reviewing admin")


class UserApiKeyDocument(BaseModel):
    """Schema for user-scoped API keys.

    Parallel to the existing `rag_api_keys` collection, kept separate so the
    public RAG path's auth surface remains unchanged. Each key is owned by
    exactly one `users` row and inherits that user's communities / quotas at
    resolution time.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_USER_API_KEY, description="Document schema version for lazy migration")
    key_id: str = Field(..., description="Stable identifier for rotation / revocation (uuid4)")
    key_hash: str = Field(..., description="HMAC-SHA-256 hash of the plaintext key (plaintext is shown only at issue time)")
    user_id: str = Field(..., description="Owning user_id (foreign reference to users.user_id)")
    name: str = Field(default="", description="Human-readable label")
    scopes: list[str] = Field(default_factory=list, description="Scopes this key may exercise (e.g., 'agent:chat')")
    enabled: bool = Field(default=True, description="Disabled keys are rejected at auth time")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    last_used_at: datetime | None = Field(None, description="Best-effort last-used timestamp")
    expires_at: datetime | None = Field(None, description="Optional hard expiry")


class AgentSessionDocument(BaseModel):
    """Schema for an agent chat session.

    `session_id` == LangGraph `thread_id`, so a session row is the durable
    metadata twin of a checkpointer thread. Sliding TTL: `expires_at` is
    pushed forward on every turn; abandoned sessions self-clean.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_AGENT_SESSION, description="Document schema version for lazy migration")
    session_id: str = Field(..., description="Session identifier == LangGraph thread_id (uuid4)")
    user_id: str = Field(..., description="Owning user_id (foreign reference to users.user_id)")
    title: str = Field(default="", description="Auto-summarized one-line title for session-browser UIs")
    community_context: str | None = Field(None, description="Default community key for this session, if any")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    last_message_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Last activity timestamp")
    message_count: int = Field(default=0, description="Cumulative count of user + assistant messages")
    cost_so_far: dict[str, Any] = Field(default_factory=dict, description="Aggregated token / usd usage for the session")
    expires_at: datetime = Field(..., description="Sliding TTL; auto-cleaned by MongoDB when idle")


class AgentMemoryDocument(BaseModel):
    """Schema for a single long-term memory item.

    Embeddings are stored as BSON Binary (subtype 9) — matching the
    `rag_chunks` convention — so Atlas Vector Search can serve them
    directly without conversion at query time.
    """

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_AGENT_MEMORY, description="Document schema version for lazy migration")
    memory_id: str = Field(..., description="Memory identifier (uuid4)")
    user_id: str = Field(..., description="Owning user_id; pre-filtered on every retrieval")
    namespace: MemoryNamespace = Field(..., description="Memory tier: semantic / episodic / procedural")
    content: str = Field(..., description="Plain-text memory content the LLM produced or read")
    embedding: Any = Field(..., description="BSON Binary vector (same dims as rag_chunks)")
    embedding_model: str = Field(..., description="Embedding model identifier used at write time")
    importance: float = Field(default=0.5, description="Extractor-assigned importance score in [0, 1]")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Free-form metadata (source_message_id, community_key, ...)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")
    last_accessed_at: datetime | None = Field(None, description="Last time this memory was returned by a retriever query")
    access_count: int = Field(default=0, description="How many times this memory has been retrieved")
    expires_at: datetime | None = Field(None, description="Sparse: set only on episodic entries; TTL cleans them up")
