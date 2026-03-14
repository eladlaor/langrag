"""
State key constants for LangGraph workflows.

CRITICAL: All state dictionary access MUST use these constants.
Never hardcode state keys as strings - use these constants instead.

This prevents typos, enables refactoring, and provides IDE autocomplete support.

Usage:
    from graphs.state_keys import SingleChatStateKeys as Keys

    # ✅ GOOD
    chat_name = state[Keys.CHAT_NAME]
    json_path = result.get(Keys.NEWSLETTER_JSON_PATH)

    # ❌ BAD (brittle, typo-prone)
    chat_name = state["chat_name"]
    json_path = result.get("newsletter_json_path")
"""


class SingleChatStateKeys:
    """Keys for SingleChatState TypedDict (single chat newsletter generation)."""

    # === Input Fields (Required) ===
    WORKFLOW_NAME = "workflow_name"
    DATA_SOURCE_TYPE = "data_source_type"
    DATA_SOURCE_NAME = "data_source_name"
    CHAT_NAME = "chat_name"
    START_DATE = "start_date"
    END_DATE = "end_date"
    DESIRED_LANGUAGE_FOR_SUMMARY = "desired_language_for_summary"
    SUMMARY_FORMAT = "summary_format"
    OUTPUT_DIR = "output_dir"

    # === Force Refresh Flags (Optional) ===
    FORCE_REFRESH_EXTRACTION = "force_refresh_extraction"
    FORCE_REFRESH_PREPROCESSING = "force_refresh_preprocessing"
    FORCE_REFRESH_TRANSLATION = "force_refresh_translation"
    FORCE_REFRESH_SEPARATE_DISCUSSIONS = "force_refresh_separate_discussions"
    FORCE_REFRESH_DISCUSSIONS_RANKING = "force_refresh_discussions_ranking"
    FORCE_REFRESH_CONTENT = "force_refresh_content"
    FORCE_REFRESH_LINK_ENRICHMENT = "force_refresh_link_enrichment"
    FORCE_REFRESH_FINAL_TRANSLATION = "force_refresh_final_translation"

    # === Directory Paths (Set by setup_directories node) ===
    EXTRACTION_DIR = "extraction_dir"
    PREPROCESS_DIR = "preprocess_dir"
    TRANSLATION_DIR = "translation_dir"
    SEPARATE_DISCUSSIONS_DIR = "separate_discussions_dir"
    DISCUSSIONS_RANKING_DIR = "discussions_ranking_dir"
    CONTENT_DIR = "content_dir"
    LINK_ENRICHMENT_DIR = "link_enrichment_dir"
    FINAL_TRANSLATED_CONTENT_DIR = "final_translated_content_dir"

    # === Expected File Paths (Set by setup_directories node) ===
    EXPECTED_EXTRACTED_FILE = "expected_extracted_file"
    EXPECTED_PREPROCESSED_FILE = "expected_preprocessed_file"
    EXPECTED_TRANSLATED_FILE = "expected_translated_file"
    EXPECTED_SEPARATE_DISCUSSIONS_FILE = "expected_separate_discussions_file"
    EXPECTED_DISCUSSIONS_RANKING_FILE = "expected_discussions_ranking_file"
    EXPECTED_NEWSLETTER_JSON = "expected_newsletter_json"
    EXPECTED_NEWSLETTER_MD = "expected_newsletter_md"
    EXPECTED_NEWSLETTER_HTML = "expected_newsletter_html"
    EXPECTED_ENRICHED_NEWSLETTER_JSON = "expected_enriched_newsletter_json"
    EXPECTED_ENRICHED_NEWSLETTER_MD = "expected_enriched_newsletter_md"
    EXPECTED_FINAL_TRANSLATED_FILE = "expected_final_translated_file"

    # === Actual File Paths (Set by processing nodes) ===
    # NOTE: These fields are STILL REQUIRED for inter-node communication.
    # See: knowledge/plans/AUDIT_IMPROVEMENT_PLAN.md
    EXTRACTED_FILE_PATH = "extracted_file_path"
    PREPROCESSED_FILE_PATH = "preprocessed_file_path"
    TRANSLATED_FILE_PATH = "translated_file_path"
    SEPARATE_DISCUSSIONS_FILE_PATH = "separate_discussions_file_path"
    DISCUSSIONS_RANKING_FILE_PATH = "discussions_ranking_file_path"
    NEWSLETTER_JSON_PATH = "newsletter_json_path"
    NEWSLETTER_MD_PATH = "newsletter_md_path"
    NEWSLETTER_HTML_PATH = "newsletter_html_path"
    ENRICHED_NEWSLETTER_JSON_PATH = "enriched_newsletter_json_path"
    ENRICHED_NEWSLETTER_MD_PATH = "enriched_newsletter_md_path"
    FINAL_TRANSLATED_FILE_PATH = "final_translated_file_path"

    # === MongoDB Newsletter IDs (Primary - MongoDB-First Architecture) ===
    NEWSLETTER_ID = "newsletter_id"
    ORIGINAL_NEWSLETTER_ID = "original_newsletter_id"
    ENRICHED_NEWSLETTER_ID = "enriched_newsletter_id"

    # === Worker Store Path (for parallel workers) ===
    WORKER_STORE_PATH = "worker_store_path"

    # === Processing Metadata ===
    MESSAGE_COUNT = "message_count"
    REUSED_EXISTING = "reused_existing"

    # === MongoDB Integration ===
    MONGODB_RUN_ID = "mongodb_run_id"

    # === Top-K Discussions Configuration ===
    TOP_K_DISCUSSIONS = "top_k_discussions"

    # === Anti-Repetition Configuration ===
    PREVIOUS_NEWSLETTERS_TO_CONSIDER = "previous_newsletters_to_consider"

    # === Progress Tracking (Optional - for SSE streaming) ===
    PROGRESS_THREAD_ID = "progress_thread_id"

    # === Langfuse Trace Context (Optional) ===
    LANGFUSE_TRACE_ID = "langfuse_trace_id"
    LANGFUSE_SESSION_ID = "langfuse_session_id"
    LANGFUSE_USER_ID = "langfuse_user_id"


