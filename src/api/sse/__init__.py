"""
SSE (Server-Sent Events) Streaming for LangGraph Workflows

Real-time progress streaming from LangGraph workflows to the frontend.

Structure:
- Types in custom_types/sse_events.py (centralized)
- stream.py: ProgressQueue for async event streaming
- node_decorators.py: Decorators for graph nodes

Usage:
    from api.sse import (
        ProgressQueue,
        get_progress_queue,
        create_stage_event,
        STAGE_EXTRACT,
        with_progress,
        with_logging,
    )
"""

# Types and constants (from centralized custom_types)
from custom_types.sse_events import (
    # Stage constants (per-chat)
    STAGE_EXTRACT,
    STAGE_PREPROCESS,
    STAGE_TRANSLATE,
    STAGE_SEPARATE,
    STAGE_RANK,
    STAGE_GENERATE,
    STAGE_ENRICH,
    STAGE_TRANSLATE_FINAL,
    # Consolidation stages
    STAGE_CONSOLIDATE_SETUP,
    STAGE_CONSOLIDATE_DISCUSSIONS,
    STAGE_CONSOLIDATE_RANK,
    STAGE_CONSOLIDATE_GENERATE,
    STAGE_CONSOLIDATE_ENRICH,
    STAGE_CONSOLIDATE_TRANSLATE,
    # Type definitions
    EventType,
    StageStatus,
    # Data classes
    ProgressEvent,
    # Helper functions
    create_stage_event,
)

# Progress queue management
from .progress_queue import (
    ProgressQueue,
    get_progress_queue,
    remove_progress_queue,
)

# Node decorators
from .node_decorators import (
    with_cache_check,
    with_progress,
    with_logging,
    pipeline_node,
)

__all__ = [
    # Stage constants (per-chat)
    "STAGE_EXTRACT",
    "STAGE_PREPROCESS",
    "STAGE_TRANSLATE",
    "STAGE_SEPARATE",
    "STAGE_RANK",
    "STAGE_GENERATE",
    "STAGE_ENRICH",
    "STAGE_TRANSLATE_FINAL",
    # Consolidation stages
    "STAGE_CONSOLIDATE_SETUP",
    "STAGE_CONSOLIDATE_DISCUSSIONS",
    "STAGE_CONSOLIDATE_RANK",
    "STAGE_CONSOLIDATE_GENERATE",
    "STAGE_CONSOLIDATE_ENRICH",
    "STAGE_CONSOLIDATE_TRANSLATE",
    # Type definitions
    "EventType",
    "StageStatus",
    # Data classes
    "ProgressEvent",
    # Helper functions
    "create_stage_event",
    # Stream management
    "ProgressQueue",
    "get_progress_queue",
    "remove_progress_queue",
    # Node decorators
    "with_cache_check",
    "with_progress",
    "with_logging",
    "pipeline_node",
]
