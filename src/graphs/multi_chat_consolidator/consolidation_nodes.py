"""
Cross-Chat Consolidation Nodes for LangGraph 1.0 Parallel Orchestrator

This module implements nodes for consolidating newsletters from multiple chats
into a single unified newsletter. Used by both periodic newsletter and daily summaries workflows.

Nodes:
1. setup_consolidated_directories - Create directory structure
2. consolidate_discussions - Merge discussions from all chats
3. rank_consolidated_discussions - Rank discussions across chats (async)
4. generate_consolidated_newsletter - Generate single newsletter (async)
5. enrich_consolidated_newsletter - Add links to consolidated newsletter (async)
6. translate_consolidated_newsletter - Translate if needed (async)

Architecture:
- Reuses existing subgraphs (discussions_ranker, link_enricher)
- Preserves all per-chat outputs
- Adds consolidated output alongside per-chat outputs
- Fail-fast error handling
- Native async nodes for LangGraph 1.0+ compatibility
"""

import dataclasses
import os
import json
import logging
import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from constants import (
    ENGLISH_LANGUAGE_CODES,
    DEFAULT_LANGUAGE,
    FileFormat,
    NewsletterType,
    NewsletterVersionType,
    NodeNames,
    DIR_NAME_CONSOLIDATED,
    DIR_NAME_AGGREGATED_DISCUSSIONS,
    DIR_NAME_DISCUSSIONS_RANKING,
    DIR_NAME_NEWSLETTER,
    DIR_NAME_LINK_ENRICHMENT,
    DIR_NAME_FINAL_TRANSLATION,
    OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS,
    OUTPUT_FILENAME_CROSS_CHAT_RANKING,
    OUTPUT_FILENAME_CONSOLIDATED_NEWSLETTER_JSON,
    OUTPUT_FILENAME_CONSOLIDATED_NEWSLETTER_MD,
    OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_JSON,
    OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_MD,
    OUTPUT_FILENAME_TRANSLATED_CONSOLIDATED_MD,
    RESULT_KEY_NEWSLETTER_SUMMARY_PATH,
    RESULT_KEY_MARKDOWN_PATH,
    OUTPUT_FILENAME_MERGED_DISCUSSIONS,
)
from graphs.single_chat_analyzer.generate_content_helpers import simplify_discussions_for_prompt
from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
from graphs.subgraphs.state import DiscussionRankerState, LinkEnricherState
from graphs.subgraphs.discussions_ranker import discussions_ranker_graph
from graphs.subgraphs.link_enricher import link_enricher_graph
from graphs.state_keys import OrchestratorKeys, RankerKeys, EnricherKeys, SingleChatKeys
from core.retrieval.mergers import DiscussionMerger, DEFAULT_SIMILARITY_THRESHOLD
from db.run_tracker import get_tracker
from observability.llm import (
    create_span,
    end_span_safely,
    TraceContext,
    extract_trace_context,
)
from observability.metrics import with_metrics
from observability.llm.evaluation import score_newsletter_generation
from api.sse import with_logging
from api.sse.node_decorators import with_progress
from custom_types.field_keys import DiscussionKeys, RankingResultKeys, ContentResultKeys, MergeGroupKeys
from custom_types.sse_events import (
    STAGE_CONSOLIDATE_SETUP,
    STAGE_CONSOLIDATE_DISCUSSIONS,
    STAGE_CONSOLIDATE_RANK,
    STAGE_CONSOLIDATE_GENERATE,
    STAGE_CONSOLIDATE_ENRICH,
    STAGE_CONSOLIDATE_TRANSLATE,
)


# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# LANGFUSE HELPER
# ============================================================================


def _create_node_span(
    name: str,
    config: dict | None = None,
    input_data: dict | None = None,
    metadata: dict | None = None,
):
    """
    Create a Langfuse span for tracing consolidation node operations.

    This is a thin wrapper around create_span that extracts trace context
    from LangGraph config.

    Args:
        name: Name of the span (e.g., "consolidate_discussions")
        config: LangGraph config containing langfuse_trace_id
        input_data: Input data to log
        metadata: Additional metadata

    Returns:
        StatefulSpanClient or None if tracing disabled
    """
    ctx = extract_trace_context(config)
    if not ctx.is_valid:
        return None

    return create_span(
        name=name,
        trace_id=ctx.trace_id,
        parent_span_id=ctx.parent_span_id,
        input_data=input_data,
        metadata=metadata,
    )


def _extract_trace_info(config: dict | None) -> TraceContext:
    """
    Extract trace context from LangGraph config.

    Args:
        config: LangGraph config dict

    Returns:
        TraceContext with extracted trace information
    """
    return extract_trace_context(config)


# ============================================================================
# NODE 1: SETUP CONSOLIDATED DIRECTORIES
# ============================================================================