class ParallelOrchestratorStateKeys:
    """Keys for ParallelOrchestratorState TypedDict (multi-chat orchestration)."""

    # === Input Fields (Required) ===
    WORKFLOW_NAME = "workflow_name"
    DATA_SOURCE_NAME = "data_source_name"
    CHAT_NAMES = "chat_names"
    START_DATE = "start_date"
    END_DATE = "end_date"
    DESIRED_LANGUAGE_FOR_SUMMARY = "desired_language_for_summary"
    SUMMARY_FORMAT = "summary_format"
    BASE_OUTPUT_DIR = "base_output_dir"

    # === Force Refresh Flags (Applied to all chats) ===
    FORCE_REFRESH_EXTRACTION = "force_refresh_extraction"
    FORCE_REFRESH_PREPROCESSING = "force_refresh_preprocessing"
    FORCE_REFRESH_TRANSLATION = "force_refresh_translation"
    FORCE_REFRESH_SEPARATE_DISCUSSIONS = "force_refresh_separate_discussions"
    FORCE_REFRESH_CONTENT = "force_refresh_content"
    FORCE_REFRESH_DISCUSSIONS_RANKING = "force_refresh_discussions_ranking"
    FORCE_REFRESH_LINK_ENRICHMENT = "force_refresh_link_enrichment"
    FORCE_REFRESH_FINAL_TRANSLATION = "force_refresh_final_translation"

    # === Cross-Chat Consolidation Flags ===
    CONSOLIDATE_CHATS = "consolidate_chats"
    FORCE_REFRESH_CROSS_CHAT_AGGREGATION = "force_refresh_cross_chat_aggregation"
    FORCE_REFRESH_CROSS_CHAT_RANKING = "force_refresh_cross_chat_ranking"
    FORCE_REFRESH_CONSOLIDATED_CONTENT = "force_refresh_consolidated_content"
    FORCE_REFRESH_CONSOLIDATED_LINK_ENRICHMENT = "force_refresh_consolidated_link_enrichment"
    FORCE_REFRESH_CONSOLIDATED_TRANSLATION = "force_refresh_consolidated_translation"

    # === Top-K Discussions Configuration ===
    TOP_K_DISCUSSIONS = "top_k_discussions"

    # === Anti-Repetition Configuration ===
    PREVIOUS_NEWSLETTERS_TO_CONSIDER = "previous_newsletters_to_consider"

    # === Discussion Merging Configuration ===
    ENABLE_DISCUSSION_MERGING = "enable_discussion_merging"
    SIMILARITY_THRESHOLD = "similarity_threshold"

    # === Discussion Merging Results ===
    MERGED_DISCUSSIONS_FILE_PATH = "merged_discussions_file_path"
    NUM_DISCUSSIONS_BEFORE_MERGE = "num_discussions_before_merge"
    NUM_DISCUSSIONS_AFTER_MERGE = "num_discussions_after_merge"
    MERGE_OPERATIONS_COUNT = "merge_operations_count"

    # === Output Handler Configuration ===
    OUTPUT_ACTIONS = "output_actions"
    WEBHOOK_URL = "webhook_url"
    EMAIL_RECIPIENTS = "email_recipients"
    SUBSTACK_BLOG_ID = "substack_blog_id"

    # === Aggregation Fields (With Reducers) ===
    CHAT_RESULTS = "chat_results"
    CHAT_ERRORS = "chat_errors"

    # === Output Fields (Final Statistics) ===
    TOTAL_CHATS = "total_chats"
    SUCCESSFUL_CHATS = "successful_chats"
    FAILED_CHATS = "failed_chats"

    # === Cross-Chat Consolidation Directory Paths ===
    CONSOLIDATED_OUTPUT_DIR = "consolidated_output_dir"
    CONSOLIDATED_AGGREGATED_DISCUSSIONS_DIR = "consolidated_aggregated_discussions_dir"
    CONSOLIDATED_RANKING_DIR = "consolidated_ranking_dir"
    CONSOLIDATED_NEWSLETTER_DIR = "consolidated_newsletter_dir"
    CONSOLIDATED_ENRICHMENT_DIR = "consolidated_enrichment_dir"
    CONSOLIDATED_TRANSLATION_DIR = "consolidated_translation_dir"

    # === Cross-Chat Consolidation Expected File Paths ===
    EXPECTED_CONSOLIDATED_AGGREGATED_DISCUSSIONS_FILE = "expected_consolidated_aggregated_discussions_file"
    EXPECTED_CONSOLIDATED_RANKING_FILE = "expected_consolidated_ranking_file"
    EXPECTED_CONSOLIDATED_NEWSLETTER_JSON = "expected_consolidated_newsletter_json"
    EXPECTED_CONSOLIDATED_NEWSLETTER_MD = "expected_consolidated_newsletter_md"
    EXPECTED_CONSOLIDATED_ENRICHED_JSON = "expected_consolidated_enriched_json"
    EXPECTED_CONSOLIDATED_ENRICHED_MD = "expected_consolidated_enriched_md"
    EXPECTED_CONSOLIDATED_TRANSLATED_FILE = "expected_consolidated_translated_file"

    # === Cross-Chat Consolidation Actual File Paths ===
    # NOTE: These fields are STILL REQUIRED for inter-node communication.
    # See: knowledge/plans/AUDIT_IMPROVEMENT_PLAN.md
    CONSOLIDATED_AGGREGATED_DISCUSSIONS_PATH = "consolidated_aggregated_discussions_path"
    CONSOLIDATED_RANKING_PATH = "consolidated_ranking_path"
    CONSOLIDATED_NEWSLETTER_JSON_PATH = "consolidated_newsletter_json_path"
    CONSOLIDATED_NEWSLETTER_MD_PATH = "consolidated_newsletter_md_path"
    CONSOLIDATED_ENRICHED_JSON_PATH = "consolidated_enriched_json_path"
    CONSOLIDATED_ENRICHED_MD_PATH = "consolidated_enriched_md_path"
    CONSOLIDATED_TRANSLATED_PATH = "consolidated_translated_path"

    # === MongoDB Consolidated Newsletter IDs (Primary - MongoDB-First Architecture) ===
    CONSOLIDATED_NEWSLETTER_ID = "consolidated_newsletter_id"

    # === Cross-Chat Consolidation Metadata ===
    TOTAL_DISCUSSIONS_CONSOLIDATED = "total_discussions_consolidated"
    TOTAL_MESSAGES_CONSOLIDATED = "total_messages_consolidated"
    SOURCE_CHATS_IN_CONSOLIDATED = "source_chats_in_consolidated"

    # === LinkedIn Draft Creation ===

    # === Delivery Results ===
    DELIVERY_RESULTS = "delivery_results"

    # === Phase 2 HITL Selection Fields ===
    HITL_SELECTION_TIMEOUT_MINUTES = "hitl_selection_timeout_minutes"
    SELECTION_PREPARED = "selection_prepared"
    SELECTION_FILE = "selection_file"

    # === Progress Tracking (Optional - for SSE streaming) ===
    PROGRESS_THREAD_ID = "progress_thread_id"

    # === MongoDB Run Tracking (Optional - for dual-write) ===
    MONGODB_RUN_ID = "mongodb_run_id"


