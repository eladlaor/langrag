"""
SSE (Server-Sent Events) Types for Workflow Progress Streaming

Type definitions and constants for real-time progress events streamed
from LangGraph workflows to the frontend.
"""

from typing import Any, Literal
from dataclasses import dataclass, asdict


# =============================================================================
# STAGE CONSTANTS
# =============================================================================
# These constants match the newsletter generation pipeline stages

# Per-chat stages
STAGE_EXTRACT = "extract_messages"
STAGE_PREPROCESS = "preprocess_messages"
STAGE_TRANSLATE = "translate_messages"
STAGE_SEPARATE = "separate_discussions"
STAGE_RANK = "rank_discussions"
STAGE_GENERATE = "generate_content"
STAGE_ENRICH = "enrich_with_links"
STAGE_TRANSLATE_FINAL = "translate_final_summary"

# Consolidation stages
STAGE_CONSOLIDATE_SETUP = "setup_consolidated_directories"
STAGE_CONSOLIDATE_DISCUSSIONS = "consolidate_discussions"
STAGE_CONSOLIDATE_RANK = "rank_consolidated_discussions"
STAGE_CONSOLIDATE_GENERATE = "generate_consolidated_newsletter"
STAGE_CONSOLIDATE_ENRICH = "enrich_consolidated_newsletter"
STAGE_CONSOLIDATE_TRANSLATE = "translate_consolidated_newsletter"


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

EventType = Literal[
    "workflow_started",
    "chat_started",
    "stage_progress",
    "chat_completed",
    "chat_failed",
    "consolidation_started",
    "consolidation_completed",
    "hitl_selection_ready",  # Phase 1 complete, waiting for user selection
    "workflow_completed",
    "error",
]

StageStatus = Literal["in_progress", "completed", "failed"]


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class ProgressEvent:
    """
    Represents a single progress event in the workflow.

    Attributes:
        event_type: Type of event (workflow_started, stage_progress, etc.)
        timestamp: ISO format timestamp when event was created
        data: Event-specific data payload
    """

    event_type: EventType
    timestamp: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_stage_event(chat_name: str, stage: str, status: StageStatus, message: str, output_file: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Create a standardized stage progress event data structure.

    Args:
        chat_name: Name of the chat being processed
        stage: Stage name (use STAGE_* constants)
        status: Stage status (in_progress, completed, failed)
        message: Human-readable progress message
        output_file: Optional path to output file created by this stage
        metadata: Optional additional metadata (e.g., message_count, duration)

    Returns:
        Event data dict ready for emission
    """
    event_data = {"chat_name": chat_name, "stage": stage, "status": status, "message": message}

    if output_file:
        event_data["output_file"] = output_file

    if metadata:
        event_data["metadata"] = metadata

    return event_data
