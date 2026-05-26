"""
Database Schemas

Pydantic models for MongoDB documents.
These models define the structure of documents stored in MongoDB collections.
"""

from datetime import datetime, UTC
from typing import Any
from pydantic import BaseModel, Field
from constants import (
    CURRENT_SCHEMA_VERSION_DISCUSSION,
    CURRENT_SCHEMA_VERSION_MESSAGE,
    CURRENT_SCHEMA_VERSION_NEWSLETTER,
    CURRENT_SCHEMA_VERSION_RAG_CHUNK,
    CURRENT_SCHEMA_VERSION_RUN,
    RunStatus,
)


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

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_DISCUSSION, description="Document schema version for lazy migration")
    discussion_id: str = Field(..., description="Unique identifier for the discussion")
    run_id: str = Field(..., description="Associated pipeline run ID")
    chat_name: str = Field(..., description="Source chat name")
    title: str = Field(..., description="Discussion title")
    nutshell: str = Field(..., description="Brief summary of the discussion")
    message_ids: list[str] = Field(..., description="List of message IDs in this discussion")
    message_count: int = Field(..., description="Number of messages in the discussion")
    ranking_score: float = Field(default=0.0, description="Relevance ranking score (0-10)")
    first_message_timestamp: int | None = Field(None, description="Timestamp of first message")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")


class MessageDocument(BaseModel):
    """Schema for raw message records."""

    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION_MESSAGE, description="Document schema version for lazy migration")
    message_id: str = Field(..., description="Unique identifier (Matrix event ID)")
    discussion_id: str = Field(..., description="Associated discussion ID")
    chat_name: str = Field(..., description="Source chat name")
    sender: str = Field(..., description="Sender identifier")
    content: str = Field(..., description="Original message content")
    timestamp: int = Field(..., description="Message timestamp (milliseconds)")
    translated_content: str | None = Field(None, description="Translated content if available")
    replies_to: str | None = Field(None, description="ID of message this replies to")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")


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
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source-specific metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation timestamp")


class AnalyticsDocument(BaseModel):
    """Schema for analytics events."""

    event_type: str = Field(..., description="Type of event")
    date: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Event date")
    data_source: str | None = Field(None, description="Data source if applicable")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Event metrics")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
