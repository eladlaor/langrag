"""
Pydantic Request/Response Models for FastAPI Endpoints

This module defines all Pydantic models used for request validation and
response serialization in the newsletter generation API.

Models follow the same structure as the original Flask endpoints to maintain
API contract compatibility.
"""

from pydantic import BaseModel, ConfigDict, Field

from constants import OutputAction, BatchJobStatus


# ============= Periodic Newsletter Models =============


class PeriodicNewsletterRequest(BaseModel):
    """
    Request model for periodic newsletter generation.

    Processes multiple WhatsApp chats over a date range to generate newsletters.
    """

    start_date: str = Field(..., description="Start date in ISO format (YYYY-MM-DD)", example="2025-01-01")
    end_date: str = Field(..., description="End date in ISO format (YYYY-MM-DD)", example="2025-01-15")
    data_source_name: str = Field(..., description="Data source name (langtalks, mcp_israel, or n8n_israel)", example="langtalks")
    whatsapp_chat_names_to_include: list[str] = Field(..., description="List of WhatsApp chat names to process", example=["LangTalks Community"])
    desired_language_for_summary: str = Field(..., description="Target language for the newsletter summary", example="english")
    summary_format: str = Field(..., description="Newsletter format: langtalks_format, mcp_israel_format, or whatsapp_format", example="langtalks_format")
    output_dir: str | None = Field(None, description="Override default output directory (optional)")

    # Force refresh flags (optional)
    force_refresh_extraction: bool | None = Field(False, description="Force re-extraction of messages")
    force_refresh_preprocessing: bool | None = Field(False, description="Force re-preprocessing")
    force_refresh_translation: bool | None = Field(False, description="Force re-translation of messages")
    force_refresh_separate_discussions: bool | None = Field(False, description="Force re-separation of discussions")
    force_refresh_content: bool | None = Field(False, description="Force re-generation of newsletter content")
    force_refresh_final_translation: bool | None = Field(False, description="Force re-translation of final summary")

    # Cross-chat consolidation flags (optional) - NEW
    consolidate_chats: bool | None = Field(True, description="Enable cross-chat consolidation (default: True). Combines multiple chats into one newsletter.")
    force_refresh_cross_chat_aggregation: bool | None = Field(False, description="Force re-aggregation of discussions from multiple chats")
    force_refresh_cross_chat_ranking: bool | None = Field(False, description="Force re-ranking of consolidated discussions")
    force_refresh_consolidated_content: bool | None = Field(False, description="Force re-generation of consolidated newsletter content")
    force_refresh_consolidated_link_enrichment: bool | None = Field(False, description="Force re-enrichment of consolidated newsletter with links")
    force_refresh_consolidated_translation: bool | None = Field(False, description="Force re-translation of consolidated newsletter")

    # LinkedIn draft creation (DEPRECATED: use output_actions=["send_linkedin"] instead)
    create_linkedin_draft: bool | None = Field(False, description="DEPRECATED: Use output_actions=['send_linkedin'] instead. " "Create LinkedIn draft post after newsletter generation (requires n8n setup).")

    # HITL selection timeout (optional)
    hitl_selection_timeout_minutes: int | None = Field(
        0,  # Default: 0 (no HITL, automatic selection)
        description="Timeout for human-in-the-loop discussion selection in minutes. " "Set to 0 to disable HITL (automatic selection of top discussions). " "Default: 0 (automatic, no human intervention required)",
        ge=0,  # Greater than or equal to 0
    )

    # Top-K discussions configuration (optional)
    top_k_discussions: int | None = Field(5, description="Number of discussions to feature in full (1 primary + rest secondary). " "Remaining discussions become brief mentions in 'worth_mentioning' section. " "Default: 5 (1 primary + 4 secondary discussions)", ge=1, le=20)

    # Anti-repetition configuration (optional)
    previous_newsletters_to_consider: int | None = Field(5, description="Number of previous newsletters to check for repetition detection. " "Topics covered in previous newsletters will be downranked. " "Set to 0 to disable anti-repetition. Default: 5 (or max available if fewer exist).", ge=0, le=20)

    # Discussion merging configuration (optional)
    enable_discussion_merging: bool | None = Field(True, description="Enable merging of similar discussions across chats into enriched super-discussions. " "When enabled, discussions covering the same topic from different groups are combined " "to provide comprehensive coverage without repetition. Default: True for multi-chat.")
    similarity_threshold: str | None = Field("moderate", description="How aggressively to merge similar discussions. " "'strict' = only near-identical topics, " "'moderate' = same topic + clear subtopics, " "'aggressive' = all related topics. Default: 'moderate'.")

    # MMR diversity configuration (optional)
    enable_mmr_diversity: bool | None = Field(True, description="Enable MMR (Maximal Marginal Relevance) diversity reranking for top-K selection. " "When enabled, discussions are selected to balance quality and diversity, " "preventing multiple discussions about the same topic. " "Uses embeddings to measure topical similarity. Default: True.")
    mmr_lambda: float | None = Field(0.7, ge=0.0, le=1.0, description="MMR balance parameter (0-1). Controls quality vs diversity trade-off. " "0.7 (default) = 70% quality, 30% diversity (recommended). " "1.0 = pure quality ranking (disable diversity). " "0.0 = pure diversity (ignore quality). " "0.5 = equal weight.")

    # Output actions (optional)
    # Includes infrastructure (save_local, webhook, send_email) and publishing platforms (send_substack, send_linkedin).
    # Publishing platform actions are validated against community-specific allowed destinations.
    output_actions: list[str] | None = Field(None, description=f"Output actions: {', '.join(OutputAction)}. " "Publishing platform actions (send_substack, send_linkedin) must be allowed " "for the specified data_source_name community.", example=[OutputAction.SAVE_LOCAL])
    webhook_url: str | None = Field(None, description="Webhook URL for webhook action")
    email_recipients: list[str] | None = Field(None, description="Email recipients for send_email action")
    substack_blog_id: str | None = Field(None, description="Substack blog ID for send_substack action (optional)")

    # Image extraction (optional)
    enable_image_extraction: bool | None = Field(False, description="Extract and store images from messages. Requires VISION_ENABLED=true in environment.")

    # Batch API configuration (optional) - for 50% cost reduction
    use_batch_api: bool | None = Field(False, description="Use OpenAI Batch API for translation (50% cost savings). " "When enabled, the request is queued for background processing. " "Returns a job_id immediately - use GET /api/batch_jobs/{job_id} to check status. " "Default: False (synchronous processing with real-time progress).")
    batch_webhook_url: str | None = Field(None, description="Webhook URL to notify when batch job completes (only used if use_batch_api=True)")
    batch_notification_email: str | None = Field(None, description="Email address to notify when batch job completes (only used if use_batch_api=True)")

    model_config = ConfigDict(json_schema_extra={"example": {"start_date": "2025-01-01", "end_date": "2025-01-15", "data_source_name": "langtalks", "whatsapp_chat_names_to_include": ["LangTalks Community"], "desired_language_for_summary": "english", "summary_format": "langtalks_format", "force_refresh_extraction": False, "previous_newsletters_to_consider": 5, "output_actions": [OutputAction.SAVE_LOCAL]}})


