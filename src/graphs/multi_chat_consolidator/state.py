"""
State Schema for Multi-Chat Consolidator Graph

Defines the TypedDict state schema for orchestrating parallel processing of
multiple chats and consolidating results.

Design Philosophy:
- Uses reducers for aggregating results from parallel workers
- File-based state: Store file paths, not contents
- Fail-fast for configuration errors, partial success for individual chats
"""

import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict


class ParallelOrchestratorState(TypedDict):
    """
    Parent state for orchestrating parallel processing of multiple chats.

    Uses LangGraph Send API to dispatch individual chats to worker subgraphs,
    then aggregates results. Optionally consolidates all chats into a single
    final newsletter (enabled by default).

    Architecture Notes:
    - Uses Send API for dynamic parallel execution
    - Reducers on chat_results/chat_errors aggregate worker outputs
    - Each worker gets isolated SingleChatState
    - Parent waits for all workers before finalizing
    - Cross-chat consolidation merges all chat outputs into one newsletter
    """

    # === Input Fields (Required) ===
    workflow_name: Literal["periodic_newsletter"]  # Workflow type
    data_source_name: str  # "langtalks" or "mcp"
    chat_names: list[str]  # Multiple chats to process in parallel
    start_date: str  # ISO format "YYYY-MM-DD"
    end_date: str  # ISO format "YYYY-MM-DD"
    desired_language_for_summary: str  # Target language for summaries
    summary_format: str  # "mcp_israel_format" or "langtalks_format"
    base_output_dir: str  # Parent directory for all chat outputs

    # === Force Refresh Flags (Applied to all chats) ===
    force_refresh_extraction: bool | None
    force_refresh_preprocessing: bool | None
    force_refresh_translation: bool | None
    force_refresh_separate_discussions: bool | None
    force_refresh_content: bool | None
    force_refresh_discussions_ranking: bool | None
    force_refresh_link_enrichment: bool | None
    force_refresh_final_translation: bool | None

    # === Cross-Chat Consolidation Flags ===
    consolidate_chats: bool | None  # Enable cross-chat consolidation (default: True)
    force_refresh_cross_chat_aggregation: bool | None  # Force re-aggregation across chats
    force_refresh_cross_chat_ranking: bool | None  # Force re-ranking across chats
    force_refresh_consolidated_content: bool | None  # Force re-generation of consolidated newsletter
    force_refresh_consolidated_link_enrichment: bool | None  # Force re-enrichment of consolidated newsletter
    force_refresh_consolidated_translation: bool | None  # Force re-translation of consolidated newsletter

    # === Top-K Discussions Configuration ===
    top_k_discussions: int | None  # Number of discussions to feature (default: 5)

    # === Anti-Repetition Configuration ===
    previous_newsletters_to_consider: int | None  # Max previous newsletters to check (default: 5, 0 disables)

    # === Discussion Merging Configuration ===
    enable_discussion_merging: bool | None  # Enable merging of similar discussions (default: True for multi-chat)
    similarity_threshold: str | None  # "strict" | "moderate" | "aggressive" (default: "moderate")

    # === Discussion Merging Results ===
    merged_discussions_file_path: str | None  # Path to merged discussions JSON
    num_discussions_before_merge: int | None  # Original discussion count before merging
    num_discussions_after_merge: int | None  # Discussion count after merging
    merge_operations_count: int | None  # Number of merge operations performed

    # === Output Handler Configuration ===
    # Configurable actions for handling final output
    # Supported actions: "save_local", "webhook", "send_email", "send_substack"
    output_actions: list[str] | None
    webhook_url: str | None  # For "webhook" action
    email_recipients: list[str] | None  # For "send_email" action
    substack_blog_id: str | None  # For "send_substack" action

    # === Aggregation Fields (With Reducers) ===
    # Collect results from all parallel chat workers
    # operator.add appends to list as workers complete
    chat_results: Annotated[list[dict], operator.add]  # Successful chat results
    chat_errors: Annotated[list[dict], operator.add]  # Failed chat results with errors

    # === Output Fields (Final Statistics) ===
    # These are set by aggregate_results node, so they're Optional during initialization
    total_chats: int | None  # Total number of chats processed
    successful_chats: int | None  # Number of successful completions
    failed_chats: int | None  # Number of failures

    # === Cross-Chat Consolidation Directory Paths ===
    # Set by setup_consolidated_directories node
    consolidated_output_dir: str | None  # Base directory for consolidated outputs
    consolidated_aggregated_discussions_dir: str | None  # Directory for aggregated discussions
    consolidated_ranking_dir: str | None  # Directory for cross-chat rankings
    consolidated_newsletter_dir: str | None  # Directory for consolidated newsletter
    consolidated_enrichment_dir: str | None  # Directory for link enrichment
    consolidated_translation_dir: str | None  # Directory for final translation

    # === Cross-Chat Consolidation Expected File Paths ===
    # Set by setup_consolidated_directories node
    expected_consolidated_aggregated_discussions_file: str | None
    expected_consolidated_ranking_file: str | None
    expected_consolidated_newsletter_json: str | None
    expected_consolidated_newsletter_md: str | None
    expected_consolidated_enriched_json: str | None
    expected_consolidated_enriched_md: str | None
    expected_consolidated_translated_file: str | None

    # === Cross-Chat Consolidation Actual File Paths ===
    # Set by consolidation nodes
    # NOTE: These fields are STILL REQUIRED for inter-node communication.
    # Removal blocked until Phase 6 MongoDB migration implements inter-node data passing
    # via MongoDB documents instead of file paths. See: knowledge/plans/AUDIT_IMPROVEMENT_PLAN.md
    consolidated_aggregated_discussions_path: str | None  # Result from consolidate_discussions
    consolidated_ranking_path: str | None  # Result from rank_consolidated_discussions
    consolidated_newsletter_json_path: str | None  # Result from generate_consolidated_newsletter
    consolidated_newsletter_md_path: str | None  # Result from generate_consolidated_newsletter
    consolidated_enriched_json_path: str | None  # Result from enrich_consolidated_newsletter
    consolidated_enriched_md_path: str | None  # Result from enrich_consolidated_newsletter
    consolidated_translated_path: str | None  # Result from translate_consolidated_newsletter

    # === MongoDB Consolidated Newsletter IDs (Primary - MongoDB-First Architecture) ===
    consolidated_newsletter_id: str | None  # MongoDB newsletter ID for consolidated newsletter

    # === Cross-Chat Consolidation Metadata ===
    total_discussions_consolidated: int | None  # Total discussions from all chats
    total_messages_consolidated: int | None  # Total messages from all chats
    source_chats_in_consolidated: list[str] | None  # Chat names included in consolidation

    # === Delivery Results ===
    delivery_results: dict | None  # Per-destination delivery outcomes: {"send_linkedin": {"success": True, ...}, ...}

    # === Phase 2 HITL Selection Fields ===
    hitl_selection_timeout_minutes: int | None  # HITL timeout in minutes (0 = disabled/automatic)
    selection_prepared: bool | None  # Flag indicating discussion selection is ready for user
    selection_file: str | None  # Path to ranked_discussions.json for HITL selection UI

    # === Progress Tracking (Optional - for SSE streaming) ===
    progress_thread_id: str | None  # Thread ID for looking up progress queue from registry

    # === MongoDB Run Tracking (Optional - for dual-write) ===
    mongodb_run_id: str | None  # Run ID in MongoDB for tracking/analytics
