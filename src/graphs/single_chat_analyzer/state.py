"""
State Schema for Single Chat Analyzer Graph

Defines the TypedDict state schema for processing individual chats through
the newsletter generation pipeline.

Design Philosophy:
- File-based state: Store file paths (strings), not file contents
- Explicit field documentation for maintainability
- Fail-fast: Required fields must be present or raise errors
"""

from typing import Literal
from typing_extensions import TypedDict

from constants import DEFAULT_LANGUAGE, DataSources, WorkflowNames


class SingleChatState(TypedDict):
    """
    State for processing a single chat through the newsletter generation pipeline.

    This state is used for both periodic newsletters and daily summaries - the only
    difference is date handling (start_date == end_date for daily summaries).

    Architecture Notes:
    - File paths are immutable strings (no reducers needed)
    - Each node checks file existence before processing
    - Force refresh flags override file existence checks
    - Dual path tracking: expected_* (for checks) vs. *_path (actual results)
    """

    # === Input Fields (Required) ===
    workflow_name: Literal["periodic_newsletter"]  # Workflow type
    data_source_type: str  # Always "whatsapp_group_chat_messages"
    data_source_name: str  # "langtalks" or "mcp"
    chat_name: str  # WhatsApp group name
    start_date: str  # ISO format "YYYY-MM-DD"
    end_date: str  # ISO format "YYYY-MM-DD" (same as start_date for daily summaries)
    desired_language_for_summary: str  # Target language for final summary
    summary_format: str  # "mcp_israel_format" or "langtalks_format"
    output_dir: str  # Base output directory for this chat's processing

    # === Force Refresh Flags (Optional) ===
    # These flags override file existence checks and force reprocessing
    force_refresh_extraction: bool | None
    force_refresh_preprocessing: bool | None
    force_refresh_translation: bool | None
    force_refresh_separate_discussions: bool | None
    force_refresh_discussions_ranking: bool | None
    force_refresh_content: bool | None
    force_refresh_link_enrichment: bool | None  # For link enrichment subgraph
    force_refresh_final_translation: bool | None

    # === Directory Paths (Set by setup_directories node) ===
    # These are Optional because they're populated during workflow execution
    extraction_dir: str | None  # Directory for extracted messages
    preprocess_dir: str | None  # Directory for preprocessed messages
    translation_dir: str | None  # Directory for translated messages
    separate_discussions_dir: str | None  # Directory for discussion separation
    discussions_ranking_dir: str | None  # Directory for discussion ranking results
    content_dir: str | None  # Directory for generated newsletter content
    link_enrichment_dir: str | None  # Directory for link enrichment results
    final_translated_content_dir: str | None  # Directory for final translated summary

    # === Expected File Paths (Set by setup_directories node) ===
    # These are the paths where files SHOULD exist (used for existence checks)
    # Also Optional because they're set by setup_directories node
    expected_extracted_file: str | None
    expected_preprocessed_file: str | None
    expected_translated_file: str | None
    expected_separate_discussions_file: str | None
    expected_discussions_ranking_file: str | None
    expected_newsletter_json: str | None
    expected_newsletter_md: str | None
    expected_newsletter_html: str | None  # Only for periodic newsletter
    expected_enriched_newsletter_json: str | None  # Expected enriched newsletter JSON
    expected_enriched_newsletter_md: str | None  # Expected enriched newsletter MD
    expected_final_translated_file: str | None

    # === Actual File Paths (Set by processing nodes) ===
    # These are the actual paths returned by processing nodes (may differ from expected)
    # NOTE: These fields are STILL REQUIRED for inter-node communication.
    # Removal blocked until Phase 6 MongoDB migration implements inter-node data passing
    # via MongoDB documents instead of file paths. See: knowledge/plans/AUDIT_IMPROVEMENT_PLAN.md
    extracted_file_path: str | None  # Result from extract_messages node
    preprocessed_file_path: str | None  # Result from preprocess_messages node
    translated_file_path: str | None  # Result from translate_messages node
    separate_discussions_file_path: str | None  # Result from separate_discussions node
    discussions_ranking_file_path: str | None  # Result from discussions_ranker node
    newsletter_json_path: str | None  # Result from generate_content node (used by enrich_with_links)
    newsletter_md_path: str | None  # Result from generate_content node
    newsletter_html_path: str | None  # Result from generate_content node (periodic only)
    enriched_newsletter_json_path: str | None  # Result from enrich_with_links node
    enriched_newsletter_md_path: str | None  # Result from enrich_with_links node (used by translate_final_summary)
    final_translated_file_path: str | None  # Result from translate_final_summary node

    # === MongoDB Newsletter IDs (Primary - MongoDB-First Architecture) ===
    newsletter_id: str | None  # MongoDB newsletter ID (format: {run_id}_nl_{chat_slug})
    original_newsletter_id: str | None  # Tracking ID for original version
    enriched_newsletter_id: str | None  # Tracking ID for enriched version (same as newsletter_id)

    # === Processing Metadata ===
    message_count: int | None  # Number of messages processed
    reused_existing: bool | None  # Whether existing files were reused (not regenerated)
    slm_filter_stats: dict | None  # SLM pre-filter statistics (from slm_prefilter node)

    # === Worker Isolation ===
    worker_store_path: str | None  # Per-worker copy of Matrix encryption store (prevents SQLite concurrent access)

    # === MongoDB Integration ===
    mongodb_run_id: str | None  # MongoDB run ID for persistence tracking

    # === Top-K Discussions Configuration ===
    top_k_discussions: int | None  # Number of discussions to feature (default: 5)

    # === Anti-Repetition Configuration ===
    previous_newsletters_to_consider: int | None  # Max previous newsletters to check (default: 5, 0 disables)

    # === Progress Tracking (Optional - for SSE streaming) ===
    progress_thread_id: str | None  # Thread ID for looking up progress queue from registry


