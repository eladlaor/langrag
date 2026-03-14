"""
Database Schemas

Pydantic models for MongoDB documents.
These models define the structure of documents stored in MongoDB collections.
"""

from datetime import datetime, UTC
from typing import Any
from pydantic import BaseModel, Field
from constants import RunStatus


class RunDocument(BaseModel):
    """Schema for pipeline run records."""

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


class AnalyticsDocument(BaseModel):
    """Schema for analytics events."""

    event_type: str = Field(..., description="Type of event")
    date: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Event date")
    data_source: str | None = Field(None, description="Data source if applicable")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Event metrics")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