class NewsletterResult(BaseModel):
    """
    Individual newsletter result for a single chat.

    Contains either success data (file paths) or error information.
    """

    date: str = Field(..., description="Date range for this newsletter")
    chat_name: str | None = Field(None, description="WhatsApp chat name")
    success: bool = Field(..., description="Whether newsletter generation succeeded")
    extracted_file: str | None = Field(None, description="Path to extracted messages file")
    preprocessed_file: str | None = Field(None, description="Path to preprocessed messages file")
    translated_file: str | None = Field(None, description="Path to translated messages file")
    newsletter_json: str | None = Field(None, description="Path to newsletter JSON file")
    newsletter_md: str | None = Field(None, description="Path to newsletter Markdown file")
    newsletter_html: str | None = Field(None, description="Path to newsletter HTML file (periodic only)")
    error: str | None = Field(None, description="Error message if generation failed")


class ConsolidatedNewsletterResult(BaseModel):
    """
    Consolidated newsletter result containing aggregated newsletter from multiple days or chats.

    Generated when:
    - generate_consolidated_newsletter=True for daily summaries (cross-day consolidation)
    - consolidate_chats=True for periodic newsletters (cross-chat consolidation)
    """

    json_path: str | None = Field(None, description="Path to consolidated newsletter JSON")
    md_path: str | None = Field(None, description="Path to consolidated newsletter Markdown")
    enriched_json_path: str | None = Field(None, description="Path to link-enriched newsletter JSON")
    enriched_md_path: str | None = Field(None, description="Path to link-enriched newsletter Markdown")
    final_translated_path: str | None = Field(None, description="Path to translated newsletter (if not English)")
    total_discussions: int | None = Field(None, description="Total discussions included in newsletter")
    total_days_processed: int | None = Field(None, description="Number of days aggregated")
    discussions_ranking_path: str | None = Field(None, description="Path to discussions ranking file")

    # Cross-chat consolidation fields (NEW)
    source_chats: list[str] | None = Field(None, description="List of chat names consolidated in this newsletter")
    total_chats_consolidated: int | None = Field(None, description="Number of chats consolidated")
    total_messages_consolidated: int | None = Field(None, description="Total messages from all chats")
    per_chat_outputs_dir: str | None = Field(None, description="Directory containing per-chat outputs (for inspection)")


