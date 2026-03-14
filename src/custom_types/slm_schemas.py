"""
SLM (Small Language Model) Type Definitions

Schemas for message classification and filtering using local SLM inference.
Used by the message pre-filter node to reduce expensive LLM API calls.
"""

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class MessageClassification(StrEnum):
    """Classification categories for WhatsApp messages."""

    KEEP = "KEEP"  # High value - technical discussions, questions, announcements
    FILTER = "FILTER"  # Low value - spam, greetings, emoji-only, off-topic
    UNCERTAIN = "UNCERTAIN"  # Ambiguous - needs LLM review (fail-safe)


class MessageClassificationResult(BaseModel):
    """Result of classifying a single message."""

    classification: MessageClassification = Field(description="The classification category")
    reason: str = Field(default="", max_length=100, description="Brief reason for classification (max 100 chars)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score (0-1)")
    message_id: str | None = Field(default=None, description="ID of the classified message")


class MessageForClassification(BaseModel):
    """Input structure for message classification."""

    message_id: str = Field(description="Unique message identifier")
    text: str = Field(description="Message text content")
    sender_name: str | None = Field(default=None, description="Sender display name")
    previous_message_summary: str | None = Field(default=None, max_length=200, description="Brief context from previous message(s)")


class BatchClassificationResult(BaseModel):
    """Result of classifying a batch of messages."""

    results: list[MessageClassificationResult] = Field(default_factory=list, description="Classification results for each message")
    total_messages: int = Field(default=0, description="Total messages processed")
    kept_count: int = Field(default=0, description="Messages classified as KEEP")
    filtered_count: int = Field(default=0, description="Messages classified as FILTER")
    uncertain_count: int = Field(default=0, description="Messages classified as UNCERTAIN")
    processing_time_ms: float = Field(default=0.0, description="Total processing time in milliseconds")
    slm_available: bool = Field(default=True, description="Whether SLM was available for classification")


class SLMFilterStats(BaseModel):
    """Statistics from SLM filtering stage."""

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = Field(default=False, description="Whether SLM filtering was enabled")
    total_input_messages: int = Field(default=0, description="Messages received for filtering")
    total_output_messages: int = Field(default=0, description="Messages after filtering (KEEP + UNCERTAIN)")
    kept: int = Field(default=0, description="Messages classified as KEEP")
    filtered: int = Field(default=0, description="Messages classified as FILTER")
    uncertain: int = Field(default=0, description="Messages classified as UNCERTAIN")
    filter_rate: float = Field(default=0.0, description="Percentage of messages filtered (0-100)")
    slm_available: bool = Field(default=True, description="Whether SLM service was available")
    fallback_used: bool = Field(default=False, description="Whether filtering was skipped due to SLM unavailability")
    processing_time_ms: float = Field(default=0.0, description="Total SLM processing time in milliseconds")
    model_used: str | None = Field(default=None, description="Model used for classification")

    def calculate_filter_rate(self) -> float:
        """Calculate and update filter rate."""
        if self.total_input_messages > 0:
            self.filter_rate = (self.filtered / self.total_input_messages) * 100
        return self.filter_rate


class SLMHealthStatus(BaseModel):
    """Health status of the SLM service."""

    model_config = ConfigDict(protected_namespaces=())

    available: bool = Field(default=False, description="Whether the SLM service is available")
    model_loaded: bool = Field(default=False, description="Whether the target model is loaded")
    model_name: str | None = Field(default=None, description="Name of the loaded model")
    response_time_ms: float | None = Field(default=None, description="Health check response time in milliseconds")
    error_message: str | None = Field(default=None, description="Error message if unhealthy")
