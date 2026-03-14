"""
Parallel Orchestrator Graph - LangGraph 1.0 Implementation

This module implements the parent orchestrator graph that coordinates parallel processing
of multiple WhatsApp chats using LangGraph's Send API. It dispatches individual chats
to worker subgraphs, aggregates results, and handles final output (webhooks, email, etc.).

Architecture:
- Parent graph (ParallelOrchestratorState)
- Worker subgraph (newsletter_generation_graph with SingleChatState)
- Send API for dynamic parallel task creation
- Native async nodes for LangGraph 1.0+ compatibility

Flow:
START → dispatch_chats → [chat_worker (parallel)] → aggregate_results → [consolidate?] → output_handler → END
Output handler dispatches delivery actions: save_local, webhook, send_email, send_linkedin, send_substack

Error Handling Philosophy:
- Fail-fast for configuration errors (invalid config, missing fields)
- Allow partial success (individual chat failures don't stop others)
- Fail if ALL chats fail (no successful results)
"""

import asyncio
import os
import logging
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from langgraph.types import Send, Command

from constants import (
    TIMEOUT_HTTP_REQUEST,
    OutputAction,
    HEADER_CONTENT_TYPE,
    CONTENT_TYPE_JSON,
    DEFAULT_BEEPER_MATRIX_STORE_PATH,
    RunStatus,
    NodeNames,
    HITL_KEY_PHASE_1_COMPLETE,
    HITL_KEY_TIMEOUT_DEADLINE,
    HITL_SUPPORTED_FORMATS,
    DIR_NAME_PER_CHAT,
    DIR_NAME_CONSOLIDATED,
    DIR_NAME_DISCUSSIONS_RANKING,
    DIR_NAME_AGGREGATED_DISCUSSIONS,
    DIR_NAME_DISCUSSIONS_FOR_SELECTION,
    FILE_EXT_MD,
    FILE_EXT_HTML,
    DEFAULT_DATA_SOURCE_FALLBACK,
    OUTPUT_FILENAME_CROSS_CHAT_RANKING,
    OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS,
    OUTPUT_FILENAME_RANKED_DISCUSSIONS,
    HITL_KEY_PHASE_2_READY,
    TAG_NEWSLETTER,
)
from graphs.multi_chat_consolidator.state import ParallelOrchestratorState
from graphs.single_chat_analyzer.state import SingleChatState, create_single_chat_state
from graphs.single_chat_analyzer.graph import newsletter_generation_graph
from graphs.state_keys import (
    ParallelOrchestratorStateKeys as OrchestratorKeys,
    SingleChatStateKeys as SingleChatKeys,
)
from utils.validation import validate_orchestrator_state
from graphs.multi_chat_consolidator.consolidation_nodes import (
    setup_consolidated_directories,
    consolidate_discussions,
    merge_similar_discussions,
    rank_consolidated_discussions,
    generate_consolidated_newsletter,
    enrich_consolidated_newsletter,
    translate_consolidated_newsletter,
)
from graphs.multi_chat_consolidator.linkedin_draft_creator import deliver_to_linkedin
from db.run_tracker import get_tracker
from observability.metrics import with_metrics, get_metrics_client
from api.sse import with_logging
from custom_types.field_keys import DiscussionKeys, RankingResultKeys, MergeGroupKeys


# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# WORKER WRAPPER NODE
# ============================================================================


@with_logging
@with_metrics(node_name=NodeNames.MultiChatConsolidator.CHAT_WORKER, workflow_name="parallel_orchestrator")
async def chat_worker_wrapper(state: SingleChatState, config: RunnableConfig | None = None) -> dict:
    """
    Wrapper node that executes the newsletter generation subgraph and transforms
    results into parent state format (chat_results or chat_errors).

    This node bridges the gap between SingleChatState (worker) and ParallelOrchestratorState (parent).
    It catches exceptions from the worker and packages them appropriately.

    Args:
        state: SingleChatState from Send command
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Contains either chat_results or chat_errors list with single item

    Note:
        The reducer (operator.add) on parent state will append this result to the aggregation list.
    """
    logger.info(f"Worker wrapper starting for chat: {state.get('chat_name', 'unknown')}")

    try:
        # Invoke the worker subgraph asynchronously (LangGraph 1.0)
        # The subgraph is already compiled, so we invoke it directly
        # If the subgraph completes without raising an exception, it succeeded
        final_state = await newsletter_generation_graph.ainvoke(state, config=config)

        # Worker succeeded (no exception raised)
        # Extract relevant result fields
        result = {
            SingleChatKeys.CHAT_NAME: final_state[SingleChatKeys.CHAT_NAME],
            SingleChatKeys.START_DATE: final_state[SingleChatKeys.START_DATE],
            SingleChatKeys.END_DATE: final_state[SingleChatKeys.END_DATE],
            SingleChatKeys.MESSAGE_COUNT: final_state.get(SingleChatKeys.MESSAGE_COUNT),
            SingleChatKeys.NEWSLETTER_JSON_PATH: final_state.get(SingleChatKeys.NEWSLETTER_JSON_PATH),
            SingleChatKeys.NEWSLETTER_MD_PATH: final_state.get(SingleChatKeys.NEWSLETTER_MD_PATH),
            SingleChatKeys.NEWSLETTER_HTML_PATH: final_state.get(SingleChatKeys.NEWSLETTER_HTML_PATH),
            SingleChatKeys.FINAL_TRANSLATED_FILE_PATH: final_state.get(SingleChatKeys.FINAL_TRANSLATED_FILE_PATH),
            SingleChatKeys.REUSED_EXISTING: final_state.get(SingleChatKeys.REUSED_EXISTING, False),
            # NEW: Include paths needed for cross-chat consolidation
            SingleChatKeys.SEPARATE_DISCUSSIONS_FILE_PATH: final_state.get(SingleChatKeys.SEPARATE_DISCUSSIONS_FILE_PATH),
            SingleChatKeys.DISCUSSIONS_RANKING_FILE_PATH: final_state.get(SingleChatKeys.DISCUSSIONS_RANKING_FILE_PATH),
        }

        logger.info(f"Worker succeeded for chat: {result[SingleChatKeys.CHAT_NAME]}")

        # Return result to be added to chat_results list (via reducer)
        return {OrchestratorKeys.CHAT_RESULTS: [result]}

    except Exception as e:
        # Unexpected exception during worker execution
        chat_name = state.get(SingleChatKeys.CHAT_NAME, "unknown")
        start_date = state.get(SingleChatKeys.START_DATE, "unknown")
        end_date = state.get(SingleChatKeys.END_DATE, "unknown")

        error_msg = f"Worker wrapper caught exception for chat '{chat_name}' " f"(date_range: {start_date} to {end_date}): {e}"
        logger.error(error_msg, exc_info=True)

        error = {
            SingleChatKeys.CHAT_NAME: chat_name,
            SingleChatKeys.START_DATE: start_date,
            SingleChatKeys.END_DATE: end_date,
            "error": str(e),
            "error_type": type(e).__name__,
        }

        # Return error to be added to chat_errors list (via reducer)
        return {OrchestratorKeys.CHAT_ERRORS: [error]}