@with_logging
@with_progress(stage=STAGE_CONSOLIDATE_SETUP, start_message="Setting up consolidation directories...", success_message="Consolidation directories ready")
@with_metrics(node_name=NodeNames.MultiChatConsolidator.SETUP_CONSOLIDATED_DIRECTORIES, workflow_name="cross_chat_consolidation")
def setup_consolidated_directories(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Create directory structure for cross-chat consolidated outputs.

    Directory Structure Created:
    base_output_dir/
    └── consolidated/
        ├── aggregated_discussions/
        ├── discussions_ranking/
        ├── newsletter/
        ├── link_enrichment/
        └── final_translation/

    Args:
        state: ParallelOrchestratorState with base_output_dir

    Returns:
        dict: Partial state update with directory paths and expected file paths

    Raises:
        RuntimeError: If directory creation fails
    """
    logger.info("Node: setup_consolidated_directories - Starting")

    base_output_dir = state[OrchestratorKeys.BASE_OUTPUT_DIR]

    # Create consolidated output directory
    consolidated_output_dir = os.path.join(base_output_dir, DIR_NAME_CONSOLIDATED)

    # Create subdirectories
    dirs = {
        "consolidated_output_dir": consolidated_output_dir,
        "consolidated_aggregated_discussions_dir": os.path.join(consolidated_output_dir, DIR_NAME_AGGREGATED_DISCUSSIONS),
        "consolidated_ranking_dir": os.path.join(consolidated_output_dir, DIR_NAME_DISCUSSIONS_RANKING),
        "consolidated_newsletter_dir": os.path.join(consolidated_output_dir, DIR_NAME_NEWSLETTER),
        "consolidated_enrichment_dir": os.path.join(consolidated_output_dir, DIR_NAME_LINK_ENRICHMENT),
        "consolidated_translation_dir": os.path.join(consolidated_output_dir, DIR_NAME_FINAL_TRANSLATION),
    }

    # Create all directories
    try:
        for dir_path in dirs.values():
            os.makedirs(dir_path, exist_ok=True)
            logger.info(f"Created directory: {dir_path}")
    except Exception as e:
        error_msg = f"Failed to create consolidated directories: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    # Define expected file paths
    expected_files = {
        "expected_consolidated_aggregated_discussions_file": os.path.join(dirs["consolidated_aggregated_discussions_dir"], OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS),
        "expected_consolidated_ranking_file": os.path.join(dirs["consolidated_ranking_dir"], OUTPUT_FILENAME_CROSS_CHAT_RANKING),
        "expected_consolidated_newsletter_json": os.path.join(dirs["consolidated_newsletter_dir"], OUTPUT_FILENAME_CONSOLIDATED_NEWSLETTER_JSON),
        "expected_consolidated_newsletter_md": os.path.join(dirs["consolidated_newsletter_dir"], OUTPUT_FILENAME_CONSOLIDATED_NEWSLETTER_MD),
        "expected_consolidated_enriched_json": os.path.join(dirs["consolidated_enrichment_dir"], OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_JSON),
        "expected_consolidated_enriched_md": os.path.join(dirs["consolidated_enrichment_dir"], OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_MD),
        "expected_consolidated_translated_file": os.path.join(dirs["consolidated_translation_dir"], OUTPUT_FILENAME_TRANSLATED_CONSOLIDATED_MD),
    }

    logger.info("Consolidated directories setup completed")

    return {**dirs, **expected_files}


# ============================================================================
# NODE 2: CONSOLIDATE DISCUSSIONS
# ============================================================================


@with_logging
@with_progress(stage=STAGE_CONSOLIDATE_DISCUSSIONS, start_message="Aggregating discussions from all chats...", success_message="Discussions aggregated successfully")
@with_metrics(node_name=NodeNames.MultiChatConsolidator.CONSOLIDATE_DISCUSSIONS, workflow_name="cross_chat_consolidation")
def consolidate_discussions(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Aggregate discussions from all successful chats into a single collection.

    Process:
    1. Iterate through successful chat_results
    2. For each chat, load separate_discussions file
    3. Merge all discussions, adding source_chat metadata
    4. Save aggregated discussions to consolidated file

    Args:
        state: ParallelOrchestratorState with chat_results
        config: LangGraph config with langfuse_trace_id for tracing

    Returns:
        dict: Partial state update with consolidated discussions path and metadata

    Raises:
        RuntimeError: If aggregation fails or no discussions found

    Note:
        Unlike other nodes, this node does NOT cache/skip if file exists, because it must
        always regenerate based on the CURRENT chat_results from this workflow run.
        Caching would cause stale data from previous runs to persist.
    """
    logger.info("Node: consolidate_discussions - Starting")

    # Create Langfuse span for tracing
    chat_results = state.get(OrchestratorKeys.CHAT_RESULTS, [])
    span = _create_node_span(
        name=NodeNames.MultiChatConsolidator.CONSOLIDATE_DISCUSSIONS,
        config=config,
        input_data={"num_chats": len(chat_results)},
        metadata={
            "start_date": state.get(OrchestratorKeys.START_DATE),
            "end_date": state.get(OrchestratorKeys.END_DATE),
            "summary_format": state.get(OrchestratorKeys.SUMMARY_FORMAT),
        },
    )

    # Get the expected output file path
    expected_file = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_AGGREGATED_DISCUSSIONS_FILE]

    # chat_results already retrieved above for span creation
    if not chat_results:
        error_msg = "No successful chat results to consolidate"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Aggregate discussions from all chats
    all_discussions = []
    total_messages = 0
    source_chats = []
    failed_chats = []

    for chat_result in chat_results:
        chat_name = chat_result.get(SingleChatKeys.CHAT_NAME)
        discussions_file = chat_result.get(SingleChatKeys.SEPARATE_DISCUSSIONS_FILE_PATH)

        if not discussions_file:
            # Try to infer path from chat output structure
            # chat_result doesn't include separate_discussions_file_path, need to construct it
            logger.warning(f"Chat result for {chat_name} missing separate_discussions_file_path, skipping")
            failed_chats.append(chat_name)
            continue

        # Load discussions for this chat
        try:
            if not os.path.exists(discussions_file):
                logger.warning(f"Discussions file not found for chat {chat_name}: {discussions_file}")
                failed_chats.append(chat_name)
                continue

            with open(discussions_file, encoding="utf-8") as f:
                chat_discussions_data = json.load(f)

            # Extract discussions (handle both list and dict formats)
            if isinstance(chat_discussions_data, dict):
                chat_discussions = chat_discussions_data.get(DiscussionKeys.DISCUSSIONS, [])
            elif isinstance(chat_discussions_data, list):
                chat_discussions = chat_discussions_data
            else:
                logger.warning(f"Unexpected discussions format for chat {chat_name}")
                failed_chats.append(chat_name)
                continue

            # Add source chat metadata to each discussion and make IDs globally unique
            # Create sanitized chat prefix for unique IDs
            chat_prefix = re.sub(r"[^a-zA-Z0-9]", "_", chat_name).lower()

            for idx, discussion in enumerate(chat_discussions):
                # Preserve original ID
                original_id = discussion.get(DiscussionKeys.ID, f"discussion_{idx+1}")
                discussion[DiscussionKeys.ORIGINAL_ID] = original_id

                # Create globally unique ID with chat prefix
                discussion[DiscussionKeys.ID] = f"{chat_prefix}_{original_id}"

                # Add source metadata
                discussion[DiscussionKeys.SOURCE_CHAT] = chat_name
                discussion[DiscussionKeys.SOURCE_DATE_RANGE] = f"{chat_result.get(SingleChatKeys.START_DATE)} to {chat_result.get(SingleChatKeys.END_DATE)}"
                all_discussions.append(discussion)
                total_messages += len(discussion.get(DiscussionKeys.MESSAGES, []))

            source_chats.append(chat_name)
            logger.info(f"Aggregated {len(chat_discussions)} discussions from chat: {chat_name}")

        except Exception as e:
            logger.error(f"Failed to load discussions for chat {chat_name}: {e}", exc_info=True)
            failed_chats.append(chat_name)

    # Validate we have at least some discussions
    if not all_discussions:
        error_msg = f"No discussions could be aggregated from {len(chat_results)} chats"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    if failed_chats:
        logger.warning(f"Failed to aggregate discussions from {len(failed_chats)} chats: {failed_chats}")

    # Prepare aggregated data structure
    aggregated_data = {
        DiscussionKeys.METADATA: {
            "total_chats": len(source_chats),
            "source_chats": source_chats,
            "failed_chats": failed_chats,
            "total_discussions": len(all_discussions),
            "total_messages": total_messages,
            "date_range": f"{state[OrchestratorKeys.START_DATE]} to {state[OrchestratorKeys.END_DATE]}",
            "summary_format": state[OrchestratorKeys.SUMMARY_FORMAT],
        },
        DiscussionKeys.DISCUSSIONS: all_discussions,
    }

    # Save aggregated discussions
    output_file = expected_file
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(aggregated_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved aggregated discussions to: {output_file}")
    except Exception as e:
        error_msg = f"Failed to save aggregated discussions: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    logger.info(f"Consolidated {len(all_discussions)} discussions from {len(source_chats)} chats")

    # End span with results
    end_span_safely(
        span,
        output={
            "total_discussions": len(all_discussions),
            "total_messages": total_messages,
            "source_chats": source_chats,
            "failed_chats": failed_chats,
        },
        level="DEFAULT" if not failed_chats else "WARNING",
    )

    return {
        OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH: output_file,
        OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED: len(all_discussions),
        OrchestratorKeys.TOTAL_MESSAGES_CONSOLIDATED: total_messages,
        OrchestratorKeys.SOURCE_CHATS_IN_CONSOLIDATED: source_chats,
    }


# ============================================================================
# NODE 2.5: MERGE SIMILAR DISCUSSIONS
# ============================================================================


@with_logging
@with_metrics(node_name=NodeNames.MultiChatConsolidator.MERGE_SIMILAR_DISCUSSIONS, workflow_name="cross_chat_consolidation")
async def merge_similar_discussions(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Merge semantically similar discussions from multiple chats into enriched super-discussions.

    This node runs AFTER consolidate_discussions and BEFORE rank_consolidated_discussions.
    It identifies discussions covering the same/overlapping topics across different chats
    and merges them into comprehensive "super discussions" that capture ALL perspectives.

    Benefits:
    - No valuable insights lost (all perspectives preserved in merged discussion)
    - No repetition in newsletter (one topic = one discussion)
    - Ranker sees accurate picture (merged importance reflects combined value)
    - Readers get comprehensive coverage with multi-group attribution

    Process:
    1. Load aggregated discussions from consolidate_discussions output
    2. Use LLM to identify which discussions should be merged (same/overlapping topics)
    3. For each merge group:
       a. Combine messages chronologically
       b. Generate merged title
       c. Synthesize comprehensive nutshell
       d. Calculate aggregate stats
    4. Output merged + standalone discussions
    5. Save to merged_discussions.json
    6. Update state for ranker to use merged file

    Configuration:
    - enable_discussion_merging: bool (default: True for multi-chat)
    - similarity_threshold: "strict" | "moderate" | "aggressive" (default: "moderate")

    Args:
        state: ParallelOrchestratorState with consolidated_aggregated_discussions_path

    Returns:
        dict: Partial state update with merged discussions path and stats

    Raises:
        RuntimeError: If merging fails critically (graceful degradation on non-critical errors)
    """
    logger.info("Node: merge_similar_discussions - Starting")

    # Check if merging is enabled
    enable_merging = state.get(OrchestratorKeys.ENABLE_DISCUSSION_MERGING, True)
    if not enable_merging:
        logger.info("Discussion merging disabled (enable_discussion_merging=False)")
        # Pass through without modification
        aggregated_path = state.get(OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH)
        return {
            OrchestratorKeys.MERGED_DISCUSSIONS_FILE_PATH: aggregated_path,
            OrchestratorKeys.NUM_DISCUSSIONS_BEFORE_MERGE: state.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED, 0),
            OrchestratorKeys.NUM_DISCUSSIONS_AFTER_MERGE: state.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED, 0),
            OrchestratorKeys.MERGE_OPERATIONS_COUNT: 0,
        }

    # Get aggregated discussions path
    aggregated_path = state.get(OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH)
    if not aggregated_path or not os.path.exists(aggregated_path):
        error_msg = f"Aggregated discussions file not found: {aggregated_path}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Load aggregated discussions
    try:
        with open(aggregated_path, encoding="utf-8") as f:
            aggregated_data = json.load(f)
    except Exception as e:
        error_msg = f"Failed to load aggregated discussions: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    # Extract discussions list
    if isinstance(aggregated_data, dict):
        discussions = aggregated_data.get(DiscussionKeys.DISCUSSIONS, [])
        metadata = aggregated_data.get(DiscussionKeys.METADATA, {})
    else:
        discussions = aggregated_data
        metadata = {}

    # Check if merging is worthwhile (need at least 2 discussions)
    if len(discussions) < 2:
        logger.info(f"Only {len(discussions)} discussion(s) - nothing to merge")
        return {
            OrchestratorKeys.MERGED_DISCUSSIONS_FILE_PATH: aggregated_path,
            OrchestratorKeys.NUM_DISCUSSIONS_BEFORE_MERGE: len(discussions),
            OrchestratorKeys.NUM_DISCUSSIONS_AFTER_MERGE: len(discussions),
            OrchestratorKeys.MERGE_OPERATIONS_COUNT: 0,
        }

    # Get similarity threshold from state
    similarity_threshold = state.get(OrchestratorKeys.SIMILARITY_THRESHOLD, DEFAULT_SIMILARITY_THRESHOLD)
    logger.info(f"Merging {len(discussions)} discussions with threshold={similarity_threshold}")

    # Initialize merger and execute merge
    try:
        merger = DiscussionMerger(
            similarity_threshold=similarity_threshold,
            enabled=True,
        )
        merge_result = await merger.merge(discussions)

    except Exception as e:
        # Graceful degradation - if merging fails, continue with unmerged discussions
        logger.warning(f"Discussion merging failed, continuing with unmerged: {e}")
        return {
            OrchestratorKeys.MERGED_DISCUSSIONS_FILE_PATH: aggregated_path,
            OrchestratorKeys.NUM_DISCUSSIONS_BEFORE_MERGE: len(discussions),
            OrchestratorKeys.NUM_DISCUSSIONS_AFTER_MERGE: len(discussions),
            OrchestratorKeys.MERGE_OPERATIONS_COUNT: 0,
        }

    # Prepare output data
    merged_data = {
        DiscussionKeys.METADATA: {
            **metadata,
            "original_discussion_count": merge_result.original_count,
            "merged_discussion_count": merge_result.merged_count,
            "merge_operations": merge_result.merge_operations,
            "similarity_threshold": similarity_threshold,
            MergeGroupKeys.MERGE_GROUPS: [dataclasses.asdict(mg) for mg in merge_result.merge_groups],
        },
        DiscussionKeys.DISCUSSIONS: merge_result.discussions,
    }

    # Save merged discussions to new file
    merged_dir = state.get(OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_DIR)
    if not merged_dir:
        merged_dir = os.path.dirname(aggregated_path)

    merged_file_path = os.path.join(merged_dir, OUTPUT_FILENAME_MERGED_DISCUSSIONS)

    try:
        with open(merged_file_path, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved merged discussions to: {merged_file_path}")
    except Exception as e:
        error_msg = f"Failed to save merged discussions: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    if merge_result.merge_operations > 0:
        merge_group_summaries = [f"'{mg.suggested_title}' ({len(mg.discussion_ids)} discussions from {', '.join(mg.source_groups)})" for mg in merge_result.merge_groups]
        logger.info(f"Merged {merge_result.merge_operations} groups: {'; '.join(merge_group_summaries)}")

    logger.info(f"Discussion merging complete: {merge_result.original_count} → {merge_result.merged_count} " f"({merge_result.merge_operations} merge operations)")

    return {
        OrchestratorKeys.MERGED_DISCUSSIONS_FILE_PATH: merged_file_path,
        OrchestratorKeys.NUM_DISCUSSIONS_BEFORE_MERGE: merge_result.original_count,
        OrchestratorKeys.NUM_DISCUSSIONS_AFTER_MERGE: merge_result.merged_count,
        OrchestratorKeys.MERGE_OPERATIONS_COUNT: merge_result.merge_operations,
        # Update consolidated path for downstream nodes to use merged version
        OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH: merged_file_path,
        OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED: merge_result.merged_count,
    }


# ============================================================================
# NODE 3: RANK CONSOLIDATED DISCUSSIONS
# ============================================================================


@with_logging
@with_progress(stage=STAGE_CONSOLIDATE_RANK, start_message="Ranking discussions across all chats...", success_message="Cross-chat ranking completed")
@with_metrics(node_name=NodeNames.MultiChatConsolidator.RANK_CONSOLIDATED_DISCUSSIONS, workflow_name="cross_chat_consolidation")
async def rank_consolidated_discussions(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Rank discussions across all chats using the discussions_ranker subgraph.

    Process:
    1. Load aggregated discussions
    2. Invoke discussions_ranker subgraph with cross-chat discussions (async)
    3. Save ranking results

    Ranking considers:
    - Relevance to summary format (langtalks/mcp)
    - Technical depth and quality
    - Engagement (message count, participants)
    - Cross-chat diversity (ensure representation from all chats)
    - Timeliness

    Args:
        state: ParallelOrchestratorState with consolidated_aggregated_discussions_path
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Partial state update with consolidated_ranking_path

    Raises:
        RuntimeError: If ranking fails
    """
    logger.info("Node: rank_consolidated_discussions - Starting")

    # Create Langfuse span for tracing
    span = _create_node_span(
        name=NodeNames.MultiChatConsolidator.RANK_CONSOLIDATED_DISCUSSIONS,
        config=config,
        input_data={
            "summary_format": state.get(OrchestratorKeys.SUMMARY_FORMAT),
            "total_discussions": state.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED),
        },
        metadata={
            "data_source_name": state.get(OrchestratorKeys.DATA_SOURCE_NAME),
            "previous_newsletters_to_consider": state.get(OrchestratorKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER, 5),
        },
    )

    # Check if we should skip
    expected_file = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_RANKING_FILE]
    force_refresh = state.get(OrchestratorKeys.FORCE_REFRESH_CROSS_CHAT_RANKING, False)

    if os.path.exists(expected_file) and not force_refresh:
        logger.info(f"Consolidated ranking already exists at {expected_file}, skipping ranking")
        return {OrchestratorKeys.CONSOLIDATED_RANKING_PATH: expected_file}

    # Get aggregated discussions path
    aggregated_discussions_path = state.get(OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH)
    if not aggregated_discussions_path or not os.path.exists(aggregated_discussions_path):
        error_msg = f"Aggregated discussions file not found: {aggregated_discussions_path}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Extract trace context from config for passing to ranker
    trace_id = None
    session_id = None
    user_id = None
    if config:
        configurable = config.get("configurable", {})
        trace_id = configurable.get("langfuse_trace_id")
        session_id = configurable.get("langfuse_session_id")
        user_id = configurable.get("langfuse_user_id")

    # Prepare state for discussions_ranker subgraph
    ranker_state: DiscussionRankerState = {
        RankerKeys.SEPARATE_DISCUSSIONS_FILE_PATH: aggregated_discussions_path,
        RankerKeys.DISCUSSIONS_RANKING_DIR: state[OrchestratorKeys.CONSOLIDATED_RANKING_DIR],
        RankerKeys.EXPECTED_DISCUSSIONS_RANKING_FILE: expected_file,
        RankerKeys.SUMMARY_FORMAT: state[OrchestratorKeys.SUMMARY_FORMAT],
        RankerKeys.FORCE_REFRESH_DISCUSSIONS_RANKING: force_refresh,
        RankerKeys.TOP_K_DISCUSSIONS: state.get(OrchestratorKeys.TOP_K_DISCUSSIONS),
        RankerKeys.DISCUSSIONS_RANKING_FILE_PATH: None,
        # Anti-repetition configuration
        RankerKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER: state.get(OrchestratorKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER, 5),
        RankerKeys.DATA_SOURCE_NAME: state.get(OrchestratorKeys.DATA_SOURCE_NAME),
        RankerKeys.CURRENT_START_DATE: state.get(OrchestratorKeys.START_DATE),
        # Langfuse trace context for LLM calls
        RankerKeys.LANGFUSE_TRACE_ID: trace_id,
        RankerKeys.LANGFUSE_SESSION_ID: session_id,
        RankerKeys.LANGFUSE_USER_ID: user_id,
    }

    # Invoke discussions_ranker subgraph (async - LangGraph 1.0)
    try:
        logger.info("Invoking discussions_ranker subgraph for cross-chat ranking")
        ranker_result = await discussions_ranker_graph.ainvoke(ranker_state, config=config)

        ranking_file_path = ranker_result.get(RankerKeys.DISCUSSIONS_RANKING_FILE_PATH)
        if not ranking_file_path or not os.path.exists(ranking_file_path):
            error_msg = "Discussions ranker did not produce ranking file"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"Cross-chat ranking completed: {ranking_file_path}")

        # End span with success
        end_span_safely(
            span,
            output={"ranking_file_path": ranking_file_path},
            level="DEFAULT",
        )

        return {OrchestratorKeys.CONSOLIDATED_RANKING_PATH: ranking_file_path}

    except Exception as e:
        # End span with error
        end_span_safely(span, level="ERROR", status_message=str(e))
        error_msg = f"Failed to rank consolidated discussions: {e}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e


