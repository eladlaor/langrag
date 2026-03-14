"""
Custom Types Module

Contains all Pydantic models and type definitions used throughout the application:
- api_schemas: Request/response models for FastAPI endpoints
- db_schemas: MongoDB document schemas
- common: Shared base models and utilities
"""

from custom_types.api_schemas import (
    PeriodicNewsletterRequest,
    PeriodicNewsletterResponse,
    NewsletterResult,
    ConsolidatedNewsletterResult,
    RankedDiscussionItem,
    DiscussionSelectionResponse,
    DiscussionSelectionsSaveRequest,
    DiscussionSelectionsSaveResponse,
    Phase2GenerationRequest,
    Phase2GenerationResponse,
)

from custom_types.common import CustomBaseModel

from custom_types.slm_schemas import (
    MessageClassification,
    MessageClassificationResult,
    MessageForClassification,
    BatchClassificationResult,
    SLMFilterStats,
    SLMHealthStatus,
)

__all__ = [
    # API Schemas
    "PeriodicNewsletterRequest",
    "PeriodicNewsletterResponse",
    "NewsletterResult",
    "ConsolidatedNewsletterResult",
    "RankedDiscussionItem",
    "DiscussionSelectionResponse",
    "DiscussionSelectionsSaveRequest",
    "DiscussionSelectionsSaveResponse",
    "Phase2GenerationRequest",
    "Phase2GenerationResponse",
    # Common
    "CustomBaseModel",
    # SLM Schemas
    "MessageClassification",
    "MessageClassificationResult",
    "MessageForClassification",
    "BatchClassificationResult",
    "SLMFilterStats",
    "SLMHealthStatus",
]
