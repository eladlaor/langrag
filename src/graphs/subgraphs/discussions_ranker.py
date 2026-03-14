"""
Discussion Ranker Subgraph - LangGraph 1.0 Implementation

This module implements a LangGraph subgraph that wraps the discussion ranking
business logic from core/retrieval/rankers/.

The ranking logic analyzes separated discussions and produces insights about
which discussions should be featured in which newsletter sections and why.

Architecture:
- Business logic: core/retrieval/rankers/discussion_ranker.py
- Graph wrapper: This file (graphs/subgraphs/discussions_ranker.py)
- LangGraph 1.0+ compatible with RunnableConfig

Current Graph Structure:
- Single-node subgraph: analyze_discussions → END
- Uses modular business logic from core/retrieval

==============================================================================
EXPANSION GUIDE: How to Add New Nodes to This Subgraph
==============================================================================

The current implementation uses a single node with modular helper functions
from core/retrieval/rankers/. This design makes it easy to expand to a
multi-node architecture.

Example 1: Add Pre-Filtering Node
----------------------------------
To add a node that filters low-quality discussions before ranking:

1. Add a filtering function to core/retrieval/rankers/discussion_ranker.py
2. Create a new node function here that calls it
3. Update the graph builder to add the node and edges

Example 2: Add Post-Analysis Validation Node
---------------------------------------------
1. Add validation logic to core/retrieval/rankers/
2. Create validation node function here
3. Update graph: analyze_discussions → validate_rankings → END

Key Principles:
1. Business logic lives in core/retrieval/rankers/
2. Graph nodes are thin wrappers that call the business logic
3. State management handled via LangGraph TypedDict
4. Fail-fast error handling throughout

==============================================================================
"""

import os
import logging

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from graphs.subgraphs.state import DiscussionRankerState
from graphs.state_keys import RankerKeys
from core.retrieval.rankers import (
    load_discussions,
    prepare_discussions_for_llm,
    rank_with_llm,
    enrich_ranking_with_metadata,
    apply_mmr_reranking,
    apply_top_k_categorization,
    save_ranking_result,
)
from core.retrieval.history import load_previous_newsletters
from observability import langfuse_span, extract_trace_context
from config import get_settings
from constants import NodeNames
from custom_types.field_keys import RankingResultKeys


logger = logging.getLogger(__name__)


# ============================================================================
# NODE IMPLEMENTATIONS
# ============================================================================