# ============================================================================
# STATE FACTORY FUNCTION
# ============================================================================


def create_single_chat_state(*, chat_name: str, data_source_name: str, start_date: str, end_date: str, output_dir: str, summary_format: str, desired_language: str = DEFAULT_LANGUAGE, force_refresh_all: bool = False, top_k_discussions: int | None = None, previous_newsletters_to_consider: int | None = 5, progress_thread_id: str | None = None, **kwargs) -> SingleChatState:
    """
    Factory function for creating SingleChatState with sensible defaults.

    This reduces boilerplate when creating state, especially in dispatch_chats
    where state is created for each chat worker.

    Args:
        chat_name: WhatsApp group name (case-sensitive)
        data_source_name: "langtalks", "mcp_israel", or "n8n_israel"
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        output_dir: Base output directory for this chat
        summary_format: "langtalks_format" or "mcp_israel_format"
        desired_language: Target language (default: DEFAULT_LANGUAGE)
        force_refresh_all: Set all refresh flags to True (default: False)
        top_k_discussions: Number of discussions to feature (default: uses config)
        previous_newsletters_to_consider: Max previous newsletters for anti-repetition (default: 5)
        progress_thread_id: Thread ID for SSE progress tracking
        **kwargs: Override any specific refresh flag (e.g., force_refresh_extraction=True)

    Returns:
        Properly initialized SingleChatState with all required fields

    Example:
        state = create_single_chat_state(
            chat_name="LangTalks Community",
            data_source_name="langtalks",
            start_date="2025-01-01",
            end_date="2025-01-14",
            output_dir="/output/langtalks",
            summary_format=SummaryFormats.LANGTALKS_FORMAT,
            force_refresh_extraction=True  # Only refresh extraction
        )
    """
    refresh_value = force_refresh_all

    state: SingleChatState = {
        # === Input Fields (Required) ===
        "workflow_name": WorkflowNames.PERIODIC_NEWSLETTER,
        "data_source_type": DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
        "data_source_name": data_source_name,
        "chat_name": chat_name,
        "start_date": start_date,
        "end_date": end_date,
        "desired_language_for_summary": desired_language,
        "summary_format": summary_format,
        "output_dir": output_dir,
        # === Force Refresh Flags ===
        "force_refresh_extraction": kwargs.get("force_refresh_extraction", refresh_value),
        "force_refresh_preprocessing": kwargs.get("force_refresh_preprocessing", refresh_value),
        "force_refresh_translation": kwargs.get("force_refresh_translation", refresh_value),
        "force_refresh_separate_discussions": kwargs.get("force_refresh_separate_discussions", refresh_value),
        "force_refresh_discussions_ranking": kwargs.get("force_refresh_discussions_ranking", refresh_value),
        "force_refresh_content": kwargs.get("force_refresh_content", refresh_value),
        "force_refresh_link_enrichment": kwargs.get("force_refresh_link_enrichment", refresh_value),
        "force_refresh_final_translation": kwargs.get("force_refresh_final_translation", refresh_value),
        # === Directory Paths (Set by setup_directories node) ===
        "extraction_dir": None,
        "preprocess_dir": None,
        "translation_dir": None,
        "separate_discussions_dir": None,
        "discussions_ranking_dir": None,
        "content_dir": None,
        "link_enrichment_dir": None,
        "final_translated_content_dir": None,
        # === Expected File Paths (Set by setup_directories node) ===
        "expected_extracted_file": None,
        "expected_preprocessed_file": None,
        "expected_translated_file": None,
        "expected_separate_discussions_file": None,
        "expected_discussions_ranking_file": None,
        "expected_newsletter_json": None,
        "expected_newsletter_md": None,
        "expected_newsletter_html": None,
        "expected_enriched_newsletter_json": None,
        "expected_enriched_newsletter_md": None,
        "expected_final_translated_file": None,
        # === Actual File Paths (Set by processing nodes) ===
        # DEPRECATED: For backward compatibility only
        "extracted_file_path": None,
        "preprocessed_file_path": None,
        "translated_file_path": None,
        "separate_discussions_file_path": None,
        "discussions_ranking_file_path": None,
        "newsletter_json_path": None,
        "newsletter_md_path": None,
        "newsletter_html_path": None,
        "enriched_newsletter_json_path": None,
        "enriched_newsletter_md_path": None,
        "final_translated_file_path": None,
        # === MongoDB Newsletter IDs (Primary) ===
        "newsletter_id": None,
        "original_newsletter_id": None,
        "enriched_newsletter_id": None,
        # === Processing Metadata ===
        "message_count": None,
        "reused_existing": None,
        "slm_filter_stats": None,
        # === Worker Isolation ===
        "worker_store_path": kwargs.get("worker_store_path"),
        # === MongoDB Integration ===
        "mongodb_run_id": kwargs.get("mongodb_run_id"),
        # === Configuration ===
        "top_k_discussions": top_k_discussions,
        "previous_newsletters_to_consider": previous_newsletters_to_consider,
        # === Progress Tracking ===
        "progress_thread_id": progress_thread_id,
    }

    return state