# ============================================================================
# HELPER: Load Content Generator
# ============================================================================


async def _generate_newsletter_from_discussions(
    discussions_file_path: str,
    output_json_path: str,
    output_md_path: str,
    summary_format: str,
    source_chats: list[str],
    date_range: str,
    featured_discussions: list[dict[str, Any]] = None,
    brief_mention_items: list[dict[str, Any]] = None,
    non_featured_discussions: list[dict[str, Any]] = None,
    desired_language_for_summary: str = DEFAULT_LANGUAGE,
    newsletter_id: str | None = None,
    run_id: str | None = None,
    data_source_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    featured_discussion_ids: list[str] | None = None,
) -> dict[str, str]:
    """
    Helper function to generate newsletter content from aggregated discussions.

    This reuses the content generation logic from the existing newsletter
    generation pipeline. The content generator expects separate_discussions format,
    not rankings.

    Supports MongoDB-first persistence (Phase 4 MongoDB migration).

    Args:
        discussions_file_path: Path to aggregated discussions JSON (separate_discussions format)
        output_json_path: Where to save newsletter JSON
        output_md_path: Where to save newsletter MD
        summary_format: Newsletter format (langtalks_format or mcp_israel_format)
        source_chats: List of chat names included
        date_range: Date range string
        featured_discussions: Optional pre-filtered discussions (from ranking)
        brief_mention_items: Optional one-liners for worth_mentioning section
        desired_language_for_summary: Target language for newsletter output (default: DEFAULT_LANGUAGE)
        newsletter_id: MongoDB newsletter ID (for MongoDB persistence)
        run_id: MongoDB run ID (for MongoDB persistence)
        data_source_name: Data source name (e.g., "langtalks")
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        featured_discussion_ids: List of featured discussion IDs

    Returns:
        dict: newsletter_id (if MongoDB enabled) and/or file paths

    Raises:
        RuntimeError: If generation fails
    """
    # Import content generator
    from core.generation.generators.factory import ContentGeneratorFactory
    from constants import DataSources, ContentGenerationOperations

    try:
        # Initialize MongoDB repository if run_id is provided
        newsletters_repo = None
        if run_id:
            try:
                from db.connection import get_database
                from db.repositories.newsletters import NewslettersRepository

                db = await get_database()
                newsletters_repo = NewslettersRepository(db)
                logger.info(f"MongoDB persistence enabled for consolidated newsletter: {newsletter_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize MongoDB repository: {e}")

        # Get content generator for format
        content_generator = ContentGeneratorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, summary_format=summary_format, newsletters_repo=newsletters_repo)

        # Generate newsletter content using the same API as SingleChatState generate_content node
        content_result = await content_generator.generate_content(
            operation=ContentGenerationOperations.GENERATE_NEWSLETTER_SUMMARY,
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            data_source_path=discussions_file_path,
            output_dir=os.path.dirname(output_json_path),
            group_name=f"Consolidated ({len(source_chats)} chats)",
            date=date_range,
            # NEW: Pass filtered discussions and brief_mention items
            featured_discussions=featured_discussions,
            brief_mention_items=brief_mention_items or [],
            non_featured_discussions=non_featured_discussions or [],
            desired_language_for_summary=desired_language_for_summary,
            # MongoDB metadata (Phase 4 MongoDB migration)
            newsletter_id=newsletter_id,
            run_id=run_id,
            newsletter_type=NewsletterType.CONSOLIDATED,
            data_source_name=data_source_name,
            start_date=start_date,
            end_date=end_date,
            summary_format=summary_format,
            chat_name=None,  # Consolidated newsletters don't have a single chat name
            featured_discussion_ids=featured_discussion_ids or [],
        )

        if not content_result:
            raise RuntimeError("Content generation returned no result")

        # Build result dict with both MongoDB ID and file paths
        result = {}

        # MongoDB ID (primary)
        if newsletter_id:
            result[ContentResultKeys.NEWSLETTER_ID] = newsletter_id

        # File paths (backward compatibility)
        newsletter_json_path = content_result.get(RESULT_KEY_NEWSLETTER_SUMMARY_PATH)
        newsletter_md_path = content_result.get(RESULT_KEY_MARKDOWN_PATH)

        if newsletter_json_path:
            result["newsletter_json_path"] = newsletter_json_path
        if newsletter_md_path:
            result["newsletter_md_path"] = newsletter_md_path

        # Verify files were created (if file outputs enabled)
        from config import get_settings

        settings = get_settings()

        if settings.database.enable_file_outputs:
            if not newsletter_json_path or not os.path.exists(newsletter_json_path):
                raise RuntimeError(f"Content generation did not create JSON file: {output_json_path}")
            if not newsletter_md_path or not os.path.exists(newsletter_md_path):
                raise RuntimeError(f"Content generation did not create MD file: {output_md_path}")
            logger.info(f"Generated consolidated newsletter files: JSON={newsletter_json_path}, MD={newsletter_md_path}")

        if newsletter_id:
            logger.info(f"Generated consolidated newsletter in MongoDB: {newsletter_id}")

        return result

    except Exception as e:
        error_msg = f"Failed to generate newsletter from discussions: {e}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e