async def analyze_discussions(state: DiscussionRankerState, config: RunnableConfig | None = None) -> dict:
    """
    Analyze discussions and produce ranking recommendations using LLM.

    This node orchestrates the ranking pipeline by calling modular helper
    functions from core/retrieval/rankers/.

    Output includes:
    - ranked_discussions: All discussions with rank, importance_score, one_liner_summary
    - featured_discussion_ids: List of discussion IDs in top-K (for content generation)
    - brief_mention_items: Pre-formatted one-liners for worth_mentioning section
    - top_k_applied: The top_k value used for categorization

    Args:
        state: DiscussionRankerState with discussions file path and config
        config: LangGraph RunnableConfig for tracing and callbacks

    Fail-Fast Conditions:
    - Input file not found or unreadable
    - JSON parsing errors
    - OpenAI API errors
    - Invalid LLM response format
    - Output directory not writable

    Returns:
        dict: discussions_ranking_file_path
    """
    # Get settings for defaults
    settings = get_settings()

    # Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.DiscussionsRanker.ANALYZE_DISCUSSIONS, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"chat_name": state.get("chat_name"), "discussions_file": state[RankerKeys.SEPARATE_DISCUSSIONS_FILE_PATH], "top_k": state.get(RankerKeys.TOP_K_DISCUSSIONS) or settings.ranking.default_top_k_discussions}, metadata={"source_name": state.get(RankerKeys.DATA_SOURCE_NAME)}) as span:
        logger.info("Node: analyze_discussions - Starting")

        expected_file = state[RankerKeys.EXPECTED_DISCUSSIONS_RANKING_FILE]
        force_refresh = state.get(RankerKeys.FORCE_REFRESH_DISCUSSIONS_RANKING, False)

        # Check for existing file
        if not force_refresh and os.path.exists(expected_file):
            logger.info(f"Using existing discussions ranking file: {expected_file}")
            if span:
                span.update(output={"file_path": expected_file, "reused_existing": True})
            return {RankerKeys.DISCUSSIONS_RANKING_FILE_PATH: expected_file}

        discussions_file = state[RankerKeys.SEPARATE_DISCUSSIONS_FILE_PATH]
        summary_format = state[RankerKeys.SUMMARY_FORMAT]
        top_k = state.get(RankerKeys.TOP_K_DISCUSSIONS) or settings.ranking.default_top_k_discussions

        # Anti-repetition configuration
        previous_newsletters_to_consider = state.get(RankerKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER, settings.ranking.default_previous_newsletters_to_consider)
        data_source_name = state.get(RankerKeys.DATA_SOURCE_NAME)
        current_start_date = state.get(RankerKeys.CURRENT_START_DATE)

        # MMR diversity configuration (from state or config defaults)
        enable_mmr = state.get(RankerKeys.ENABLE_MMR_DIVERSITY)
        if enable_mmr is None:
            enable_mmr = settings.ranking.enable_mmr_diversity
        mmr_lambda = state.get(RankerKeys.MMR_LAMBDA)
        if mmr_lambda is None:
            mmr_lambda = settings.ranking.mmr_lambda

        logger.info(f"Using top_k_discussions={top_k}, enable_mmr={enable_mmr}, " f"mmr_lambda={mmr_lambda:.2f} for categorization")

        # Step 0: Load previous newsletter context for anti-repetition
        previous_context = None
        if previous_newsletters_to_consider > 0 and data_source_name and current_start_date:
            try:
                previous_context = await load_previous_newsletters(
                    data_source_name=data_source_name,
                    current_start_date=current_start_date,
                    max_newsletters=previous_newsletters_to_consider,
                )
                logger.info(f"Anti-repetition: loaded {previous_context.total_editions} " f"previous newsletters for {data_source_name}")
            except Exception as e:
                # Graceful degradation - continue without anti-repetition on error
                logger.warning(f"Failed to load previous newsletters for anti-repetition: {e}")
                previous_context = None
        elif previous_newsletters_to_consider == 0:
            logger.info("Anti-repetition disabled (previous_newsletters_to_consider=0)")
        else:
            logger.debug("Anti-repetition skipped: missing data_source_name or current_start_date")

        # Step 1: Load discussions from file
        discussions = load_discussions(discussions_file)

        if not discussions:
            logger.warning("No discussions found in input file - creating empty ranking")
            ranking_result = {RankingResultKeys.RANKED_DISCUSSIONS: [], RankingResultKeys.FEATURED_DISCUSSION_IDS: [], RankingResultKeys.BRIEF_MENTION_ITEMS: [], RankingResultKeys.TOP_K_APPLIED: top_k, RankingResultKeys.EDITORIAL_NOTES: "No discussions to rank", RankingResultKeys.TOPIC_DIVERSITY: "N/A"}
        else:
            # Step 2: Prepare discussions for LLM analysis
            discussions_summary = prepare_discussions_for_llm(discussions)

            # Extract Langfuse trace context from state (if available)
            trace_id = state.get(RankerKeys.LANGFUSE_TRACE_ID)
            session_id = state.get(RankerKeys.LANGFUSE_SESSION_ID)
            user_id = state.get(RankerKeys.LANGFUSE_USER_ID)

            # Step 3: Rank discussions using LLM (includes one-liner generation and anti-repetition)
            ranking_result = await rank_with_llm(
                discussions_summary,
                summary_format,
                previous_newsletter_context=previous_context,
                # Langfuse trace context for LLM call tracing
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
            )

            # Step 4: Enrich rankings with metadata from original discussions
            ranking_result = enrich_ranking_with_metadata(ranking_result, discussions)

            # Step 5: Apply MMR diversity reranking (if enabled)
            ranking_result = apply_mmr_reranking(ranking_result, discussions, enable_mmr, mmr_lambda)

            # Step 6: Apply top-k categorization and create convenience lists
            ranking_result = apply_top_k_categorization(ranking_result, top_k, discussions)

        # Step 7: Save results to file
        save_ranking_result(ranking_result, expected_file)

        # Update span with output metrics
        if span:
            featured_count = len(ranking_result.get(RankingResultKeys.FEATURED_DISCUSSION_IDS, []))
            brief_count = len(ranking_result.get(RankingResultKeys.BRIEF_MENTION_ITEMS, []))
            span.update(output={"file_path": expected_file, "total_discussions": len(discussions) if discussions else 0, "featured_count": featured_count, "brief_count": brief_count, "top_k_applied": ranking_result.get(RankingResultKeys.TOP_K_APPLIED, top_k)})

        return {RankerKeys.DISCUSSIONS_RANKING_FILE_PATH: expected_file}


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================


def build_discussions_ranker_graph() -> StateGraph:
    """
    Build and compile the discussions ranker subgraph.

    Graph Structure:
    START → analyze_discussions → END

    Note: This is currently a single-node subgraph, but can be extended to
    multiple nodes if we want to add:
    - Pre-analysis filtering
    - Multi-stage ranking (first pass + refinement)
    - Post-analysis validation

    Returns:
        Compiled StateGraph with checkpointing enabled
    """
    try:
        logger.info("Building discussions ranker subgraph...")

        # Create graph builder
        builder = StateGraph(DiscussionRankerState)

        # Add nodes
        builder.add_node(NodeNames.DiscussionsRanker.ANALYZE_DISCUSSIONS, analyze_discussions)

        # Define linear flow
        builder.add_edge(START, NodeNames.DiscussionsRanker.ANALYZE_DISCUSSIONS)
        builder.add_edge(NodeNames.DiscussionsRanker.ANALYZE_DISCUSSIONS, END)

        # Compile without checkpointer — subgraphs are invoked atomically via ainvoke
        # and are not resumable, so checkpointing provides no value and leaks memory
        compiled_graph = builder.compile()

        logger.info("Discussions ranker subgraph compiled successfully")

        return compiled_graph
    except Exception as e:
        logger.error(f"Failed to build discussions ranker graph: {e}")
        raise RuntimeError(f"Failed to build discussions ranker graph: {e}") from e


# Create and export the compiled subgraph
discussions_ranker_graph = build_discussions_ranker_graph()
