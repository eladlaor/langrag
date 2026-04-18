"""
Consolidated imports for graph modules.

This module provides grouped imports to simplify graph file headers
and make dependencies explicit. Use this to reduce import clutter
in graph implementation files.

Usage:
    from graphs.imports import (
        # LangGraph core
        StateGraph, START, END, AsyncSqliteSaver, RunnableConfig,
        # Progress tracking
        with_cache_check, with_progress, with_logging,
        STAGE_EXTRACT, STAGE_PREPROCESS, ...
        # Observability
        with_metrics, langfuse_span, extract_trace_context,
        # etc.
    )
"""

# LangGraph core
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.runnables import RunnableConfig

# Graph states
from graphs.single_chat_analyzer.state import SingleChatState
from graphs.subgraphs.state import (
    DiscussionRankerState,
    LinkEnricherState,
    create_ranker_state_from_single_chat,
    create_enricher_state_from_single_chat,
)

# Subgraphs
from graphs.subgraphs.discussions_ranker import discussions_ranker_graph
from graphs.subgraphs.link_enricher import link_enricher_graph

# Progress tracking
from api.sse import (
    create_stage_event,
    get_progress_queue,
    with_cache_check,
    with_progress,
    with_logging,
    STAGE_EXTRACT,
    STAGE_PREPROCESS,
    STAGE_TRANSLATE,
    STAGE_SEPARATE,
    STAGE_RANK,
    STAGE_GENERATE,
    STAGE_ENRICH,
    STAGE_TRANSLATE_FINAL,
)

# Observability
from observability.metrics import with_metrics
from observability import langfuse_span, extract_trace_context, score_newsletter_structure
from observability.decorators import with_trace_span

# Business logic factories
from core.ingestion.extractors.beeper import RawDataExtractorBeeper
from core.ingestion.preprocessors.factory import DataProcessorFactory
from core.generation.generators.factory import ContentGeneratorFactory

# Database
from db.run_tracker import get_tracker
from db.node_persistence import NodePersistence, generate_newsletter_id
from db.persistence_policy import PersistencePolicy, handle_persistence_error

# Constants
from constants import (
    DataSources,
    PreprocessingOperations,
    ContentGenerationOperations,
    NewsletterVersionType,
    NewsletterType,
    DiscussionCategory,
    RepetitionScore,
    SimilarityThreshold,
)

# Config
from config import get_settings

# Re-export all for clean imports
__all__ = [
    # LangGraph
    "StateGraph",
    "START",
    "END",
    "AsyncSqliteSaver",
    "RunnableConfig",
    # States
    "SingleChatState",
    "DiscussionRankerState",
    "LinkEnricherState",
    "create_ranker_state_from_single_chat",
    "create_enricher_state_from_single_chat",
    # Subgraphs
    "discussions_ranker_graph",
    "link_enricher_graph",
    # Progress
    "create_stage_event",
    "get_progress_queue",
    "with_cache_check",
    "with_progress",
    "with_logging",
    "STAGE_EXTRACT",
    "STAGE_PREPROCESS",
    "STAGE_TRANSLATE",
    "STAGE_SEPARATE",
    "STAGE_RANK",
    "STAGE_GENERATE",
    "STAGE_ENRICH",
    "STAGE_TRANSLATE_FINAL",
    # Observability
    "with_metrics",
    "langfuse_span",
    "extract_trace_context",
    "score_newsletter_structure",
    "with_trace_span",
    # Business logic
    "RawDataExtractorBeeper",
    "DataProcessorFactory",
    "ContentGeneratorFactory",
    # Database
    "get_tracker",
    "NodePersistence",
    "generate_newsletter_id",
    "PersistencePolicy",
    "handle_persistence_error",
    # Constants
    "DataSources",
    "PreprocessingOperations",
    "ContentGenerationOperations",
    "NewsletterVersionType",
    "NewsletterType",
    "DiscussionCategory",
    "RepetitionScore",
    "SimilarityThreshold",
    # Config
    "get_settings",
]