# ============================================================================
# NODE 4: GENERATE CONSOLIDATED NEWSLETTER
# ============================================================================


@with_logging
@with_progress(stage=STAGE_CONSOLIDATE_GENERATE, start_message="Generating consolidated newsletter...", success_message="Consolidated newsletter generated")
@with_metrics(node_name=NodeNames.MultiChatConsolidator.GENERATE_CONSOLIDATED_NEWSLETTER, workflow_name="cross_chat_consolidation")
async def generate_consolidated_newsletter(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Generate single consolidated newsletter from ranked discussions.

    Process:
    1. Load ranked discussions
    2. Invoke content generator with rankings
    3. Generate newsletter JSON and Markdown
    4. Include source chat attribution

    Args:
        state: ParallelOrchestratorState with consolidated_ranking_path
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Partial state update with newsletter file paths

    Raises:
        RuntimeError: If generation fails
    """
    logger.info("Node: generate_consolidated_newsletter - Starting")

    # Create Langfuse span for tracing
    span = _create_node_span(
        name=NodeNames.MultiChatConsolidator.GENERATE_CONSOLIDATED_NEWSLETTER,
        config=config,
        input_data={
            "summary_format": state.get(OrchestratorKeys.SUMMARY_FORMAT),
            "total_discussions": state.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED),
        },
        metadata={
            "data_source_name": state.get(OrchestratorKeys.DATA_SOURCE_NAME),
            "source_chats": state.get(OrchestratorKeys.SOURCE_CHATS_IN_CONSOLIDATED, []),
        },
    )

    # Check if we should skip (MongoDB-first, then files)
    mongodb_run_id = state.get(OrchestratorKeys.MONGODB_RUN_ID)
    force_refresh = state.get(OrchestratorKeys.FORCE_REFRESH_CONSOLIDATED_CONTENT, False)

    if not force_refresh and mongodb_run_id:
        # Check MongoDB first (native async - LangGraph 1.0)
        consolidated_newsletter_id = f"{mongodb_run_id}_nl_consolidated"
        try:
            from db.connection import get_database
            from db.repositories.newsletters import NewslettersRepository

            db = await get_database()
            repo = NewslettersRepository(db)
            existing_newsletter = await repo.get_newsletter(consolidated_newsletter_id)

            if existing_newsletter:
                logger.info(f"Consolidated newsletter already exists in MongoDB: {consolidated_newsletter_id}")
                return {OrchestratorKeys.CONSOLIDATED_NEWSLETTER_ID: consolidated_newsletter_id}
        except Exception as e:
            logger.warning(f"Failed to check MongoDB for existing newsletter: {e}")

    # Fallback: Check files (backward compatibility)
    expected_json = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_NEWSLETTER_JSON]
    expected_md = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_NEWSLETTER_MD]

    if os.path.exists(expected_json) and os.path.exists(expected_md) and not force_refresh:
        logger.info("Consolidated newsletter files already exist, skipping generation")
        return {
            OrchestratorKeys.CONSOLIDATED_NEWSLETTER_JSON_PATH: expected_json,
            OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH: expected_md,
        }

    # Get aggregated discussions file path (content generator needs discussions, not rankings)
    discussions_path = state.get(OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH)
    if not discussions_path or not os.path.exists(discussions_path):
        error_msg = f"Consolidated discussions file not found: {discussions_path}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Load ranking data to get featured_discussion_ids and brief_mention_items
    # FAIL-FAST: Ranking file is required for consolidated content generation
    ranking_path = state.get(OrchestratorKeys.CONSOLIDATED_RANKING_PATH)

    if not ranking_path:
        raise RuntimeError("Missing consolidated_ranking_path in state. " "The rank_consolidated_discussions node must run before generate_consolidated_newsletter.")

    if not os.path.exists(ranking_path):
        raise FileNotFoundError(f"Consolidated ranking file not found: {ranking_path}. " "Ensure the rank_consolidated_discussions node completed successfully.")

    try:
        with open(ranking_path, encoding="utf-8") as f:
            ranking_data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in consolidated ranking file {ranking_path}: {e}. " "The ranking file is corrupted or malformed.")
    except Exception as e:
        raise RuntimeError(f"Failed to read consolidated ranking file {ranking_path}: {e}")

    featured_discussion_ids = ranking_data.get(RankingResultKeys.FEATURED_DISCUSSION_IDS)
    if featured_discussion_ids is None:
        raise RuntimeError(f"Consolidated ranking file {ranking_path} missing 'featured_discussion_ids' field. " "This indicates the ranking was generated with an older version. " "Please re-run with force_refresh_cross_chat_ranking=true.")

    brief_mention_items = ranking_data.get(RankingResultKeys.BRIEF_MENTION_ITEMS, [])
    logger.info(f"Loaded consolidated ranking: {len(featured_discussion_ids)} featured, {len(brief_mention_items)} brief_mention")

    # Filter discussions to only include featured ones
    if not featured_discussion_ids:
        raise RuntimeError("No featured_discussion_ids found in consolidated ranking. " "The ranking file exists but contains no featured discussions. " "This may indicate all discussions were marked as 'skip'.")

    try:
        with open(discussions_path, encoding="utf-8") as f:
            all_discussions_data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in discussions file {discussions_path}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to read discussions file {discussions_path}: {e}")

    # Extract discussions list
    if isinstance(all_discussions_data, dict):
        all_discussions = all_discussions_data.get(DiscussionKeys.DISCUSSIONS, [])
    else:
        all_discussions = all_discussions_data

    # Filter to only featured discussions
    featured_ids_set = set(featured_discussion_ids)
    featured_discussions = [d for d in all_discussions if d.get(DiscussionKeys.ID) in featured_ids_set]

    if not featured_discussions:
        raise RuntimeError(f"No matching discussions found for featured IDs in consolidated newsletter. " f"Featured IDs from ranking: {featured_discussion_ids}. " f"Discussion IDs in file: {[d.get(DiscussionKeys.ID) for d in all_discussions]}. " "This indicates a mismatch between ranking and aggregated discussions files.")

    logger.info(f"Filtered to {len(featured_discussions)} featured discussions out of {len(all_discussions)} total")

    # Load non-featured discussions as fallback for worth_mentioning
    non_featured_discussions = []
    if not brief_mention_items:
        non_featured = [d for d in all_discussions if d.get(DiscussionKeys.ID) not in featured_ids_set]
        non_featured_discussions = simplify_discussions_for_prompt(non_featured)
        logger.info(f"Loaded {len(non_featured_discussions)} non-featured discussions as fallback context for worth_mentioning")

    # Generate consolidated newsletter_id for MongoDB
    mongodb_run_id = state.get(OrchestratorKeys.MONGODB_RUN_ID)
    consolidated_newsletter_id = None

    if mongodb_run_id:
        # Format: {run_id}_nl_consolidated
        consolidated_newsletter_id = f"{mongodb_run_id}_nl_consolidated"
        logger.info(f"Generated consolidated newsletter_id: {consolidated_newsletter_id}")

    # Generate newsletter
    try:
        result = await _generate_newsletter_from_discussions(
            discussions_file_path=discussions_path,
            output_json_path=expected_json,
            output_md_path=expected_md,
            summary_format=state[OrchestratorKeys.SUMMARY_FORMAT],
            source_chats=state.get(OrchestratorKeys.SOURCE_CHATS_IN_CONSOLIDATED, []),
            date_range=f"{state[OrchestratorKeys.START_DATE]} to {state[OrchestratorKeys.END_DATE]}",
            featured_discussions=featured_discussions,
            brief_mention_items=brief_mention_items,
            non_featured_discussions=non_featured_discussions,
            desired_language_for_summary=state[OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY],
            # MongoDB metadata (Phase 4 MongoDB migration)
            newsletter_id=consolidated_newsletter_id,
            run_id=mongodb_run_id,
            data_source_name=state.get(OrchestratorKeys.DATA_SOURCE_NAME),
            start_date=state.get(OrchestratorKeys.START_DATE),
            end_date=state.get(OrchestratorKeys.END_DATE),
            featured_discussion_ids=featured_discussion_ids,
        )

        # Get newsletter_id from result (primary) or fall back to file path
        newsletter_id = result.get(ContentResultKeys.NEWSLETTER_ID)
        newsletter_json_path = result.get("newsletter_json_path")
        source_chats = state.get(OrchestratorKeys.SOURCE_CHATS_IN_CONSOLIDATED, [])

        # Add consolidated metadata to the newsletter JSON (only if file exists)
        # MongoDB-first: This is for backward compatibility when file outputs are enabled
        newsletter_data = None
        if newsletter_json_path and os.path.exists(newsletter_json_path):
            try:
                with open(newsletter_json_path, encoding="utf-8") as f:
                    newsletter_data = json.load(f)

                # Add consolidated metadata
                if DiscussionKeys.METADATA not in newsletter_data:
                    newsletter_data[DiscussionKeys.METADATA] = {}

                newsletter_data[DiscussionKeys.METADATA]["source_chats"] = source_chats
                newsletter_data[DiscussionKeys.METADATA]["total_chats_consolidated"] = len(source_chats)
                newsletter_data[DiscussionKeys.METADATA]["is_consolidated"] = True

                # Save updated newsletter
                with open(newsletter_json_path, "w", encoding="utf-8") as f:
                    json.dump(newsletter_data, f, indent=2, ensure_ascii=False)

                logger.info(f"Added consolidated metadata to file: {len(source_chats)} source chats")
            except Exception as e:
                logger.warning(f"Failed to add consolidated metadata to file: {e}")

        # If we have newsletter_id but no file, load from MongoDB for scoring (native async)
        if newsletter_id and not newsletter_data:
            try:
                from db.connection import get_database
                from db.repositories.newsletters import NewslettersRepository

                db = await get_database()
                repo = NewslettersRepository(db)
                newsletter_data = await repo.get_newsletter_content(newsletter_id, version=NewsletterVersionType.ORIGINAL, format=FileFormat.JSON)
                logger.info("Loaded newsletter from MongoDB for scoring")
            except Exception as e:
                logger.warning(f"Failed to load newsletter from MongoDB: {e}")

        logger.info("Consolidated newsletter generation completed")

        # ✅ EVALUATION SCORING: Comprehensive newsletter quality scoring
        if span:
            try:
                # Calculate total discussions for coverage scoring
                total_discussions = len(all_discussions)
                featured_count = len(featured_discussion_ids)
                brief_count = len(brief_mention_items)

                # Extract trace context for scoring
                ctx = extract_trace_context(config)

                scores = score_newsletter_generation(
                    trace_id=ctx.trace_id,
                    observation_id=span.id if hasattr(span, "id") else None,
                    newsletter_result=newsletter_data,
                    total_discussions=total_discussions,
                    featured_count=featured_count,
                    brief_mention_count=brief_count,
                )
                logger.info(f"Consolidated newsletter scores - " f"Structural: {scores['structural_completeness']:.2f}, " f"Coverage: {scores['ranking_coverage']:.2f}, " f"Balance: {scores['content_balance']:.2f}")
            except Exception as e:
                logger.warning(f"Failed to score consolidated newsletter: {e}")

        # End span with success
        end_span_safely(
            span,
            output={
                ContentResultKeys.NEWSLETTER_ID: newsletter_id,
                "newsletter_json_path": newsletter_json_path,
                "source_chats_count": len(source_chats),
            },
            level="DEFAULT",
        )

        # NOTE: MongoDB persistence is now handled by the generator (Phase 1.2)
        # The duplicate store_newsletter_sync code has been removed

        # Build return dict with both MongoDB ID (primary) and file paths (backward compat)
        return_dict = {}

        # MongoDB ID (primary)
        if newsletter_id:
            return_dict[OrchestratorKeys.CONSOLIDATED_NEWSLETTER_ID] = newsletter_id

        # File paths (backward compatibility)
        if newsletter_json_path:
            return_dict[OrchestratorKeys.CONSOLIDATED_NEWSLETTER_JSON_PATH] = newsletter_json_path
        if result.get("newsletter_md_path"):
            return_dict[OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH] = result["newsletter_md_path"]

        return return_dict

    except Exception as e:
        # End span with error
        end_span_safely(span, level="ERROR", status_message=str(e))
        error_msg = f"Failed to generate consolidated newsletter: {e}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e


# ============================================================================
# NODE 5: ENRICH CONSOLIDATED NEWSLETTER
# ============================================================================


@with_logging
@with_progress(stage=STAGE_CONSOLIDATE_ENRICH, start_message="Enriching consolidated newsletter with links...", success_message="Consolidated newsletter enriched")
@with_metrics(node_name=NodeNames.MultiChatConsolidator.RELATED_LINKS_ENRICHMENT, workflow_name="cross_chat_consolidation")
async def enrich_consolidated_newsletter(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Enrich consolidated newsletter with links using link_enricher subgraph.

    Process:
    1. Load consolidated newsletter
    2. Load aggregated discussions (source of links)
    3. Invoke link_enricher subgraph (async)
    4. Save enriched newsletter

    Args:
        state: ParallelOrchestratorState with newsletter and discussions paths
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Partial state update with enriched newsletter paths

    Raises:
        RuntimeError: If enrichment fails
    """
    logger.info("Node: enrich_consolidated_newsletter - Starting")

    # Check if we should skip (MongoDB-first, then files)
    mongodb_run_id = state.get(OrchestratorKeys.MONGODB_RUN_ID)
    force_refresh = state.get(OrchestratorKeys.FORCE_REFRESH_CONSOLIDATED_LINK_ENRICHMENT, False)

    if not force_refresh and mongodb_run_id:
        # Check MongoDB first for enriched version (native async - LangGraph 1.0)
        consolidated_newsletter_id = f"{mongodb_run_id}_nl_consolidated"
        try:
            from db.connection import get_database
            from db.repositories.newsletters import NewslettersRepository

            db = await get_database()
            repo = NewslettersRepository(db)
            existing_enriched = await repo.get_newsletter_content(consolidated_newsletter_id, version=NewsletterVersionType.ENRICHED, format=FileFormat.JSON)

            if existing_enriched:
                logger.info(f"Enriched consolidated newsletter already exists in MongoDB: {consolidated_newsletter_id}")
                return {OrchestratorKeys.CONSOLIDATED_NEWSLETTER_ID: consolidated_newsletter_id}
        except Exception as e:
            logger.warning(f"Failed to check MongoDB for enriched version: {e}")

    # Fallback: Check files (backward compatibility)
    expected_json = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_ENRICHED_JSON]
    expected_md = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_ENRICHED_MD]

    if os.path.exists(expected_json) and os.path.exists(expected_md) and not force_refresh:
        logger.info("Enriched consolidated newsletter files already exist, skipping enrichment")
        return {
            OrchestratorKeys.CONSOLIDATED_ENRICHED_JSON_PATH: expected_json,
            OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH: expected_md,
        }

    # Get required paths
    newsletter_json = state.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_JSON_PATH)
    newsletter_md = state.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH)
    discussions_path = state.get(OrchestratorKeys.CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH)

    if not all([newsletter_json, newsletter_md, discussions_path]):
        error_msg = "Missing required paths for link enrichment"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Prepare state for link_enricher subgraph
    enricher_state: LinkEnricherState = {
        EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH: discussions_path,
        EnricherKeys.NEWSLETTER_JSON_PATH: newsletter_json,
        EnricherKeys.NEWSLETTER_MD_PATH: newsletter_md,
        EnricherKeys.LINK_ENRICHMENT_DIR: state[OrchestratorKeys.CONSOLIDATED_ENRICHMENT_DIR],
        EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_JSON: expected_json,
        EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_MD: expected_md,
        EnricherKeys.SUMMARY_FORMAT: state[OrchestratorKeys.SUMMARY_FORMAT],
        EnricherKeys.FORCE_REFRESH_LINK_ENRICHMENT: force_refresh,
        EnricherKeys.EXTRACTED_LINKS: [],
        EnricherKeys.SEARCHED_LINKS: [],
        EnricherKeys.AGGREGATED_LINKS_FILE_PATH: None,
        EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH: None,
        EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH: None,
        EnricherKeys.NUM_LINKS_EXTRACTED: None,
        EnricherKeys.NUM_LINKS_SEARCHED: None,
        EnricherKeys.NUM_LINKS_INSERTED: None,
    }

    # Invoke link_enricher subgraph (async - LangGraph 1.0)
    try:
        logger.info("Invoking link_enricher subgraph for consolidated newsletter")
        enricher_result = await link_enricher_graph.ainvoke(enricher_state, config=config)

        enriched_json_path = enricher_result.get(EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH)
        enriched_md_path = enricher_result.get(EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH)

        if not enriched_json_path or not enriched_md_path:
            error_msg = "Link enricher did not produce enriched files"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info("Consolidated newsletter enrichment completed")

        # === MONGODB PERSISTENCE: Store enriched version (native async - LangGraph 1.0) ===
        consolidated_newsletter_id = None
        if mongodb_run_id:
            try:
                from db.connection import get_database
                from db.repositories.newsletters import NewslettersRepository

                db = await get_database()
                repo = NewslettersRepository(db)

                consolidated_newsletter_id = f"{mongodb_run_id}_nl_consolidated"
                links_added = enricher_result.get(EnricherKeys.NUM_LINKS_INSERTED, 0)

                # Read enriched content (if files exist)
                enriched_json = None
                enriched_markdown = None

                if enriched_json_path and os.path.exists(enriched_json_path):
                    with open(enriched_json_path, encoding="utf-8") as f:
                        enriched_json = json.load(f)

                if enriched_md_path and os.path.exists(enriched_md_path):
                    with open(enriched_md_path, encoding="utf-8") as f:
                        enriched_markdown = f.read()

                # Update enriched version in MongoDB
                await repo.add_enriched_version(
                    newsletter_id=consolidated_newsletter_id,
                    enriched_json=enriched_json,
                    enriched_markdown=enriched_markdown,
                    enriched_html=None,  # Not generated for consolidated
                    file_paths={},  # Deprecated
                    links_added=links_added,
                )

                logger.info(f"Enriched version saved to MongoDB: {consolidated_newsletter_id} (links_added={links_added})")

            except Exception as e:
                logger.warning(f"Failed to save enriched version to MongoDB: {e}")

        # Build return dict with both MongoDB ID (primary) and file paths (backward compat)
        return_dict = {}

        if consolidated_newsletter_id:
            return_dict[OrchestratorKeys.CONSOLIDATED_NEWSLETTER_ID] = consolidated_newsletter_id

        if enriched_json_path:
            return_dict[OrchestratorKeys.CONSOLIDATED_ENRICHED_JSON_PATH] = enriched_json_path
        if enriched_md_path:
            return_dict[OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH] = enriched_md_path

        return return_dict

    except Exception as e:
        error_msg = f"Failed to enrich consolidated newsletter: {e}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e


