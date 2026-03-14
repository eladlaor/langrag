"""
Batch API Data Types

Provider-agnostic data types for batch API operations.
Used by all batch API provider implementations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class BatchStatus(StrEnum):
    """Status of a batch job across all providers."""

    VALIDATING = "validating"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class BatchRequest:
    """
    A single request within a batch.

    Provider-agnostic representation that gets translated
    to provider-specific format by each implementation.

    Attributes:
        custom_id: Unique identifier for this request (for result correlation)
        messages: List of message dicts with 'role' and 'content'
        model: Model to use (if different from provider default)
        temperature: Sampling temperature
        response_format: Optional structured output format
        metadata: Additional provider-specific options
    """

    custom_id: str
    messages: list[dict[str, str]]
    model: str | None = None
    temperature: float = 0.7
    response_format: dict | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchRequestResult:
    """
    Result for a single request within a batch.

    Attributes:
        custom_id: Identifier matching the original request
        success: Whether this request succeeded
        content: Response content (if successful)
        error: Error message (if failed)
        usage: Token usage stats (if available)
    """

    custom_id: str
    success: bool
    content: str | None = None
    error: str | None = None
    usage: dict[str, int] | None = None


@dataclass
class BatchResult:
    """
    Complete result of a batch operation.

    Attributes:
        batch_id: Provider's batch identifier
        status: Final status of the batch
        results: Individual request results
        total_requests: Total number of requests submitted
        completed_requests: Number of successfully completed requests
        failed_requests: Number of failed requests
        created_at: When the batch was created
        completed_at: When the batch finished (if completed)
        metadata: Additional provider-specific info
    """

    batch_id: str
    status: BatchStatus
    results: list[BatchRequestResult]
    total_requests: int
    completed_requests: int
    failed_requests: int
    created_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchInfo:
    """
    Information about a submitted batch (before completion).

    Returned immediately after batch submission.

    Attributes:
        batch_id: Provider's batch identifier
        file_id: Uploaded file identifier (if applicable)
        status: Current status
        total_requests: Number of requests in batch
        created_at: When the batch was created
    """

    batch_id: str
    file_id: str | None = None
    status: BatchStatus = BatchStatus.VALIDATING
    total_requests: int = 0
    created_at: datetime | None = None