class DiscussionRankerStateKeys:
    """Keys for DiscussionRankerState TypedDict (discussion ranking subgraph)."""

    # === Input Fields (Required) ===
    SEPARATE_DISCUSSIONS_FILE_PATH = "separate_discussions_file_path"
    DISCUSSIONS_RANKING_DIR = "discussions_ranking_dir"
    EXPECTED_DISCUSSIONS_RANKING_FILE = "expected_discussions_ranking_file"
    SUMMARY_FORMAT = "summary_format"

    # === Top-K Configuration ===
    TOP_K_DISCUSSIONS = "top_k_discussions"

    # === Anti-Repetition Configuration ===
    PREVIOUS_NEWSLETTERS_TO_CONSIDER = "previous_newsletters_to_consider"
    DATA_SOURCE_NAME = "data_source_name"
    CURRENT_START_DATE = "current_start_date"

    # === MMR Diversity Configuration ===
    ENABLE_MMR_DIVERSITY = "enable_mmr_diversity"
    MMR_LAMBDA = "mmr_lambda"

    # === Force Refresh Flag ===
    FORCE_REFRESH_DISCUSSIONS_RANKING = "force_refresh_discussions_ranking"

    # === Langfuse Trace Context (Optional) ===
    LANGFUSE_TRACE_ID = "langfuse_trace_id"
    LANGFUSE_SESSION_ID = "langfuse_session_id"
    LANGFUSE_USER_ID = "langfuse_user_id"

    # === MongoDB Run Tracking (Optional - for diagnostics) ===
    MONGODB_RUN_ID = "mongodb_run_id"

    # === Output Fields ===
    DISCUSSIONS_RANKING_FILE_PATH = "discussions_ranking_file_path"