# ============================================================================
# NODE IMPLEMENTATIONS
# ============================================================================


@with_logging
@with_metrics(node_name=NodeNames.MultiChatConsolidator.ENSURE_VALID_SESSION, workflow_name="parallel_orchestrator")
async def ensure_valid_session(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Ensure Matrix encryption session is fresh by refreshing once at orchestrator level.

    This node runs ONCE before dispatching workers, preventing parallel login attempts
    that cause rate limiting and file conflicts. It refreshes the Matrix session by
    logging in with email/password credentials, ensuring all workers have access to
    current encryption keys.

    Strategy: Always refresh (simpler and more reliable than validation)
    - Logging in takes ~2 seconds
    - Guarantees fresh encryption keys for all workers
    - Eliminates session staleness bugs
    - Prevents M_LIMIT_EXCEEDED errors from parallel logins

    Fail-Fast Conditions:
    - BEEPER_EMAIL or BEEPER_PASSWORD not set in .env
    - Login fails with provided credentials
    - Session refresh fails for any reason

    Args:
        state: ParallelOrchestratorState (uses source_name for extractor)
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Empty dict (no state changes, just ensures session validity)
    """
    from core.ingestion.extractors.beeper import RawDataExtractorBeeper

    logger.info("Node: ensure_valid_session - Starting (orchestrator level)")
    logger.info("🔄 Refreshing Matrix session once before dispatching workers...")

    source_name = state.get(OrchestratorKeys.DATA_SOURCE_NAME, DEFAULT_DATA_SOURCE_FALLBACK)

    try:
        # Get database connection for MongoDB cache
        from db.connection import get_database

        db = await get_database()

        # Create extractor instance to access session methods
        extractor = RawDataExtractorBeeper(source_name=source_name, database=db)

        # Native async call - no manual event loop hack needed with LangGraph 1.0
        await extractor.refresh_session_via_login()

        logger.info("✅ Session refreshed successfully - all workers will use current encryption keys")
        logger.info("Node: ensure_valid_session - Complete")
        return {}

    except Exception as e:
        error_msg = f"Failed to ensure valid session at orchestrator level: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)


@with_metrics(node_name=NodeNames.MultiChatConsolidator.DISPATCH_CHATS, workflow_name="parallel_orchestrator")
async def dispatch_chats(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> Command[Literal["chat_worker"]]:
    """
    Create Send commands for each chat to process in parallel.

    This node creates isolated SingleChatState for each chat and dispatches them
    to the worker subgraph using LangGraph's Send API. Each chat gets its own
    output directory and processes independently.

    Also creates a run document in MongoDB for tracking (fail-soft).

    Fail-Fast Conditions:
    - No chat_names provided (empty list)
    - Invalid base_output_dir (parent directory doesn't exist)

    Args:
        state: ParallelOrchestratorState with chat_names, dates, config
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        Command: Command object with goto containing Send commands for parallel execution

    Raises:
        ValueError: If chat_names is empty
        RuntimeError: If base_output_dir is invalid
    """
    logger.info("Node: dispatch_chats - Starting")

    # Validate required state fields
    validate_orchestrator_state(state, required=["chat_names", "data_source_name", "base_output_dir"])

    # Create run in MongoDB (fail-soft - doesn't block workflow if MongoDB unavailable)
    tracker = get_tracker()
    mongodb_run_id = await tracker.create_run(
        data_source_name=state.get(OrchestratorKeys.DATA_SOURCE_NAME, "unknown"),
        chat_names=state.get(OrchestratorKeys.CHAT_NAMES, []),
        start_date=state.get(OrchestratorKeys.START_DATE, ""),
        end_date=state.get(OrchestratorKeys.END_DATE, ""),
        config={
            "summary_format": state.get(OrchestratorKeys.SUMMARY_FORMAT),
            "desired_language": state.get(OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY),
            "consolidate_chats": state.get(OrchestratorKeys.CONSOLIDATE_CHATS, True),
            "workflow_name": state.get(OrchestratorKeys.WORKFLOW_NAME),
        },
    )
    if mongodb_run_id:
        logger.info(f"MongoDB run created: {mongodb_run_id}")
        await tracker.start_run(mongodb_run_id)

    # Get chat_names (already validated)
    chat_names = state.get(OrchestratorKeys.CHAT_NAMES, [])

    # Validate base_output_dir
    base_output_dir = state[OrchestratorKeys.BASE_OUTPUT_DIR]
    parent_dir = os.path.dirname(base_output_dir) or "."
    if not os.path.exists(parent_dir):
        error_msg = f"Parent directory for base_output_dir does not exist: {parent_dir}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Create base output directory if it doesn't exist
    try:
        os.makedirs(base_output_dir, exist_ok=True)
    except Exception as e:
        error_msg = f"Failed to create base_output_dir {base_output_dir}: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    # Create Send command for each chat
    sends = []

    # Organize per-chat outputs in subdirectory if consolidation is enabled
    consolidate = state.get(OrchestratorKeys.CONSOLIDATE_CHATS, True)
    if consolidate and len(chat_names) > 1:
        # Use per_chat/ subdirectory for organized structure
        per_chat_base = os.path.join(base_output_dir, DIR_NAME_PER_CHAT)
    else:
        # Use base_output_dir directly (backward compatible)
        per_chat_base = base_output_dir

    # Create per-worker copies of the Matrix encryption store to prevent SQLite concurrent access crashes
    import shutil

    canonical_store_path = os.getenv("BEEPER_MATRIX_STORE_PATH", DEFAULT_BEEPER_MATRIX_STORE_PATH)

    for i, chat_name in enumerate(chat_names):
        # Create per-worker copy of the encryption store (prevents SQLite concurrent writer crashes)
        worker_store_path = f"{canonical_store_path}_worker_{i}"
        if os.path.isdir(canonical_store_path):
            if os.path.exists(worker_store_path):
                shutil.rmtree(worker_store_path)
            shutil.copytree(canonical_store_path, worker_store_path)
            logger.info(f"Created worker store copy: {worker_store_path}")
        else:
            worker_store_path = None
            logger.warning(f"Canonical store not found at {canonical_store_path}, skipping worker copy")

        # Create chat-specific output directory path
        # Sanitize chat name for filesystem safety (remove/replace unsafe characters)
        secure_chat_name = re.sub(r'[<>:"/\\|?*]', "_", chat_name).replace(" ", "_").replace("#", "")
        chat_output_dir = os.path.join(per_chat_base, secure_chat_name)

        # Build SingleChatState using factory function
        # Factory provides sensible defaults and ensures all fields are present
        chat_state = create_single_chat_state(
            chat_name=chat_name,
            data_source_name=state[OrchestratorKeys.DATA_SOURCE_NAME],
            start_date=state[OrchestratorKeys.START_DATE],
            end_date=state[OrchestratorKeys.END_DATE],
            output_dir=chat_output_dir,
            summary_format=state[OrchestratorKeys.SUMMARY_FORMAT],
            desired_language=state[OrchestratorKeys.DESIRED_LANGUAGE_FOR_SUMMARY],
            top_k_discussions=state.get(OrchestratorKeys.TOP_K_DISCUSSIONS),
            previous_newsletters_to_consider=state.get(OrchestratorKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER, 5),
            progress_thread_id=state.get(OrchestratorKeys.PROGRESS_THREAD_ID),
            # Worker isolation (per-worker Matrix store copy)
            worker_store_path=worker_store_path,
            # MongoDB integration
            mongodb_run_id=mongodb_run_id,
            # Pass through individual force refresh flags
            force_refresh_extraction=state.get(OrchestratorKeys.FORCE_REFRESH_EXTRACTION, False),
            force_refresh_preprocessing=state.get(OrchestratorKeys.FORCE_REFRESH_PREPROCESSING, False),
            force_refresh_translation=state.get(OrchestratorKeys.FORCE_REFRESH_TRANSLATION, False),
            force_refresh_separate_discussions=state.get(OrchestratorKeys.FORCE_REFRESH_SEPARATE_DISCUSSIONS, False),
            force_refresh_discussions_ranking=state.get(OrchestratorKeys.FORCE_REFRESH_DISCUSSIONS_RANKING, False),
            force_refresh_content=state.get(OrchestratorKeys.FORCE_REFRESH_CONTENT, False),
            force_refresh_link_enrichment=state.get(OrchestratorKeys.FORCE_REFRESH_LINK_ENRICHMENT, False),
            force_refresh_final_translation=state.get(OrchestratorKeys.FORCE_REFRESH_FINAL_TRANSLATION, False),
        )

        # Send to chat_worker subgraph
        sends.append(Send(NodeNames.MultiChatConsolidator.CHAT_WORKER, chat_state))
        logger.info(f"Dispatched chat: {chat_name} to output_dir: {chat_output_dir}")

    logger.info(f"Dispatched {len(sends)} chats for parallel processing")

    # Track parallel worker metrics
    metrics_client = get_metrics_client()
    metrics_client.track_parallel_workers(workflow_name="parallel_orchestrator", active_count=len(chat_names), queue_depth=len(chat_names))

    # Return Command with sends in goto parameter for parallel execution
    # Include mongodb_run_id in state update for downstream nodes
    state_update = {}
    if mongodb_run_id:
        state_update[OrchestratorKeys.MONGODB_RUN_ID] = mongodb_run_id

    return Command(update=state_update, goto=sends)


@with_logging
@with_metrics(node_name=NodeNames.MultiChatConsolidator.AGGREGATE_RESULTS, workflow_name="parallel_orchestrator")
async def aggregate_results(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Collect results from all parallel workers and compute summary statistics.

    This node waits for all chat workers to complete, then aggregates successful
    results and errors. It calculates summary statistics and validates that at
    least some chats succeeded.

    Fail-Fast Conditions:
    - All chats failed (no successful results)

    Args:
        state: ParallelOrchestratorState with chat_results and chat_errors
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: Partial state update with total_chats, successful_chats, failed_chats

    Raises:
        RuntimeError: If all chats failed processing
    """
    logger.info("Node: aggregate_results - Starting")

    # Get aggregated results from reducers
    chat_results = state.get(OrchestratorKeys.CHAT_RESULTS, [])
    chat_errors = state.get(OrchestratorKeys.CHAT_ERRORS, [])

    successful_chats = len(chat_results)
    failed_chats = len(chat_errors)
    total_chats = successful_chats + failed_chats

    logger.info(f"Aggregation summary: {successful_chats}/{total_chats} successful, {failed_chats} failed")

    # Log individual failures for debugging
    if chat_errors:
        logger.warning(f"Failed chats ({failed_chats}):")
        for error in chat_errors:
            logger.warning(f"  - {error.get(SingleChatKeys.CHAT_NAME, 'unknown')}: {error.get('error', 'unknown error')}")

    # Fail-fast: If ALL chats failed, raise error
    if successful_chats == 0:
        error_msg = f"All {total_chats} chats failed processing. Check individual errors in chat_errors field."
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Log successful chats
    logger.info(f"Successful chats ({successful_chats}):")
    for result in chat_results:
        logger.info(f"  - {result.get(SingleChatKeys.CHAT_NAME, 'unknown')}")

    # Update MongoDB run with aggregation metrics (fail-soft)
    mongodb_run_id = state.get(OrchestratorKeys.MONGODB_RUN_ID)
    if mongodb_run_id:
        tracker = get_tracker()

        # Track aggregation stage
        await tracker.update_stage_progress(
            mongodb_run_id,
            "aggregation",
            RunStatus.COMPLETED,
            metadata={
                "total_chats": total_chats,
                "successful_chats": successful_chats,
                "failed_chats": failed_chats,
            },
        )

        # Track each successful chat's status and outputs
        for result in chat_results:
            chat_name = result.get(SingleChatKeys.CHAT_NAME, "unknown")
            await tracker.update_chat_status(
                run_id=mongodb_run_id,
                chat_name=chat_name,
                status=RunStatus.COMPLETED,
                metadata={
                    "message_count": result.get(SingleChatKeys.MESSAGE_COUNT),
                    "discussion_count": result.get("discussion_count", 0),
                },
            )

            # Store output paths
            output_paths = {}
            if result.get(SingleChatKeys.NEWSLETTER_JSON_PATH):
                output_paths["newsletter_json"] = result[SingleChatKeys.NEWSLETTER_JSON_PATH]
            if result.get(SingleChatKeys.NEWSLETTER_MD_PATH):
                output_paths["newsletter_md"] = result[SingleChatKeys.NEWSLETTER_MD_PATH]
            if result.get(SingleChatKeys.NEWSLETTER_HTML_PATH):
                output_paths["newsletter_html"] = result[SingleChatKeys.NEWSLETTER_HTML_PATH]
            if result.get(SingleChatKeys.ENRICHED_NEWSLETTER_MD_PATH):
                output_paths["enriched_md"] = result[SingleChatKeys.ENRICHED_NEWSLETTER_MD_PATH]

            if output_paths:
                await tracker.update_chat_outputs(run_id=mongodb_run_id, chat_name=chat_name, output_paths=output_paths)

        # Track failed chats
        for error in chat_errors:
            chat_name = error.get(SingleChatKeys.CHAT_NAME, "unknown")
            await tracker.update_chat_status(run_id=mongodb_run_id, chat_name=chat_name, status=RunStatus.FAILED, metadata={"error": error.get("error", "unknown error")})

    # Update worker metrics (all workers completed)
    metrics_client = get_metrics_client()
    metrics_client.track_parallel_workers(workflow_name="parallel_orchestrator", active_count=0, queue_depth=0)

    return {OrchestratorKeys.TOTAL_CHATS: total_chats, OrchestratorKeys.SUCCESSFUL_CHATS: successful_chats, OrchestratorKeys.FAILED_CHATS: failed_chats}


# =============================================================================
# EMAIL HELPER FUNCTIONS
# =============================================================================


def _find_best_html_path(state: ParallelOrchestratorState, chat_results: list) -> str | None:
    """
    Find the best available HTML newsletter path.

    Priority order:
    1. Consolidated enriched HTML (cross-chat consolidation with links)
    2. Consolidated base HTML
    3. First successful chat's enriched HTML
    4. First successful chat's base HTML

    Args:
        state: Orchestrator state
        chat_results: List of chat result dictionaries

    Returns:
        Path to HTML file or None if not found
    """
    # Try consolidated paths first (if cross-chat consolidation was enabled)
    consolidated_enriched = state.get(OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH)
    if consolidated_enriched:
        # Replace .md with .html
        html_path = consolidated_enriched.replace(FILE_EXT_MD, FILE_EXT_HTML)
        if os.path.exists(html_path):
            return html_path

    consolidated_base = state.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH)
    if consolidated_base:
        html_path = consolidated_base.replace(FILE_EXT_MD, FILE_EXT_HTML)
        if os.path.exists(html_path):
            return html_path

    # Fall back to first successful chat's HTML
    # All entries in chat_results are successful (failures go to chat_errors)
    logger.info(f"_find_best_html_path: checking {len(chat_results)} chat results. HTML paths: {[(r.get(SingleChatKeys.NEWSLETTER_HTML_PATH), r.get(SingleChatKeys.ENRICHED_NEWSLETTER_MD_PATH)) for r in chat_results]}")
    for result in chat_results:
        # Try enriched HTML first
        enriched_md = result.get(SingleChatKeys.ENRICHED_NEWSLETTER_MD_PATH)
        if enriched_md:
            html_path = enriched_md.replace(FILE_EXT_MD, FILE_EXT_HTML)
            if os.path.exists(html_path):
                return html_path

        # Try base HTML
        newsletter_html = result.get(SingleChatKeys.NEWSLETTER_HTML_PATH)
        if newsletter_html and os.path.exists(newsletter_html):
            return newsletter_html

    return None


def _send_newsletter_email(recipients: list, html_path: str, data_source: str, start_date: str, end_date: str, base_url: str = "") -> None:
    """
    Send newsletter notification email with link to HTML viewer.

    Args:
        recipients: List of email addresses
        html_path: Path to HTML newsletter file
        data_source: Data source name (e.g., "langtalks")
        start_date: Newsletter start date
        end_date: Newsletter end date
        base_url: Base URL for the application (e.g., "http://localhost")

    Raises:
        Exception: If email sending fails
    """
    from core.delivery.email_factory import send_email

    # Build viewer URL
    viewer_url = f"{base_url}/api/newsletter_html_viewer?path={html_path}"

    # Format subject
    date_range = f"{start_date} to {end_date}" if start_date != end_date else start_date
    subject = f"Your {data_source.replace('_', ' ').title()} Newsletter ({date_range})"

    # Build HTML body
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
        <div style="background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
            <h1 style="color: #333; margin-bottom: 20px;">Your Newsletter is Ready! 📬</h1>

            <p style="color: #555; font-size: 16px; line-height: 1.6;">
                Your <strong>{data_source.replace('_', ' ').title()}</strong> newsletter for
                <strong>{date_range}</strong> has been generated successfully.
            </p>

            <p style="margin: 30px 0; text-align: center;">
                <a href="{viewer_url}"
                   style="background-color: #4CAF50; color: white;
                          padding: 14px 28px; text-decoration: none;
                          border-radius: 5px; display: inline-block;
                          font-size: 16px; font-weight: bold;">
                    View Newsletter
                </a>
            </p>

            <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">

            <p style="color: #888; font-size: 12px;">
                If the button doesn't work, copy and paste this link into your browser:<br>
                <code style="background-color: #f0f0f0; padding: 5px; display: inline-block; margin-top: 5px; word-break: break-all;">
                    {viewer_url}
                </code>
            </p>

            <p style="color: #888; font-size: 11px; margin-top: 20px;">
                This email was automatically generated by LangTalks Newsletter.
            </p>
        </div>
    </body>
    </html>
    """

    # Send email using configured provider (Gmail or SendGrid)
    send_email(subject=subject, html_content=html_body, recipient_emails=recipients)

    logger.info(f"Newsletter email sent to {len(recipients)} recipients: {recipients}")


@with_logging
@with_metrics(node_name=NodeNames.MultiChatConsolidator.OUTPUT_HANDLER, workflow_name="parallel_orchestrator")
async def output_handler(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Handle final output based on configured actions.

    This node executes configured output actions (webhook, email, Substack, LinkedIn, etc.)
    based on the output_actions list. Default action is "save_local" (already
    handled by worker nodes).

    Supported Actions:
    - "save_local": Files already saved by worker nodes (no-op here)
    - "webhook": POST results to webhook_url
    - "send_email": Send newsletter notification email
    - "send_substack": Post to Substack blog (stub - not yet implemented)
    - "send_linkedin": Create LinkedIn draft post via n8n webhook

    Delivery Pattern:
    - Infrastructure actions (save_local, webhook) use fail-fast
    - Delivery actions (send_email, send_substack, send_linkedin) use fail-soft
    - All delivery results are collected in delivery_results dict

    Args:
        state: ParallelOrchestratorState with chat_results and output config
        config: LangGraph RunnableConfig for tracing and callbacks

    Returns:
        dict: State update with delivery_results (if any delivery actions were executed)

    Raises:
        ValueError: If invalid action or missing required config for infrastructure actions
        RuntimeError: If webhook fails
    """
    logger.info("Node: output_handler - Starting")

    output_actions = state.get(OrchestratorKeys.OUTPUT_ACTIONS, [OutputAction.SAVE_LOCAL])
    chat_results = state.get(OrchestratorKeys.CHAT_RESULTS, [])
    delivery_results = {}

    logger.info(f"Processing {len(output_actions)} output actions: {output_actions}")

    for action in output_actions:
        if action == OutputAction.SAVE_LOCAL:
            logger.info(f"Action '{OutputAction.SAVE_LOCAL}': Files already saved to disk by worker nodes")
            continue

        elif action == OutputAction.WEBHOOK:
            webhook_url = state.get(OrchestratorKeys.WEBHOOK_URL)
            if not webhook_url:
                error_msg = f"Action '{OutputAction.WEBHOOK}' specified but 'webhook_url' not provided in state"
                logger.error(error_msg)
                raise ValueError(error_msg)

            payload = {"results": chat_results, "summary": {"total_chats": state.get(OrchestratorKeys.TOTAL_CHATS, 0), "successful_chats": state.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0), "failed_chats": state.get(OrchestratorKeys.FAILED_CHATS, 0)}}

            try:
                logger.info(f"Sending webhook to: {webhook_url}")
                async with httpx.AsyncClient() as client:
                    response = await client.post(webhook_url, json=payload, timeout=TIMEOUT_HTTP_REQUEST, headers={HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON})
                response.raise_for_status()
                logger.info(f"Webhook triggered successfully (status: {response.status_code})")
            except httpx.HTTPError as e:
                error_msg = f"Webhook failed for URL {webhook_url}: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e

        elif action == OutputAction.SEND_EMAIL:
            email_recipients = state.get(OrchestratorKeys.EMAIL_RECIPIENTS)
            if not email_recipients:
                error_msg = f"Action '{OutputAction.SEND_EMAIL}' specified but 'email_recipients' not provided in state"
                logger.error(error_msg)
                raise ValueError(error_msg)

            newsletter_html_path = _find_best_html_path(state, chat_results)

            if not newsletter_html_path:
                logger.warning("No HTML newsletter available for email, skipping send_email action")
                delivery_results[OutputAction.SEND_EMAIL] = {"success": False, "error": "No HTML newsletter available"}
                continue

            try:
                await asyncio.to_thread(_send_newsletter_email, recipients=email_recipients, html_path=newsletter_html_path, data_source=state.get(OrchestratorKeys.DATA_SOURCE_NAME, TAG_NEWSLETTER), start_date=state.get(OrchestratorKeys.START_DATE, ""), end_date=state.get(OrchestratorKeys.END_DATE, ""), base_url=os.getenv("APP_BASE_URL", "http://localhost"))
                logger.info(f"Newsletter email sent to {len(email_recipients)} recipients")
                delivery_results[OutputAction.SEND_EMAIL] = {"success": True, "recipients": email_recipients}
            except Exception as e:
                logger.error(f"Failed to send newsletter email: {e}")
                delivery_results[OutputAction.SEND_EMAIL] = {"success": False, "error": str(e)}

        elif action == OutputAction.SEND_SUBSTACK:
            substack_blog_id = state.get(OrchestratorKeys.SUBSTACK_BLOG_ID)
            if not substack_blog_id:
                error_msg = f"Action '{OutputAction.SEND_SUBSTACK}' specified but 'substack_blog_id' not provided in state"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.warning(f"Action '{OutputAction.SEND_SUBSTACK}': Substack delivery not yet implemented. Blog ID: {substack_blog_id}")
            delivery_results[OutputAction.SEND_SUBSTACK] = {"success": False, "error": "Substack delivery not yet implemented"}

        elif action == OutputAction.SEND_LINKEDIN:
            logger.info(f"Action '{OutputAction.SEND_LINKEDIN}': Creating LinkedIn draft via n8n webhook")
            linkedin_result = await asyncio.to_thread(deliver_to_linkedin, state)
            delivery_results[OutputAction.SEND_LINKEDIN] = linkedin_result
            if linkedin_result.get("success"):
                logger.info("LinkedIn draft created successfully")
            else:
                logger.warning(f"LinkedIn delivery failed (fail-soft): {linkedin_result.get('error')}")

        else:
            error_msg = f"Unknown output action: '{action}'. Valid actions: {', '.join(OutputAction)}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    # Log delivery results summary
    if delivery_results:
        successes = sum(1 for r in delivery_results.values() if r.get("success"))
        failures = len(delivery_results) - successes
        logger.info(f"Delivery results: {successes} succeeded, {failures} failed. Details: {delivery_results}")

    # Mark run as complete in MongoDB (fail-soft)
    mongodb_run_id = state.get(OrchestratorKeys.MONGODB_RUN_ID)
    if mongodb_run_id:
        tracker = get_tracker()
        await tracker.complete_run(
            mongodb_run_id,
            output_path=state.get(OrchestratorKeys.BASE_OUTPUT_DIR, ""),
            metrics={
                "total_chats": state.get(OrchestratorKeys.TOTAL_CHATS, 0),
                "successful_chats": state.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0),
                "failed_chats": state.get(OrchestratorKeys.FAILED_CHATS, 0),
                "total_discussions": state.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED),
                "consolidated": state.get(OrchestratorKeys.CONSOLIDATE_CHATS, False),
            },
        )

    logger.info("Output handler completed successfully")
    return {OrchestratorKeys.DELIVERY_RESULTS: delivery_results} if delivery_results else {}