# ============================================================================
# NODE 6: TRANSLATE CONSOLIDATED NEWSLETTER
# ============================================================================


@with_logging
@with_progress(stage=STAGE_CONSOLIDATE_TRANSLATE, start_message="Translating consolidated newsletter...", success_message="Consolidated newsletter translated")
@with_metrics(node_name=NodeNames.MultiChatConsolidator.TRANSLATE_CONSOLIDATED_NEWSLETTER, workflow_name="cross_chat_consolidation")
async def translate_consolidated_newsletter(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Translate consolidated newsletter if target language is not English.

    Process:
    1. Check if translation is needed
    2. If needed, invoke translator with enriched newsletter (Markdown)
    3. Save translated output

    Args:
        state: ParallelOrchestratorState with enriched newsletter path
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Partial state update with translated file path (or None if not needed)

    Raises:
        RuntimeError: If translation fails when needed
    """
    logger.info("Node: translate_consolidated_newsletter - Starting")

    desired_language = state[OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY].lower()

    # Check if translation is needed
    if desired_language in ENGLISH_LANGUAGE_CODES:
        logger.info("Target language is English, skipping translation")
        return {OrchestratorKeys.CONSOLIDATED_TRANSLATED_PATH: None}

    # Check if we should skip
    expected_file = state[OrchestratorKeys.EXPECTED_CONSOLIDATED_TRANSLATED_FILE]
    force_refresh = state.get(OrchestratorKeys.FORCE_REFRESH_CONSOLIDATED_TRANSLATION, False)

    if os.path.exists(expected_file) and not force_refresh:
        logger.info("Translated consolidated newsletter already exists, skipping translation")
        return {OrchestratorKeys.CONSOLIDATED_TRANSLATED_PATH: expected_file}

    # Get enriched newsletter MD path (not JSON)
    enriched_md = state.get(OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH)
    if not enriched_md or not os.path.exists(enriched_md):
        error_msg = f"Enriched newsletter markdown not found for translation: {enriched_md}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Import required modules for translation
    from core.generation.generators.factory import ContentGeneratorFactory
    from constants import DataSources, ContentGenerationOperations

    try:
        # Get data source info from state
        data_source_name = state[OrchestratorKeys.DATA_SOURCE_NAME]
        summary_format = state[OrchestratorKeys.SUMMARY_FORMAT]
        start_date = state[OrchestratorKeys.START_DATE]
        end_date = state[OrchestratorKeys.END_DATE]

        # Use a representative chat name for the content generator
        # (the translation doesn't use this for actual content, just for factory selection)
        chat_names = state.get(OrchestratorKeys.CHAT_NAMES, [])
        representative_chat_name = chat_names[0] if chat_names else "Consolidated"

        # Create content generator using existing factory
        content_generator = ContentGeneratorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, source_name=data_source_name, chat_name=representative_chat_name, summary_format=summary_format)

        # Prepare date string
        if start_date == end_date:
            date_str = start_date
        else:
            date_str = f"{start_date} to {end_date}"

        # Translate using existing infrastructure
        translation_result = await content_generator.generate_content(operation=ContentGenerationOperations.TRANSLATE_SUMMARY, data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, data_source_path=enriched_md, group_name="Consolidated Newsletter", expected_final_translated_file_path=expected_file, date=date_str, desired_language_for_summary=desired_language)

        # Verify output file was created
        if not os.path.exists(expected_file):
            raise RuntimeError(f"Translation did not create expected file: {expected_file}")

        logger.info(f"Consolidated newsletter translated to {desired_language}: {expected_file}")

        # === MONGODB PERSISTENCE: Store translated consolidated newsletter (native async) ===
        mongodb_run_id = state.get(OrchestratorKeys.MONGODB_RUN_ID)
        if mongodb_run_id:
            tracker = get_tracker()
            newsletter_id = f"{mongodb_run_id}_nl_consolidated"

            await tracker.store_newsletter(
                newsletter_id=newsletter_id,
                run_id=mongodb_run_id,
                newsletter_type=NewsletterType.CONSOLIDATED,
                data_source_name=state[OrchestratorKeys.DATA_SOURCE_NAME],
                chat_name=None,
                start_date=state[OrchestratorKeys.START_DATE],
                end_date=state[OrchestratorKeys.END_DATE],
                summary_format=state[OrchestratorKeys.SUMMARY_FORMAT],
                desired_language=state[OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY],
                json_path="",  # Not applicable for translated version
                md_path=expected_file,
                version_type=NewsletterVersionType.TRANSLATED,
            )

        return {OrchestratorKeys.CONSOLIDATED_TRANSLATED_PATH: expected_file}

    except Exception as e:
        error_msg = f"Failed to translate consolidated newsletter: {e}"
        logger.error(error_msg, exc_info=True)
        raise RuntimeError(error_msg) from e