class PeriodicNewsletterResponse(BaseModel):
    """
    Response model for periodic newsletter generation.

    Contains aggregated results and statistics for all processed chats.
    Optionally includes consolidated newsletter if consolidate_chats=True and >1 chat processed.
    """

    message: str = Field(..., description="Summary message")
    results: list[NewsletterResult] = Field(..., description="Results for each chat")
    total_chats: int = Field(..., description="Total number of chats processed")
    successful_chats: int = Field(..., description="Number of successful completions")
    failed_chats: int = Field(..., description="Number of failures")

    # Cross-chat consolidation result (NEW)
    consolidated_newsletter: ConsolidatedNewsletterResult | None = Field(None, description="Consolidated newsletter combining all chats (if consolidate_chats=True and >1 successful chat)")


# ============= Batch Job Models =============


class BatchJobQueuedResponse(BaseModel):
    """
    Response when a batch job is queued (HTTP 202 Accepted).

    Returned when use_batch_api=True in the request.
    """

    job_id: str = Field(..., description="Unique job identifier (UUID)")
    status: str = Field(BatchJobStatus.QUEUED, description="Job status (always 'queued' for this response)")
    message: str = Field(..., description="Instructions for checking job status")
    estimated_completion: str = Field("within 24 hours (usually much faster)", description="Expected completion time")


class BatchJobStatusResponse(BaseModel):
    """
    Response for batch job status query.

    Status values: queued, processing, completed, failed, cancelled
    """

    job_id: str = Field(..., description="Unique job identifier (UUID)")
    status: str = Field(..., description="Current job status")
    created_at: str = Field(..., description="Job creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")
    started_at: str | None = Field(None, description="Processing start timestamp")
    completed_at: str | None = Field(None, description="Completion timestamp")

    # Request details
    data_source_name: str | None = Field(None, description="Data source from original request")
    start_date: str | None = Field(None, description="Start date from original request")
    end_date: str | None = Field(None, description="End date from original request")

    # Results (only present when completed)
    output_dir: str | None = Field(None, description="Output directory path (when completed)")
    error_message: str | None = Field(None, description="Error message (when failed)")

    # OpenAI tracking (for debugging)
    openai_batch_id: str | None = Field(None, description="OpenAI Batch API job ID")