# ============================================================================
# ROUTER FUNCTION
# ============================================================================


def format_timestamp(timestamp_ms: int, format_str: str) -> str:
    """
    Format Unix timestamp in milliseconds to specified format.

    Args:
        timestamp_ms: Unix timestamp in milliseconds
        format_str: strftime format string (e.g., "%H:%M" or "%d.%m.%y")

    Returns:
        Formatted timestamp string
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime(format_str)


def prepare_discussion_selection(state: ParallelOrchestratorState, config: RunnableConfig | None = None) -> dict:
    """
    Prepare ranked discussions for human-in-the-loop selection.

    This node creates a JSON file with all metadata needed for the Web UI
    to display discussions for user selection. After creating this file,
    the workflow ENDS (Phase 1 complete). User will then select discussions
    via Web UI and trigger Phase 2 generation.

    This node only runs for formats that require HITL (e.g., langtalks_format).

    Enriches discussions with:
    - Formatted timestamps (date + time separately)
    - Source chat/group name
    - Participant count
    - Message count
    - Nutshell summary
    - Relevance score
    - Reasoning for inclusion

    Args:
        state: ParallelOrchestratorState with cross_chat_ranking results

    Returns:
        dict: selection_prepared flag and selection_file path

    Raises:
        RuntimeError: If ranking file not found or can't be read
    """
    logger.info("Node: prepare_discussion_selection - Starting")

    # Load ranked discussions from cross-chat consolidation
    consolidated_ranking_file = os.path.join(state[OrchestratorKeys.BASE_OUTPUT_DIR], DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_RANKING, OUTPUT_FILENAME_CROSS_CHAT_RANKING)

    if not os.path.exists(consolidated_ranking_file):
        raise RuntimeError(f"Cross-chat ranking file not found: {consolidated_ranking_file}")

    try:
        with open(consolidated_ranking_file, encoding="utf-8") as f:
            ranking_data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read ranking file: {e}")

    ranked_discussions = ranking_data.get(RankingResultKeys.RANKED_DISCUSSIONS, [])

    # Load full discussion content to get group names
    aggregated_file = os.path.join(state[OrchestratorKeys.BASE_OUTPUT_DIR], DIR_NAME_CONSOLIDATED, DIR_NAME_AGGREGATED_DISCUSSIONS, OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS)

    discussions_lookup = {}
    if os.path.exists(aggregated_file):
        with open(aggregated_file, encoding="utf-8") as f:
            aggregated_data = json.load(f)
            for disc in aggregated_data.get(DiscussionKeys.DISCUSSIONS, []):
                discussions_lookup[disc.get(DiscussionKeys.ID)] = disc

    # Enrich discussions with all required metadata
    enriched_discussions = []
    for disc in ranked_discussions:
        disc_id = disc.get(RankingResultKeys.DISCUSSION_ID)
        original_disc = discussions_lookup.get(disc_id, {})

        enriched = {
            DiscussionKeys.ID: disc_id,
            RankingResultKeys.RANK: disc.get(RankingResultKeys.RANK),
            DiscussionKeys.TITLE: original_disc.get(DiscussionKeys.TITLE, disc.get(DiscussionKeys.TITLE, "")),
            DiscussionKeys.GROUP_NAME: original_disc.get(DiscussionKeys.SOURCE_CHAT, original_disc.get(DiscussionKeys.GROUP_NAME, "")),
            "first_message_date": format_timestamp(disc.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP, 0), "%d.%m.%y"),
            "first_message_time": format_timestamp(disc.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP, 0), "%H:%M"),
            DiscussionKeys.NUM_MESSAGES: disc.get(DiscussionKeys.NUM_MESSAGES, 0),
            DiscussionKeys.NUM_UNIQUE_PARTICIPANTS: disc.get(DiscussionKeys.NUM_UNIQUE_PARTICIPANTS, 0),
            DiscussionKeys.NUTSHELL: original_disc.get(DiscussionKeys.NUTSHELL, ""),
            "relevance_score": disc.get(RankingResultKeys.IMPORTANCE_SCORE, 0),
            "reasoning": disc.get(MergeGroupKeys.REASONING, ""),
        }

        # Add merged discussion metadata if present
        if original_disc.get(DiscussionKeys.IS_MERGED, False):
            enriched[DiscussionKeys.IS_MERGED] = True
            enriched[DiscussionKeys.SOURCE_DISCUSSIONS] = original_disc.get(DiscussionKeys.SOURCE_DISCUSSIONS, [])

            # Format source groups for display (list of groups)
            enriched[DiscussionKeys.SOURCE_GROUPS] = [s.get("group", "Unknown") for s in enriched[DiscussionKeys.SOURCE_DISCUSSIONS]]

        enriched_discussions.append(enriched)

    # Create output directory
    selection_dir = os.path.join(state[OrchestratorKeys.BASE_OUTPUT_DIR], DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_FOR_SELECTION)
    os.makedirs(selection_dir, exist_ok=True)

    # Calculate timeout deadline (configurable, default 0 = automatic selection)
    timeout_minutes = state.get(OrchestratorKeys.HITL_SELECTION_TIMEOUT_MINUTES, 0)  # Default: 0 (automatic selection)
    timeout_deadline = datetime.now() + timedelta(minutes=timeout_minutes)

    logger.info(f"HITL selection timeout: {timeout_minutes} minutes ({timeout_minutes/60:.1f} hours)")
    logger.info(f"Selection expires at: {timeout_deadline.isoformat()}")

    # Create selection file
    selection_file = os.path.join(selection_dir, OUTPUT_FILENAME_RANKED_DISCUSSIONS)
    selection_data = {
        HITL_KEY_PHASE_1_COMPLETE: True,
        HITL_KEY_PHASE_2_READY: False,
        "data_source_name": state.get(OrchestratorKeys.DATA_SOURCE_NAME),
        "summary_format": state.get(OrchestratorKeys.SUMMARY_FORMAT),
        "date_range": f"{state.get(OrchestratorKeys.START_DATE)} to {state.get(OrchestratorKeys.END_DATE)}",
        "run_directory": Path(state[OrchestratorKeys.BASE_OUTPUT_DIR]).name,
        "format_type": state.get(OrchestratorKeys.SUMMARY_FORMAT),
        "discussions": enriched_discussions,
        "total_discussions": len(enriched_discussions),
        HITL_KEY_TIMEOUT_DEADLINE: timeout_deadline.isoformat(),
    }

    with open(selection_file, "w", encoding="utf-8") as f:
        json.dump(selection_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Prepared {len(enriched_discussions)} discussions for selection: {selection_file}")
    logger.info("Phase 1 complete - awaiting user selection via Web UI")

    return {OrchestratorKeys.SELECTION_PREPARED: True, OrchestratorKeys.SELECTION_FILE: selection_file, HITL_KEY_TIMEOUT_DEADLINE: timeout_deadline.isoformat()}


def requires_hitl_selection(state: ParallelOrchestratorState) -> str:
    """
    Router: Check if format requires human-in-the-loop discussion selection.

    HITL is enabled when:
    1. Format is langtalks_format or mcp_israel_format
    2. AND hitl_selection_timeout_minutes > 0 (or not set, defaulting to 0 = automatic)

    Special case: hitl_selection_timeout_minutes = 0 disables HITL (automatic selection)

    If HITL enabled:
    - Route to prepare_discussion_selection
    - Workflow ENDS after that (Phase 1 complete)
    - User selects discussions via Web UI
    - User triggers Phase 2 separately

    If HITL disabled:
    - Continue with existing consolidation flow

    Args:
        state: ParallelOrchestratorState with summary_format and hitl_selection_timeout_minutes

    Returns:
        "hitl" if human selection required (Phase 1 only)
        "continue" if should proceed with full consolidation flow
    """
    summary_format = state.get(OrchestratorKeys.SUMMARY_FORMAT, "")
    timeout_minutes = state.get(OrchestratorKeys.HITL_SELECTION_TIMEOUT_MINUTES, 0)  # Default: 0 (automatic selection)

    hitl_formats = HITL_SUPPORTED_FORMATS

    # Check if format supports HITL
    if summary_format not in hitl_formats:
        logger.info(f"Router: Format '{summary_format}' does not support HITL, continuing full flow")
        return "continue"

    # Check if HITL is disabled (timeout = 0)
    if timeout_minutes == 0:
        logger.info(f"Router: Format '{summary_format}' supports HITL, but timeout=0 (disabled)")
        logger.info("Router: Skipping HITL, continuing with automatic selection")
        return "continue"

    # HITL is enabled
    logger.info(f"Router: Format '{summary_format}' requires HITL selection (timeout: {timeout_minutes} minutes)")
    logger.info("Router: Will prepare discussion selection and END (Phase 1)")
    return "hitl"


def should_consolidate_chats(state: ParallelOrchestratorState) -> str:
    """
    Router: Decide whether to consolidate chats or proceed directly to output.

    Consolidation happens if:
    - consolidate_chats flag is True (default)
    - At least 2 chats succeeded (nothing to consolidate with 1 chat)

    Args:
        state: ParallelOrchestratorState with consolidate_chats flag and successful_chats count

    Returns:
        "consolidate" if consolidation should proceed
        "skip" if should go directly to output_handler
    """
    consolidate = state.get(OrchestratorKeys.CONSOLIDATE_CHATS, True)  # Default: True
    successful_chats = state.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0)

    if consolidate and successful_chats > 1:
        logger.info(f"Router: Consolidating {successful_chats} chats")
        return "consolidate"
    else:
        if not consolidate:
            logger.info("Router: Consolidation disabled (consolidate_chats=False)")
        elif successful_chats <= 1:
            logger.info(f"Router: Only {successful_chats} chat(s) succeeded, skipping consolidation")
        return "skip"


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================


def build_parallel_orchestrator_graph() -> StateGraph:
    """
    Build and compile the parent orchestrator graph for parallel chat processing.

    This graph coordinates parallel processing of multiple chats by:
    1. Dispatching each chat to the worker subgraph using Send API
    2. Waiting for all workers to complete
    3. Aggregating results and computing statistics
    4. [NEW] Optionally consolidating all chats into single newsletter
    5. [NEW] For HITL formats: Preparing discussion selection and ENDING (Phase 1)
    6. For non-HITL formats: Continuing with full newsletter generation
    7. Handling final output (webhooks, email, etc.)

    Graph Structure (HITL formats like langtalks_format) - TWO-PHASE:
    Phase 1:
    START → dispatch_chats → [chat_worker (parallel)] → aggregate_results
          → setup_consolidated_directories → consolidate_discussions
          → rank_consolidated_discussions → prepare_discussion_selection → END

    Phase 2 (triggered separately after user selects discussions):
    (See langtalks_generator.py for Phase 2 generation)

    Graph Structure (non-HITL formats) - SINGLE PHASE:
    START → dispatch_chats → [chat_worker (parallel)] → aggregate_results
          → setup_consolidated_directories → consolidate_discussions
          → rank_consolidated_discussions → generate_consolidated_newsletter
          → enrich_consolidated_newsletter → translate_consolidated_newsletter
          → output_handler → END

    Graph Structure (without consolidation):
    START → dispatch_chats → [chat_worker (parallel)] → aggregate_results
          → output_handler → END

    Key Features:
    - Dynamic parallel execution via Send API
    - Isolated state for each chat (SingleChatState)
    - Result aggregation with reducers (chat_results, chat_errors)
    - Cross-chat consolidation (optional, enabled by default)
    - Human-in-the-loop selection for certain formats (langtalks_format, mcp_israel_format)
    - Checkpointing for resumability

    Returns:
        Compiled StateGraph with checkpointing enabled

    Notes:
    - Uses newsletter_generation_graph as the "chat_worker" subgraph
    - Checkpointer configured with MemorySaver (use SqliteSaver for production)
    - Each worker failure is isolated (doesn't stop other workers)
    - Fail-fast only if ALL workers fail
    - Consolidation only triggers if consolidate_chats=True and >1 successful chats
    - HITL formats end after discussion selection preparation (Phase 1 only)
    """
    logger.info("Building parallel orchestrator graph with cross-chat consolidation support...")

    # Create graph builder with ParallelOrchestratorState
    builder = StateGraph(ParallelOrchestratorState)

    # Add session validation node (runs once before workers)
    builder.add_node(NodeNames.MultiChatConsolidator.ENSURE_VALID_SESSION, ensure_valid_session)

    # Add per-chat processing nodes
    builder.add_node(NodeNames.MultiChatConsolidator.DISPATCH_CHATS, dispatch_chats)
    builder.add_node(NodeNames.MultiChatConsolidator.CHAT_WORKER, chat_worker_wrapper)
    builder.add_node(NodeNames.MultiChatConsolidator.AGGREGATE_RESULTS, aggregate_results)
    builder.add_node(NodeNames.MultiChatConsolidator.OUTPUT_HANDLER, output_handler)

    # Add cross-chat consolidation nodes
    builder.add_node(NodeNames.MultiChatConsolidator.SETUP_CONSOLIDATED_DIRECTORIES, setup_consolidated_directories)
    builder.add_node(NodeNames.MultiChatConsolidator.CONSOLIDATE_DISCUSSIONS, consolidate_discussions)
    builder.add_node(NodeNames.MultiChatConsolidator.MERGE_SIMILAR_DISCUSSIONS, merge_similar_discussions)
    builder.add_node(NodeNames.MultiChatConsolidator.RANK_CONSOLIDATED_DISCUSSIONS, rank_consolidated_discussions)
    builder.add_node(NodeNames.MultiChatConsolidator.SET_FOR_HUMAN_IN_THE_LOOP, prepare_discussion_selection)  # HITL node
    builder.add_node(NodeNames.MultiChatConsolidator.GENERATE_CONSOLIDATED_NEWSLETTER, generate_consolidated_newsletter)
    builder.add_node(NodeNames.MultiChatConsolidator.RELATED_LINKS_ENRICHMENT, enrich_consolidated_newsletter)
    builder.add_node(NodeNames.MultiChatConsolidator.TRANSLATE_CONSOLIDATED_NEWSLETTER, translate_consolidated_newsletter)

    # Define edges for per-chat processing
    builder.add_edge(START, NodeNames.MultiChatConsolidator.ENSURE_VALID_SESSION)
    builder.add_edge(NodeNames.MultiChatConsolidator.ENSURE_VALID_SESSION, NodeNames.MultiChatConsolidator.DISPATCH_CHATS)
    # dispatch_chats returns Send commands that route to chat_worker (parallel)
    builder.add_edge(NodeNames.MultiChatConsolidator.CHAT_WORKER, NodeNames.MultiChatConsolidator.AGGREGATE_RESULTS)

    # Conditional routing after aggregation
    builder.add_conditional_edges(
        NodeNames.MultiChatConsolidator.AGGREGATE_RESULTS,
        should_consolidate_chats,
        {
            "consolidate": NodeNames.MultiChatConsolidator.SETUP_CONSOLIDATED_DIRECTORIES,
            "skip": NodeNames.MultiChatConsolidator.OUTPUT_HANDLER,  # Skip consolidation, go directly to output handler
        },
    )

    # Define edges for consolidation flow (linear)
    builder.add_edge(NodeNames.MultiChatConsolidator.SETUP_CONSOLIDATED_DIRECTORIES, NodeNames.MultiChatConsolidator.CONSOLIDATE_DISCUSSIONS)
    builder.add_edge(NodeNames.MultiChatConsolidator.CONSOLIDATE_DISCUSSIONS, NodeNames.MultiChatConsolidator.MERGE_SIMILAR_DISCUSSIONS)
    builder.add_edge(NodeNames.MultiChatConsolidator.MERGE_SIMILAR_DISCUSSIONS, NodeNames.MultiChatConsolidator.RANK_CONSOLIDATED_DISCUSSIONS)

    # Conditional routing after ranking - check if HITL required
    builder.add_conditional_edges(
        NodeNames.MultiChatConsolidator.RANK_CONSOLIDATED_DISCUSSIONS,
        requires_hitl_selection,
        {
            "hitl": NodeNames.MultiChatConsolidator.SET_FOR_HUMAN_IN_THE_LOOP,  # Phase 1 only - END after this
            "continue": NodeNames.MultiChatConsolidator.GENERATE_CONSOLIDATED_NEWSLETTER,  # Full flow - continue to generation
        },
    )

    # HITL path: After preparing selection, END workflow (Phase 1 complete)
    builder.add_edge(NodeNames.MultiChatConsolidator.SET_FOR_HUMAN_IN_THE_LOOP, END)

    # Continue path: Full consolidation flow
    builder.add_edge(NodeNames.MultiChatConsolidator.GENERATE_CONSOLIDATED_NEWSLETTER, NodeNames.MultiChatConsolidator.RELATED_LINKS_ENRICHMENT)

    # Agentic loop: conditional edge allows cycling back for re-enrichment (placeholder — always continues for now)
    def should_retry_enrichment(state: ParallelOrchestratorState) -> str:
        return "continue"

    builder.add_conditional_edges(
        NodeNames.MultiChatConsolidator.RELATED_LINKS_ENRICHMENT,
        should_retry_enrichment,
        {
            "retry": NodeNames.MultiChatConsolidator.RELATED_LINKS_ENRICHMENT,
            "continue": NodeNames.MultiChatConsolidator.TRANSLATE_CONSOLIDATED_NEWSLETTER,
        },
    )
    builder.add_edge(NodeNames.MultiChatConsolidator.TRANSLATE_CONSOLIDATED_NEWSLETTER, NodeNames.MultiChatConsolidator.OUTPUT_HANDLER)

    # Final edge to END
    builder.add_edge(NodeNames.MultiChatConsolidator.OUTPUT_HANDLER, END)

    compiled_graph = builder.compile()

    logger.info("Parallel orchestrator graph compiled successfully")
    logger.info("Graph includes cross-chat consolidation flow (enabled by default)")
    logger.info("Primary flow: START → dispatch_chats → [chat_worker*] → aggregate_results → [consolidate*] → output_handler → END")

    return compiled_graph


# Create and export the compiled graph
parallel_orchestrator_graph = build_parallel_orchestrator_graph()