class LinkEnricherStateKeys:
    """Keys for LinkEnricherState TypedDict (link enrichment subgraph)."""

    # === Input Fields (Required) ===
    SEPARATE_DISCUSSIONS_FILE_PATH = "separate_discussions_file_path"
    NEWSLETTER_JSON_PATH = "newsletter_json_path"
    NEWSLETTER_MD_PATH = "newsletter_md_path"
    LINK_ENRICHMENT_DIR = "link_enrichment_dir"
    EXPECTED_ENRICHED_NEWSLETTER_JSON = "expected_enriched_newsletter_json"
    EXPECTED_ENRICHED_NEWSLETTER_MD = "expected_enriched_newsletter_md"
    SUMMARY_FORMAT = "summary_format"

    # === Force Refresh Flag ===
    FORCE_REFRESH_LINK_ENRICHMENT = "force_refresh_link_enrichment"

    # === MongoDB Run Tracking (Optional - for diagnostics) ===
    MONGODB_RUN_ID = "mongodb_run_id"

    # === Intermediate Fields (Set by nodes with reducers) ===
    EXTRACTED_LINKS = "extracted_links"
    SEARCHED_LINKS = "searched_links"

    # === Output Fields ===
    AGGREGATED_LINKS_FILE_PATH = "aggregated_links_file_path"
    ENRICHED_NEWSLETTER_JSON_PATH = "enriched_newsletter_json_path"
    ENRICHED_NEWSLETTER_MD_PATH = "enriched_newsletter_md_path"
    NUM_LINKS_EXTRACTED = "num_links_extracted"
    NUM_LINKS_SEARCHED = "num_links_searched"
    NUM_LINKS_INSERTED = "num_links_inserted"


# ============================================================================
# CONVENIENCE ALIASES
# ============================================================================
# Use these shorter aliases for cleaner imports in your code

# Most commonly used state (single chat workflow)
SingleChatKeys = SingleChatStateKeys

# Multi-chat orchestration
OrchestratorKeys = ParallelOrchestratorStateKeys

# Subgraph states
RankerKeys = DiscussionRankerStateKeys
EnricherKeys = LinkEnricherStateKeys