class BatchJobListResponse(BaseModel):
    """
    Response for listing batch jobs.
    """

    jobs: list[BatchJobStatusResponse] = Field(..., description="List of batch jobs")
    total: int = Field(..., description="Total number of jobs matching filter")


# ============= Phase 2 HITL Models =============


class RankedDiscussionItem(BaseModel):
    """
    Single discussion item for HITL selection UI.

    Contains all metadata needed for user to make informed selection decision.
    """

    id: str = Field(..., description="Discussion ID")
    rank: int = Field(..., description="Ranking position (1-based)")
    title: str = Field(..., description="Discussion title")
    group_name: str = Field(..., description="WhatsApp group name")
    first_message_date: str = Field(..., description="Date of first message (DD.MM.YY)")
    first_message_time: str = Field(..., description="Time of first message (HH:MM)")
    num_messages: int = Field(..., description="Number of messages in discussion")
    num_unique_participants: int = Field(..., description="Number of unique participants")
    nutshell: str = Field(..., description="Short summary of discussion")
    relevance_score: float | None = Field(None, description="Importance score (0-10)")
    reasoning: str = Field(..., description="Why this discussion was ranked here")


class DiscussionSelectionResponse(BaseModel):
    """
    Response model for GET /api/discussion_selection/{run_directory}

    Loads ranked_discussions.json prepared by Phase 1 for UI display.
    """

    discussions: list[RankedDiscussionItem] = Field(..., description="Ranked discussions for selection")
    timeout_deadline: str = Field(..., description="ISO timestamp when selection expires")
    total_discussions: int = Field(..., description="Total number of discussions available")
    format_type: str = Field(..., description="Newsletter format (e.g., 'langtalks_format')")


class DiscussionSelectionsSaveRequest(BaseModel):
    """
    Request model for POST /api/save_discussion_selections

    Saves user-selected discussion IDs to user_selections.json.
    """

    run_directory: str = Field(..., description="Path to workflow output directory")
    selected_discussion_ids: list[str] = Field(..., description="List of selected discussion IDs")


class DiscussionSelectionsSaveResponse(BaseModel):
    """
    Response confirming selections were saved.
    """

    message: str = Field(..., description="Success message")
    selections_file_path: str = Field(..., description="Path to saved user_selections.json")
    num_selected: int = Field(..., description="Number of discussions selected")


class Phase2GenerationRequest(BaseModel):
    """
    Request model for POST /api/generate_newsletter_phase2

    Triggers Phase 2 newsletter generation using selected discussions.
    """

    run_directory: str = Field(..., description="Path to workflow output directory (from Phase 1)")


class Phase2GenerationResponse(BaseModel):
    """
    Response model for Phase 2 newsletter generation.

    Contains paths to generated newsletter and statistics.
    """

    message: str = Field(..., description="Success message")
    newsletter_path: str = Field(..., description="Path to generated newsletter (enriched HTML if available, otherwise base markdown)")
    num_discussions: int = Field(..., description="Number of discussions included")
    content_length: int = Field(..., description="Newsletter length in characters")
    validation_passed: bool = Field(..., description="Whether format validation passed")

    # Base newsletter paths
    base_json_path: str | None = Field(None, description="Path to base newsletter JSON")
    base_md_path: str | None = Field(None, description="Path to base newsletter Markdown")
    base_html_path: str | None = Field(None, description="Path to base newsletter HTML")

    # Enriched newsletter paths (with links)
    enriched_json_path: str | None = Field(None, description="Path to enriched newsletter JSON")
    enriched_md_path: str | None = Field(None, description="Path to enriched newsletter Markdown")
    enriched_html_path: str | None = Field(None, description="Path to enriched newsletter HTML")

    # Link metadata
    links_metadata_path: str | None = Field(None, description="Path to aggregated links metadata JSON")
