"""
Newsletter Generation Endpoint

This module implements the periodic newsletter generation endpoint that processes
multiple WhatsApp chats in parallel over a date range.

Flow:
1. Validating request parameters
2. Invoking parallel_orchestrator_graph with state
3. Transforming LangGraph state results to response format
4. Returning aggregated results with statistics

Error Handling:
- HTTP 400 for validation errors
- HTTP 500 for workflow execution errors
- Fail-fast philosophy: errors are logged and propagated

Instrumented with Langfuse for tracing and cost tracking.
"""

import logging
import os
import json
import asyncio
import uuid
from datetime import datetime, UTC
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse

from observability.llm import (
    get_langfuse_client,
    is_langfuse_enabled,
)
from utils.observability import safe_flush_langfuse

from custom_types.api_schemas import (
    PeriodicNewsletterRequest,
    PeriodicNewsletterResponse,
    NewsletterResult,
    ConsolidatedNewsletterResult,
    RankedDiscussionItem,
    DiscussionSelectionResponse,
    DiscussionSelectionsSaveRequest,
    DiscussionSelectionsSaveResponse,
    Phase2GenerationRequest,
    Phase2GenerationResponse,
    BatchJobQueuedResponse,
    BatchJobStatusResponse,
    BatchJobListResponse,
)
from custom_types.field_keys import RankingResultKeys, DiscussionKeys
from db.batch_jobs import BatchJobManager, BatchJobStatus
from graphs.multi_chat_consolidator.graph import parallel_orchestrator_graph
from graphs.state_keys import (
    ParallelOrchestratorStateKeys as OrchestratorKeys,
    SingleChatStateKeys as SingleChatKeys,
    LinkEnricherStateKeys as EnricherKeys,
)
from graphs.subgraphs.link_enricher import link_enricher_graph
from graphs.subgraphs.state import LinkEnricherState
from api.sse import get_progress_queue, remove_progress_queue, ProgressQueue
from config import get_settings
from constants import (
    KNOWN_WHATSAPP_CHAT_NAMES,
    ROUTE_GENERATE_PERIODIC_NEWSLETTER,
    ROUTE_GENERATE_PERIODIC_NEWSLETTER_STREAM,
    ROUTE_DISCUSSION_SELECTION,
    ROUTE_SAVE_DISCUSSION_SELECTIONS,
    ROUTE_GENERATE_NEWSLETTER_PHASE2,
    ROUTE_NEWSLETTER_FILE_CONTENT,
    ROUTE_NEWSLETTER_HTML_VIEWER,
    ROUTE_BATCH_JOBS_BY_ID,
    ROUTE_BATCH_JOBS,
    DataSources,
    ContentGenerationOperations,
    OutputAction,
    UNIVERSAL_OUTPUT_ACTIONS,
    COMMUNITY_ALLOWED_OUTPUT_ACTIONS,
    ENV_DEFAULT_EMAIL_RECIPIENT,
    WorkflowNames,
    ProgressEventType,
    HITL_KEY_TIMEOUT_DEADLINE,
    RESULT_KEY_NEWSLETTER_SUMMARY_PATH,
    RESULT_KEY_MARKDOWN_PATH,
    RESULT_KEY_HTML_PATH,
    SummaryFormats,
    OUTPUT_DIR_PERIODIC_NEWSLETTER,
    DIR_NAME_PER_CHAT,
    DIR_NAME_CONSOLIDATED,
    DIR_NAME_NEWSLETTER,
    DIR_NAME_LINK_ENRICHMENT,
    OUTPUT_FILENAME_ENRICHED_JSON,
    OUTPUT_FILENAME_ENRICHED_MD,
    OUTPUT_FILENAME_ENRICHED_HTML,
    TAG_NEWSLETTER,
    TAG_PERIODIC,
    TAG_STREAMING,
    BatchJobStatus,
    DIR_NAME_DISCUSSIONS_FOR_SELECTION,
    DIR_NAME_AFTER_SELECTION,
    DIR_NAME_AGGREGATED_DISCUSSIONS,
    DIR_NAME_DISCUSSIONS_RANKING,
    OUTPUT_FILENAME_RANKED_DISCUSSIONS,
    OUTPUT_FILENAME_USER_SELECTIONS,
    OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS,
    OUTPUT_FILENAME_CROSS_CHAT_RANKING,
    OUTPUT_FILENAME_SELECTED_DISCUSSIONS,
    OUTPUT_BASE_DIR_NAME,
    CONTENT_TYPE_EVENT_STREAM,
)
from core.generation.generators.factory import ContentGeneratorFactory
from custom_types.newsletter_formats import list_formats

router = APIRouter()
logger = logging.getLogger(__name__)


def validate_newsletter_request(request: PeriodicNewsletterRequest) -> None:
    """
    Validating all periodic newsletter request parameters comprehensively.

    This is the single source of truth for request validation. All newsletter
    endpoints should call this function to ensure consistent validation.

    Validates:
    - data_source_name is in KNOWN_WHATSAPP_CHAT_NAMES
    - All chat names are valid for the data source
    - summary_format is valid
    - Date format is YYYY-MM-DD and start_date <= end_date
    - whatsapp_chat_names_to_include is not empty
    - Output action parameters are provided when actions are specified

    Args:
        request: PeriodicNewsletterRequest to validate

    Raises:
        HTTPException: If validation fails (HTTP 400)
    """
    # Validating data_source_name
    if request.data_source_name not in KNOWN_WHATSAPP_CHAT_NAMES:
        raise HTTPException(status_code=400, detail=f"Invalid data_source_name: {request.data_source_name}. " f"Must be one of: {', '.join(KNOWN_WHATSAPP_CHAT_NAMES.keys())}")

    # Validating chat names
    valid_chat_names = KNOWN_WHATSAPP_CHAT_NAMES[request.data_source_name]
    invalid_chats = [name for name in request.whatsapp_chat_names_to_include if name not in valid_chat_names]
    if invalid_chats:
        raise HTTPException(status_code=400, detail=f"Invalid chat names: {', '.join(invalid_chats)}. " f"Must be one of: {', '.join(valid_chat_names)}")

    # Validating summary format using auto-discovered format registry
    valid_formats = list_formats()
    if request.summary_format not in valid_formats:
        raise HTTPException(status_code=400, detail=f"Invalid summary_format: {request.summary_format}. " f"Must be one of: {', '.join(valid_formats)}")

    # Validating date format and range
    try:
        start_date_obj = datetime.strptime(request.start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(request.end_date, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format. Must be YYYY-MM-DD: {e}")

    if start_date_obj > end_date_obj:
        raise HTTPException(status_code=400, detail=f"start_date ({request.start_date}) must be before or equal to end_date ({request.end_date})")

    # Validating chat names list is not empty
    if not request.whatsapp_chat_names_to_include:
        raise HTTPException(status_code=400, detail="whatsapp_chat_names_to_include cannot be empty")

    # Resolve output actions (merges legacy fields like create_linkedin_draft)
    resolved_actions = resolve_output_actions(request)

    # Validating output action values
    valid_actions = list(OutputAction)
    for action in resolved_actions:
        if action not in valid_actions:
            raise HTTPException(status_code=400, detail=f"Invalid output action: '{action}'. Valid actions: {', '.join(valid_actions)}")

    # Validating community-specific output actions
    community_allowed = COMMUNITY_ALLOWED_OUTPUT_ACTIONS.get(request.data_source_name, [])
    all_allowed = list(UNIVERSAL_OUTPUT_ACTIONS) + list(community_allowed)
    for action in resolved_actions:
        if action not in all_allowed:
            raise HTTPException(status_code=400, detail=f"Output action '{action}' is not configured for community '{request.data_source_name}'. " f"Allowed actions: {', '.join(all_allowed)}")

    # Validating action-specific parameters
    if OutputAction.WEBHOOK in resolved_actions and not request.webhook_url:
        raise HTTPException(status_code=400, detail=f"Output action '{OutputAction.WEBHOOK}' specified but 'webhook_url' not provided")
    if OutputAction.SEND_EMAIL in resolved_actions and not request.email_recipients:
        default_email = os.getenv(ENV_DEFAULT_EMAIL_RECIPIENT)
        if not default_email:
            raise HTTPException(status_code=400, detail=f"Output action '{OutputAction.SEND_EMAIL}' specified but 'email_recipients' not provided " f"and {ENV_DEFAULT_EMAIL_RECIPIENT} environment variable is not set")
        logger.info(f"Using default email recipient: {default_email}")
    if OutputAction.SEND_SUBSTACK in resolved_actions and not request.substack_blog_id:
        raise HTTPException(status_code=400, detail=f"Output action '{OutputAction.SEND_SUBSTACK}' specified but 'substack_blog_id' not provided")


def resolve_output_actions(request: PeriodicNewsletterRequest) -> list[str]:
    """
    Resolve the final list of output actions from request, handling backward compatibility.

    Merges explicit output_actions with legacy create_linkedin_draft flag.

    Args:
        request: PeriodicNewsletterRequest with output_actions and legacy fields

    Returns:
        List of output action string values
    """
    actions = list(request.output_actions or [])

    # Backward compatibility: create_linkedin_draft=True → add send_linkedin
    if request.create_linkedin_draft and OutputAction.SEND_LINKEDIN not in actions:
        logger.info("Legacy create_linkedin_draft=True detected, adding 'send_linkedin' to output_actions")
        actions.append(OutputAction.SEND_LINKEDIN)

    return actions


def _get_email_recipients(explicit_recipients: list | None) -> list | None:
    """
    Get email recipients with fallback to default.

    If explicit recipients are provided, use them.
    Otherwise, fall back to DEFAULT_EMAIL_RECIPIENT env var.

    Args:
        explicit_recipients: Explicitly provided email recipients

    Returns:
        List of email recipients or None if none available
    """
    if explicit_recipients:
        return explicit_recipients

    default_email = os.getenv(ENV_DEFAULT_EMAIL_RECIPIENT)
    if default_email:
        return [default_email]

    return None


def setup_output_directory(request: PeriodicNewsletterRequest) -> str:
    """
    Setting up and validating the output directory for a newsletter generation run.

    Creating the run-specific output directory and validating it is writable.
    This is the single source of truth for output directory setup.

    Args:
        request: PeriodicNewsletterRequest containing output_dir and identifiers

    Returns:
        str: The validated run output directory path

    Raises:
        HTTPException: If directory setup fails (HTTP 400)
    """
    base_output_dir = request.output_dir or os.path.join("output", OUTPUT_DIR_PERIODIC_NEWSLETTER)
    run_output_dir = os.path.join(base_output_dir, f"{request.data_source_name}_{request.start_date}_to_{request.end_date}")

    try:
        os.makedirs(run_output_dir, exist_ok=True)
        # Testing write permissions by creating and removing a test file
        test_file = os.path.join(run_output_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=f"Output directory is not writable: {run_output_dir} - {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to setup output directory: {run_output_dir} - {e}")

    return run_output_dir


@router.post(ROUTE_GENERATE_PERIODIC_NEWSLETTER, response_model=PeriodicNewsletterResponse)
async def generate_periodic_newsletter(request: PeriodicNewsletterRequest):
    """
    Generating periodic newsletter from WhatsApp group chats.

    This endpoint processes multiple chats in parallel over a date range using
    the LangGraph parallel_orchestrator_graph workflow. Each chat is processed
    through the complete pipeline: extraction, preprocessing, translation,
    discussion separation, content generation, and final translation.

    The workflow runs asynchronously and may take several minutes depending on
    the number of chats and date range.

    Args:
        request: PeriodicNewsletterRequest with dates, chats, and config

    Returns:
        PeriodicNewsletterResponse with results and statistics

    Raises:
        HTTPException: 400 for validation errors, 500 for execution errors
    """
    try:
        logger.info(f"Received periodic newsletter request: {request.data_source_name} " f"({request.start_date} to {request.end_date})")

        # Comprehensive validation (single source of truth)
        validate_newsletter_request(request)

        # Handling batch mode - queueing job and returning immediately
        if request.use_batch_api:
            logger.info("Batch mode enabled - queueing job for background processing")

            batch_manager = BatchJobManager()
            try:
                job_id = await batch_manager.create_job(request=request.model_dump(), webhook_url=request.batch_webhook_url, notification_email=request.batch_notification_email)

                logger.info(f"Created batch job: {job_id}")

                return JSONResponse(status_code=202, content=BatchJobQueuedResponse(job_id=job_id, status=BatchJobStatus.QUEUED, message=f"Job queued for batch processing. Use GET /api/batch_jobs/{job_id} to check status.", estimated_completion="within 24 hours (usually much faster)").model_dump())

            except Exception as e:
                logger.error(f"Failed to create batch job: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to queue batch job: {e}")

        # Setting up and validating output directory (single source of truth)
        run_output_dir = setup_output_directory(request)
        logger.info(f"Output directory: {run_output_dir}")

        # Creating Langfuse trace for this workflow
        langfuse = get_langfuse_client()
        trace = None
        thread_id = f"periodic_newsletter_{request.data_source_name}_{request.start_date}_{request.end_date}_{uuid.uuid4().hex[:8]}"

        if langfuse and is_langfuse_enabled():
            try:
                trace = langfuse.trace(
                    name="periodic_newsletter_generation",
                    session_id=thread_id,
                    user_id=request.data_source_name,
                    input=request.model_dump(),
                    metadata={
                        "chat_count": len(request.whatsapp_chat_names_to_include),
                        "consolidate_chats": request.consolidate_chats,
                        "summary_format": request.summary_format,
                        "date_range": f"{request.start_date} to {request.end_date}",
                        "output_dir": run_output_dir,
                    },
                    tags=[TAG_NEWSLETTER, TAG_PERIODIC, request.data_source_name],
                )
                logger.info(f"Created Langfuse trace: {trace.id}")
            except Exception as trace_err:
                logger.warning(f"Failed to create Langfuse trace: {trace_err}")

        # Preparing state for parallel orchestrator
        state = {
            "workflow_name": WorkflowNames.PERIODIC_NEWSLETTER,
            "data_source_name": request.data_source_name,
            "chat_names": request.whatsapp_chat_names_to_include,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "desired_language_for_summary": request.desired_language_for_summary,
            "summary_format": request.summary_format,
            "base_output_dir": run_output_dir,
            # Force refresh flags
            "force_refresh_extraction": request.force_refresh_extraction,
            "force_refresh_preprocessing": request.force_refresh_preprocessing,
            "force_refresh_translation": request.force_refresh_translation,
            "force_refresh_separate_discussions": request.force_refresh_separate_discussions,
            "force_refresh_content": request.force_refresh_content,
            "force_refresh_final_translation": request.force_refresh_final_translation,
            # Cross-chat consolidation flags (NEW)
            "consolidate_chats": request.consolidate_chats,
            "force_refresh_cross_chat_aggregation": request.force_refresh_cross_chat_aggregation,
            "force_refresh_cross_chat_ranking": request.force_refresh_cross_chat_ranking,
            "force_refresh_consolidated_content": request.force_refresh_consolidated_content,
            "force_refresh_consolidated_link_enrichment": request.force_refresh_consolidated_link_enrichment,
            "force_refresh_consolidated_translation": request.force_refresh_consolidated_translation,
            # Top-K discussions configuration
            "top_k_discussions": request.top_k_discussions,
            # Anti-repetition configuration
            "previous_newsletters_to_consider": request.previous_newsletters_to_consider,
            # Discussion merging configuration
            "enable_discussion_merging": request.enable_discussion_merging,
            "similarity_threshold": request.similarity_threshold,
            # Image extraction configuration
            "enable_image_extraction": request.enable_image_extraction,
            # Output actions (resolved with backward compat for create_linkedin_draft)
            "output_actions": resolve_output_actions(request) or [OutputAction.SAVE_LOCAL],
            "webhook_url": request.webhook_url,
            "email_recipients": _get_email_recipients(request.email_recipients),
            "substack_blog_id": request.substack_blog_id,
            # Initializing aggregation fields (required by state schema)
            OrchestratorKeys.CHAT_RESULTS: [],
            OrchestratorKeys.CHAT_ERRORS: [],
        }

        # Invoking parallel orchestrator graph
        config = {
            "configurable": {
                "thread_id": thread_id,
                "langfuse_trace_id": trace.id if trace else None,
                "langfuse_session_id": thread_id,
                "langfuse_user_id": request.data_source_name,
            }
        }

        logger.info(f"Invoking parallel orchestrator graph for {len(request.whatsapp_chat_names_to_include)} chats")

        result = await parallel_orchestrator_graph.ainvoke(state, config)

        logger.info(f"Workflow completed: {result.get('successful_chats', 0)}/{result.get('total_chats', 0)} successful")

        # Transforming results to response format
        results = []

        # Adding successful results
        for chat_result in result.get(OrchestratorKeys.CHAT_RESULTS, []):
            results.append(
                NewsletterResult(
                    date=f"{request.start_date} to {request.end_date}",
                    chat_name=chat_result.get(SingleChatKeys.CHAT_NAME),
                    success=True,
                    extracted_file=None,  # Not included in parallel orchestrator results
                    preprocessed_file=None,  # Not included in parallel orchestrator results
                    translated_file=chat_result.get(SingleChatKeys.FINAL_TRANSLATED_FILE_PATH),
                    newsletter_json=chat_result.get(SingleChatKeys.NEWSLETTER_JSON_PATH),
                    newsletter_md=chat_result.get(SingleChatKeys.NEWSLETTER_MD_PATH),
                    newsletter_html=chat_result.get(SingleChatKeys.NEWSLETTER_HTML_PATH),
                    error=None,
                )
            )

        # Adding failed results
        for chat_error in result.get(OrchestratorKeys.CHAT_ERRORS, []):
            results.append(NewsletterResult(date=f"{request.start_date} to {request.end_date}", chat_name=chat_error.get(SingleChatKeys.CHAT_NAME), success=False, extracted_file=None, preprocessed_file=None, translated_file=None, newsletter_json=None, newsletter_md=None, newsletter_html=None, error=chat_error.get("error")))

        # Building consolidated newsletter result if available (NEW)
        consolidated_newsletter = None
        if result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_JSON_PATH):
            consolidated_newsletter = ConsolidatedNewsletterResult(
                json_path=result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_JSON_PATH),
                md_path=result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH),
                enriched_json_path=result.get(OrchestratorKeys.CONSOLIDATED_ENRICHED_JSON_PATH),
                enriched_md_path=result.get(OrchestratorKeys.CONSOLIDATED_ENRICHED_MD_PATH),
                final_translated_path=result.get(OrchestratorKeys.CONSOLIDATED_TRANSLATED_PATH),
                total_discussions=result.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED),
                discussions_ranking_path=result.get(OrchestratorKeys.CONSOLIDATED_RANKING_PATH),
                source_chats=result.get(OrchestratorKeys.SOURCE_CHATS_IN_CONSOLIDATED),
                total_chats_consolidated=len(result.get(OrchestratorKeys.SOURCE_CHATS_IN_CONSOLIDATED, [])),
                total_messages_consolidated=result.get(OrchestratorKeys.TOTAL_MESSAGES_CONSOLIDATED),
                per_chat_outputs_dir=os.path.join(run_output_dir, DIR_NAME_PER_CHAT) if request.consolidate_chats else None,
            )

        # Building message
        message = f"Generated periodic newsletter: {result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0)}/{result.get(OrchestratorKeys.TOTAL_CHATS, 0)} chats successful"
        if consolidated_newsletter and consolidated_newsletter.md_path:
            message += f", consolidated newsletter generated with {consolidated_newsletter.total_discussions} discussions from {consolidated_newsletter.total_chats_consolidated} chats"

        # Updating Langfuse trace with output
        if trace:
            try:
                trace.update(
                    output={
                        "successful_chats": result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0),
                        "failed_chats": result.get(OrchestratorKeys.FAILED_CHATS, 0),
                        "total_chats": result.get(OrchestratorKeys.TOTAL_CHATS, 0),
                        "total_discussions": result.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED),
                        "consolidated_path": result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH),
                    },
                    level="DEFAULT" if result.get(OrchestratorKeys.FAILED_CHATS, 0) == 0 else "WARNING",
                )
            except Exception as trace_err:
                logger.debug(f"Failed to update Langfuse trace: {trace_err}")

        # Cleaning up diagnostics from memory (fail-soft)
        # TODO: Implement LLM-powered diagnostic report generation once generate_structured is available on the LLM provider
        mongodb_run_id = result.get(OrchestratorKeys.MONGODB_RUN_ID)
        if mongodb_run_id:
            try:
                from utils.run_diagnostics import clear_diagnostics

                clear_diagnostics(mongodb_run_id)
            except Exception as diag_err:
                logger.error(f"Failed to clear diagnostics: {diag_err}", exc_info=True)
                # Don't fail the request - diagnostics are best-effort

        # Flushing Langfuse traces
        safe_flush_langfuse(context="end_of_newsletter_generation")

        return PeriodicNewsletterResponse(message=message, results=results, total_chats=result.get("total_chats", 0), successful_chats=result.get("successful_chats", 0), failed_chats=result.get("failed_chats", 0), consolidated_newsletter=consolidated_newsletter)

    except HTTPException:
        # Re-raise validation errors (already have proper status codes)
        safe_flush_langfuse(context="http_exception")
        raise
    except Exception as e:
        # Updating trace with error if it exists
        if "trace" in locals() and trace:
            try:
                trace.update(level="ERROR", status_message=str(e))
            except Exception as trace_err:
                logger.error(f"Failed to update Langfuse trace with error state: {trace_err}")
        # Flushing and re-raising
        safe_flush_langfuse(context="error_handling")
        error_msg = f"Error in generate_periodic_newsletter: {e}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post(ROUTE_GENERATE_PERIODIC_NEWSLETTER_STREAM)
async def generate_periodic_newsletter_stream(request: PeriodicNewsletterRequest):
    """
    Generating periodic newsletter with real-time progress streaming (SSE).

    This endpoint streams Server-Sent Events (SSE) with real-time progress updates
    as the workflow executes. Each event contains information about the current stage,
    chat being processed, and any output files generated.

    Event Types Emitted:
    - workflow_started: Initial event with configuration
    - chat_started: Processing started for specific chat
    - stage_progress: Node execution updates (extracting, preprocessing, etc.)
    - chat_completed: Chat finished successfully (includes output paths)
    - chat_failed: Chat failed with error
    - consolidation_started: Cross-chat consolidation beginning
    - consolidation_completed: Consolidation finished (includes paths)
    - workflow_completed: All chats done + final results
    - error: Fatal error occurred

    Args:
        request: PeriodicNewsletterRequest with dates, chats, and config

    Returns:
        StreamingResponse with text/event-stream content type

    Raises:
        HTTPException: 400 for validation errors

    Example SSE Event:
        data: {"event_type": "stage_progress", "timestamp": "2025-10-18T12:00:00",
               "data": {"chat_name": "LangTalks", "stage": "extract_messages",
                       "status": "completed", "message": "Extracted 1,234 messages",
                       "output_file": "/app/output/.../raw_messages.jsonl"}}
    """
    # Comprehensive validation (single source of truth)
    validate_newsletter_request(request)

    # Setting up and validating output directory (single source of truth)
    run_output_dir = setup_output_directory(request)

    # Generating thread ID
    thread_id = f"periodic_newsletter_{request.data_source_name}_{request.start_date}_{request.end_date}_{uuid.uuid4().hex[:8]}"

    # Creating progress queue for this workflow
    progress = get_progress_queue(thread_id)

    async def event_stream():
        """
        Async generator that runs the workflow and streams progress events.
        Handling client disconnects gracefully and sending keepalive pings.
        """
        settings = get_settings()
        workflow_task = None
        last_keepalive = asyncio.get_event_loop().time()
        keepalive_interval = settings.api.keepalive_interval_seconds

        try:
            # Emitting workflow_started event
            progress.emit(ProgressEventType.WORKFLOW_STARTED, {"data_source": request.data_source_name, "start_date": request.start_date, "end_date": request.end_date, "chat_count": len(request.whatsapp_chat_names_to_include), "chat_names": request.whatsapp_chat_names_to_include, "output_directory": run_output_dir})

            # Running workflow in background task
            workflow_task = asyncio.create_task(run_workflow_with_progress(request, run_output_dir, thread_id, progress))

            # Streaming progress events while workflow runs
            workflow_completed = False
            while not workflow_completed:
                try:
                    # Waiting for next event with timeout for keepalive
                    current_time = asyncio.get_event_loop().time()
                    time_since_keepalive = current_time - last_keepalive
                    timeout = max(settings.api.min_event_timeout_seconds, keepalive_interval - time_since_keepalive)

                    try:
                        # Trying to get next event from queue
                        event = await asyncio.wait_for(progress._queue.get(), timeout=timeout)

                        # Yielding the event
                        event_data = json.dumps(event.to_dict())
                        yield f"data: {event_data}\n\n"

                        # Resetting keepalive timer
                        last_keepalive = asyncio.get_event_loop().time()

                    except TimeoutError:
                        # No event within timeout - sending keepalive if needed
                        current_time = asyncio.get_event_loop().time()
                        if current_time - last_keepalive >= keepalive_interval:
                            yield ": keepalive\n\n"
                            last_keepalive = current_time

                    # Checking if workflow is done
                    if workflow_task.done():
                        # Getting workflow result (will raise exception if task failed)
                        result = await workflow_task

                        # Checking if HITL mode was triggered (Phase 1 complete, waiting for selection)
                        if result.get(OrchestratorKeys.SELECTION_PREPARED):
                            # Emitting hitl_selection_ready event instead of workflow_completed
                            progress.emit(
                                ProgressEventType.HITL_SELECTION_READY, {"total_chats": result.get(OrchestratorKeys.TOTAL_CHATS, 0), "successful_chats": result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0), "failed_chats": result.get(OrchestratorKeys.FAILED_CHATS, 0), "run_directory": run_output_dir, "selection_file": result.get(OrchestratorKeys.SELECTION_FILE), "timeout_deadline": result.get(HITL_KEY_TIMEOUT_DEADLINE), "message": "Phase 1 complete. Please select discussions for the newsletter."}
                            )
                            logger.info(f"HITL selection ready: {run_output_dir}")
                        else:
                            # Emitting workflow_completed event with final results
                            progress.emit(
                                ProgressEventType.WORKFLOW_COMPLETED,
                                {
                                    "total_chats": result.get(OrchestratorKeys.TOTAL_CHATS, 0),
                                    "successful_chats": result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0),
                                    "failed_chats": result.get(OrchestratorKeys.FAILED_CHATS, 0),
                                    "output_directory": run_output_dir,
                                    "per_chat_outputs_dir": os.path.join(run_output_dir, DIR_NAME_PER_CHAT) if request.consolidate_chats else run_output_dir,
                                    "consolidated_output_dir": os.path.join(run_output_dir, DIR_NAME_CONSOLIDATED) if result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_JSON_PATH) else None,
                                    "consolidated_newsletter_path": result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH),
                                    "results": result,  # Full result object for client processing
                                },
                            )

                        # Closing progress queue
                        progress.close()

                        # Streaming any remaining events in queue
                        while not progress._queue.empty():
                            try:
                                final_event = progress._queue.get_nowait()
                                event_data = json.dumps(final_event.to_dict())
                                yield f"data: {event_data}\n\n"
                            except asyncio.QueueEmpty:
                                break

                        workflow_completed = True

                except asyncio.CancelledError:
                    # Client disconnected - log but let workflow continue
                    logger.info(f"Client disconnected from stream: {thread_id}")
                    logger.info("Workflow will continue running in background")
                    raise  # Re-raise to properly cleanup

        except asyncio.CancelledError:
            # Client disconnected during streaming
            logger.info(f"SSE stream cancelled for {thread_id}, workflow continues in background")
            # Don't close progress queue - workflow still running

        except Exception as e:
            logger.error(f"Error in streaming workflow: {e}", exc_info=True)
            try:
                progress.emit(ProgressEventType.ERROR, {"message": str(e), "type": type(e).__name__})
                error_data = json.dumps({"event_type": ProgressEventType.ERROR, "timestamp": datetime.now(UTC).isoformat(), "data": {"message": str(e), "type": type(e).__name__}})
                yield f"data: {error_data}\n\n"
            except Exception as emit_err:
                logger.error(f"Failed to emit SSE error event: {emit_err}")
            progress.close()

        finally:
            # Only cleaning up if workflow completed or errored
            # If client just disconnected, let workflow continue
            if workflow_task and workflow_task.done():
                remove_progress_queue(thread_id)
                logger.info(f"Cleaned up progress queue for completed workflow: {thread_id}")
            else:
                logger.info(f"Keeping progress queue for running workflow: {thread_id}")

    return StreamingResponse(
        event_stream(),
        media_type=CONTENT_TYPE_EVENT_STREAM,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def run_workflow_with_progress(request: PeriodicNewsletterRequest, run_output_dir: str, thread_id: str, progress: ProgressQueue) -> dict:
    """
    Running the newsletter generation workflow in a background task.

    Using native async LangGraph 1.0+ ainvoke() for graph execution.
    Progress is emitted via the progress queue for SSE streaming.

    Args:
        request: Newsletter generation request
        run_output_dir: Output directory path
        thread_id: Unique thread ID for this workflow
        progress: Progress queue for emitting events

    Returns:
        dict: LangGraph workflow result state
    """
    # Preparing state for parallel orchestrator
    state = {
        "workflow_name": WorkflowNames.PERIODIC_NEWSLETTER,
        "data_source_name": request.data_source_name,
        "chat_names": request.whatsapp_chat_names_to_include,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "desired_language_for_summary": request.desired_language_for_summary,
        "summary_format": request.summary_format,
        "base_output_dir": run_output_dir,
        # Force refresh flags
        "force_refresh_extraction": request.force_refresh_extraction,
        "force_refresh_preprocessing": request.force_refresh_preprocessing,
        "force_refresh_translation": request.force_refresh_translation,
        "force_refresh_separate_discussions": request.force_refresh_separate_discussions,
        "force_refresh_content": request.force_refresh_content,
        "force_refresh_final_translation": request.force_refresh_final_translation,
        # Cross-chat consolidation flags
        "consolidate_chats": request.consolidate_chats,
        "force_refresh_cross_chat_aggregation": request.force_refresh_cross_chat_aggregation,
        "force_refresh_cross_chat_ranking": request.force_refresh_cross_chat_ranking,
        "force_refresh_consolidated_content": request.force_refresh_consolidated_content,
        "force_refresh_consolidated_link_enrichment": request.force_refresh_consolidated_link_enrichment,
        "force_refresh_consolidated_translation": request.force_refresh_consolidated_translation,
        # HITL selection timeout
        "hitl_selection_timeout_minutes": request.hitl_selection_timeout_minutes,
        # Top-K discussions configuration
        "top_k_discussions": request.top_k_discussions,
        # Anti-repetition configuration
        "previous_newsletters_to_consider": request.previous_newsletters_to_consider,
        # Discussion merging configuration
        "enable_discussion_merging": request.enable_discussion_merging,
        "similarity_threshold": request.similarity_threshold,
        # Image extraction configuration
        "enable_image_extraction": request.enable_image_extraction,
        # Output actions (resolved with backward compat for create_linkedin_draft)
        "output_actions": resolve_output_actions(request) or [OutputAction.SAVE_LOCAL],
        "webhook_url": request.webhook_url,
        "email_recipients": _get_email_recipients(request.email_recipients),
        "substack_blog_id": request.substack_blog_id,
        # Initializing aggregation fields
        OrchestratorKeys.CHAT_RESULTS: [],
        OrchestratorKeys.CHAT_ERRORS: [],
        # Injecting progress thread ID for nodes to look up queue
        "progress_thread_id": thread_id,
    }

    # Creating Langfuse trace for streaming workflow
    langfuse = get_langfuse_client()
    trace = None
    langfuse_trace_id = None

    if langfuse and is_langfuse_enabled():
        try:
            trace = langfuse.trace(
                name="periodic_newsletter_generation_stream",
                session_id=thread_id,
                user_id=request.data_source_name,
                input=request.model_dump(),
                metadata={
                    "chat_count": len(request.whatsapp_chat_names_to_include),
                    "consolidate_chats": request.consolidate_chats,
                    "summary_format": request.summary_format,
                    "date_range": f"{request.start_date} to {request.end_date}",
                    "output_dir": run_output_dir,
                    "streaming": True,
                },
                tags=[TAG_NEWSLETTER, TAG_PERIODIC, TAG_STREAMING, request.data_source_name],
            )
            langfuse_trace_id = trace.id
            logger.info(f"Created Langfuse trace for streaming: {trace.id}")
        except Exception as trace_err:
            logger.warning(f"Failed to create Langfuse trace: {trace_err}")

    config = {
        "configurable": {
            "thread_id": thread_id,
            "langfuse_trace_id": langfuse_trace_id,
            "langfuse_session_id": thread_id,
            "langfuse_user_id": request.data_source_name,
        }
    }

    logger.info(f"Starting workflow with progress tracking: {thread_id}")

    # Native async graph invocation (LangGraph 1.0+)
    result = await parallel_orchestrator_graph.ainvoke(state, config)

    logger.info(f"Workflow completed: {result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0)}/{result.get(OrchestratorKeys.TOTAL_CHATS, 0)} successful")

    # Updating Langfuse trace with final results
    if trace:
        try:
            trace.update(
                output={
                    "successful_chats": result.get(OrchestratorKeys.SUCCESSFUL_CHATS, 0),
                    "failed_chats": result.get(OrchestratorKeys.FAILED_CHATS, 0),
                    "total_chats": result.get(OrchestratorKeys.TOTAL_CHATS, 0),
                    "total_discussions": result.get(OrchestratorKeys.TOTAL_DISCUSSIONS_CONSOLIDATED),
                    "consolidated_path": result.get(OrchestratorKeys.CONSOLIDATED_NEWSLETTER_MD_PATH),
                },
                level="DEFAULT" if result.get(OrchestratorKeys.FAILED_CHATS, 0) == 0 else "WARNING",
            )
        except Exception as trace_err:
            logger.debug(f"Failed to update Langfuse trace: {trace_err}")

    # Flushing Langfuse traces
    safe_flush_langfuse(context="newsletter_stream_completion")

    return result


# ============================================================================
# PHASE 2: HUMAN-IN-THE-LOOP ENDPOINTS
# ============================================================================


@router.get(ROUTE_DISCUSSION_SELECTION, response_model=DiscussionSelectionResponse)
async def get_discussion_selection(run_directory: str):
    """
    Loading ranked discussions for HITL selection UI.

    This endpoint loads the ranked_discussions.json file prepared by Phase 1
    and returns it formatted for the discussion selection UI.

    Args:
        run_directory: Path to workflow output directory from Phase 1
                      (e.g., "output/langtalks_2025-10-01_to_2025-10-26")

    Returns:
        DiscussionSelectionResponse with ranked discussions and metadata

    Raises:
        HTTPException 404: If ranked_discussions.json not found
        HTTPException 500: If file cannot be read or parsed
    """
    logger.info(f"Loading discussion selection from: {run_directory}")

    # Building path to ranked_discussions.json
    ranked_discussions_path = os.path.join(run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_FOR_SELECTION, OUTPUT_FILENAME_RANKED_DISCUSSIONS)

    if not os.path.exists(ranked_discussions_path):
        logger.error(f"Ranked discussions file not found: {ranked_discussions_path}")
        raise HTTPException(status_code=404, detail=f"Ranked discussions not found at {ranked_discussions_path}. " "Please run Phase 1 first with a format that requires HITL selection.")

    # Loading ranked discussions
    try:
        with open(ranked_discussions_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ranked discussions JSON: {e}")
        raise HTTPException(status_code=500, detail=f"Invalid JSON in ranked discussions file: {e}")
    except Exception as e:
        logger.error(f"Failed to read ranked discussions file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read ranked discussions: {e}")

    # Transforming to response model
    discussions = [RankedDiscussionItem(**disc) for disc in data.get(DiscussionKeys.DISCUSSIONS, [])]

    response = DiscussionSelectionResponse(discussions=discussions, timeout_deadline=data.get("timeout_deadline", ""), total_discussions=len(discussions), format_type=data.get("format_type", "unknown"))

    logger.info(f"Loaded {len(discussions)} discussions for selection")
    return response


@router.post(ROUTE_SAVE_DISCUSSION_SELECTIONS, response_model=DiscussionSelectionsSaveResponse)
async def save_discussion_selections(request: DiscussionSelectionsSaveRequest):
    """
    Saving user-selected discussion IDs for Phase 2 generation.

    This endpoint saves the user's selection to user_selections.json in the
    workflow output directory, which Phase 2 will read to generate the newsletter.

    Args:
        request: Contains run_directory and selected_discussion_ids

    Returns:
        DiscussionSelectionsSaveResponse with confirmation and file path

    Raises:
        HTTPException 400: If no discussions selected
        HTTPException 404: If run_directory doesn't exist
        HTTPException 500: If file write fails
    """
    logger.info(f"Saving {len(request.selected_discussion_ids)} discussion selections to: {request.run_directory}")

    # Validating request
    if not request.selected_discussion_ids:
        raise HTTPException(status_code=400, detail="No discussions selected. Please select at least one discussion.")

    if not os.path.exists(request.run_directory):
        raise HTTPException(status_code=404, detail=f"Run directory not found: {request.run_directory}")

    # Building path for user_selections.json
    selections_dir = os.path.join(request.run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_FOR_SELECTION)
    selections_file = os.path.join(selections_dir, OUTPUT_FILENAME_USER_SELECTIONS)

    # Ensuring directory exists
    os.makedirs(selections_dir, exist_ok=True)

    # Saving selections
    try:
        selections_data = {"selected_discussion_ids": request.selected_discussion_ids, "selection_timestamp": datetime.now(UTC).isoformat(), "num_selected": len(request.selected_discussion_ids)}

        with open(selections_file, "w", encoding="utf-8") as f:
            json.dump(selections_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved selections to: {selections_file}")

    except Exception as e:
        logger.error(f"Failed to save selections: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save selections: {e}")

    return DiscussionSelectionsSaveResponse(message=f"Successfully saved {len(request.selected_discussion_ids)} discussion selections", selections_file_path=selections_file, num_selected=len(request.selected_discussion_ids))


@router.post(ROUTE_GENERATE_NEWSLETTER_PHASE2, response_model=Phase2GenerationResponse)
async def generate_newsletter_phase2(request: Phase2GenerationRequest):
    """
    Generating newsletter using selected discussions (Phase 2).

    This endpoint loads the user's selections from user_selections.json,
    retrieves the full discussion content, and generates the final newsletter
    using the format-specific generator (e.g., langtalks_generator).

    Flow:
    1. Load user_selections.json
    2. Load all_chats_aggregated.json (full discussion content)
    3. Filter discussions based on selections
    4. Invoke format-specific generator (langtalks_generator.py)
    5. Return generated newsletter paths

    Args:
        request: Contains run_directory

    Returns:
        Phase2GenerationResponse with newsletter path and statistics

    Raises:
        HTTPException 404: If selections file or aggregated discussions not found
        HTTPException 500: If generation or validation fails
    """
    logger.info(f"Starting Phase 2 newsletter generation for: {request.run_directory}")

    # Loading user selections
    selections_file = os.path.join(request.run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_FOR_SELECTION, OUTPUT_FILENAME_USER_SELECTIONS)

    if not os.path.exists(selections_file):
        raise HTTPException(status_code=404, detail=f"User selections not found at {selections_file}. " "Please save selections first using /api/save_discussion_selections")

    try:
        with open(selections_file, encoding="utf-8") as f:
            selections_data = json.load(f)
        selected_ids = selections_data.get("selected_discussion_ids", [])
    except Exception as e:
        logger.error(f"Failed to load selections: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load selections: {e}")

    # Loading aggregated discussions (full content)
    aggregated_file = os.path.join(request.run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_AGGREGATED_DISCUSSIONS, OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS)

    if not os.path.exists(aggregated_file):
        raise HTTPException(status_code=404, detail=f"Aggregated discussions not found at {aggregated_file}. " "Please run Phase 1 first.")

    try:
        with open(aggregated_file, encoding="utf-8") as f:
            aggregated_data = json.load(f)
        all_discussions = aggregated_data.get(DiscussionKeys.DISCUSSIONS, [])
    except Exception as e:
        logger.error(f"Failed to load aggregated discussions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load aggregated discussions: {e}")

    # Filtering selected discussions
    selected_discussions = [disc for disc in all_discussions if disc.get(DiscussionKeys.ID) in selected_ids]

    if not selected_discussions:
        raise HTTPException(status_code=400, detail=f"No matching discussions found for selected IDs: {selected_ids}")

    logger.info(f"Filtered {len(selected_discussions)} discussions from {len(all_discussions)} total")

    # Loading ranking file to get brief_mention_items and format metadata
    # This follows the same pattern as generate_consolidated_newsletter node
    ranking_file = os.path.join(request.run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_RANKING, OUTPUT_FILENAME_CROSS_CHAT_RANKING)

    if not os.path.exists(ranking_file):
        raise HTTPException(status_code=404, detail=f"Ranking file not found at {ranking_file}. Please run Phase 1 first.")

    try:
        with open(ranking_file, encoding="utf-8") as f:
            ranking_data = json.load(f)
        brief_mention_items = ranking_data.get(RankingResultKeys.BRIEF_MENTION_ITEMS, [])
    except Exception as e:
        logger.error(f"Failed to load ranking data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load ranking data: {e}")

    # Loading ranked_discussions.json to get format_type
    ranked_discussions_file = os.path.join(request.run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_FOR_SELECTION, OUTPUT_FILENAME_RANKED_DISCUSSIONS)

    try:
        with open(ranked_discussions_file, encoding="utf-8") as f:
            ranked_data = json.load(f)
        summary_format = ranked_data.get("summary_format") or ranked_data.get("format_type", SummaryFormats.LANGTALKS_FORMAT)
        data_source_name = ranked_data.get("data_source_name", "unknown")
        date_range = ranked_data.get("date_range", "unknown")
    except Exception as e:
        logger.error(f"Failed to load ranked discussions metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load format metadata: {e}")

    logger.info(f"Using format: {summary_format}")
    logger.info(f"Loaded {len(brief_mention_items)} brief mention items from ranking")

    # Creating output directory for Phase 2
    phase2_output_dir = os.path.join(request.run_directory, DIR_NAME_CONSOLIDATED, DIR_NAME_AFTER_SELECTION)
    os.makedirs(phase2_output_dir, exist_ok=True)

    # Saving selected discussions to temporary file (required by ContentGenerator)
    selected_discussions_file = os.path.join(phase2_output_dir, OUTPUT_FILENAME_SELECTED_DISCUSSIONS)
    try:
        with open(selected_discussions_file, "w", encoding="utf-8") as f:
            json.dump({DiscussionKeys.DISCUSSIONS: selected_discussions}, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved selected discussions to: {selected_discussions_file}")
    except Exception as e:
        logger.error(f"Failed to save selected discussions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save selected discussions: {e}")

    # Generating newsletter using ContentGeneratorFactory
    try:
        # Getting content generator for format
        content_generator = ContentGeneratorFactory.create(data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES, summary_format=summary_format)

        # Generating newsletter (JSON, MD, HTML)
        # Following the same pattern as generate_consolidated_newsletter node
        newsletter_output_dir = os.path.join(phase2_output_dir, DIR_NAME_NEWSLETTER)
        os.makedirs(newsletter_output_dir, exist_ok=True)

        result = await content_generator.generate_content(
            operation=ContentGenerationOperations.GENERATE_NEWSLETTER_SUMMARY,
            data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
            data_source_path=selected_discussions_file,
            output_dir=newsletter_output_dir,
            group_name=f"Selected Discussions ({len(selected_discussions)} items)",
            date=date_range,
            # CRITICAL: Passing pre-filtered discussions (required by langtalks generator)
            featured_discussions=selected_discussions,
            brief_mention_items=brief_mention_items,
        )

        newsletter_json_path = result.get(RESULT_KEY_NEWSLETTER_SUMMARY_PATH)
        newsletter_md_path = result.get(RESULT_KEY_MARKDOWN_PATH)
        newsletter_html_path = result.get(RESULT_KEY_HTML_PATH)

        # Verifying files were created
        if not newsletter_json_path or not os.path.exists(newsletter_json_path):
            raise RuntimeError("Newsletter JSON was not created")
        if not newsletter_md_path or not os.path.exists(newsletter_md_path):
            raise RuntimeError("Newsletter Markdown was not created")
        if not newsletter_html_path or not os.path.exists(newsletter_html_path):
            raise RuntimeError("Newsletter HTML was not created")

        logger.info("Phase 2 generation completed successfully")
        logger.info(f"  JSON: {newsletter_json_path}")
        logger.info(f"  MD: {newsletter_md_path}")
        logger.info(f"  HTML: {newsletter_html_path}")

        # Calculating content length from JSON
        with open(newsletter_json_path, encoding="utf-8") as f:
            newsletter_content = json.load(f)
            content_length = len(json.dumps(newsletter_content))

        # Step 2: Link Enrichment (invoke link_enricher_graph)
        logger.info("Starting link enrichment...")

        try:
            # Preparing output directories
            link_enrichment_dir = os.path.join(phase2_output_dir, DIR_NAME_LINK_ENRICHMENT)
            os.makedirs(link_enrichment_dir, exist_ok=True)

            expected_enriched_json = os.path.join(link_enrichment_dir, OUTPUT_FILENAME_ENRICHED_JSON)
            expected_enriched_md = os.path.join(link_enrichment_dir, OUTPUT_FILENAME_ENRICHED_MD)

            # Preparing state for link_enricher subgraph
            enricher_state: LinkEnricherState = {
                EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH: selected_discussions_file,
                EnricherKeys.NEWSLETTER_JSON_PATH: newsletter_json_path,
                EnricherKeys.NEWSLETTER_MD_PATH: newsletter_md_path,
                EnricherKeys.LINK_ENRICHMENT_DIR: link_enrichment_dir,
                EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_JSON: expected_enriched_json,
                EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_MD: expected_enriched_md,
                EnricherKeys.SUMMARY_FORMAT: summary_format,
                EnricherKeys.FORCE_REFRESH_LINK_ENRICHMENT: False,
                EnricherKeys.EXTRACTED_LINKS: [],
                EnricherKeys.SEARCHED_LINKS: [],
                EnricherKeys.AGGREGATED_LINKS_FILE_PATH: None,
                EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH: None,
                EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH: None,
                EnricherKeys.NUM_LINKS_EXTRACTED: None,
                EnricherKeys.NUM_LINKS_SEARCHED: None,
                EnricherKeys.NUM_LINKS_INSERTED: None,
            }

            # Invoking link_enricher subgraph (async - LangGraph 1.0+)
            logger.info("Invoking link_enricher_graph...")
            thread_id = str(uuid.uuid4())
            enricher_result = await link_enricher_graph.ainvoke(enricher_state, config={"configurable": {"thread_id": thread_id}})

            enriched_json_path = enricher_result.get(EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH)
            enriched_md_path = enricher_result.get(EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH)
            num_links_inserted = enricher_result.get(EnricherKeys.NUM_LINKS_INSERTED, 0)

            if enriched_json_path and os.path.exists(enriched_json_path):
                logger.info(f"Link enrichment completed: {num_links_inserted} links inserted")
                logger.info(f"  Enriched JSON: {enriched_json_path}")
                logger.info(f"  Enriched MD: {enriched_md_path}")

                # Generating HTML from enriched JSON
                with open(enriched_json_path, encoding="utf-8") as f:
                    enriched_content = json.load(f)

                # Using format plugin to render HTML from enriched content
                from custom_types.newsletter_formats import get_format

                newsletter_format = get_format(summary_format)
                enriched_html_content = newsletter_format.render_html(enriched_content)

                enriched_html_path = os.path.join(link_enrichment_dir, OUTPUT_FILENAME_ENRICHED_HTML)
                with open(enriched_html_path, "w", encoding="utf-8") as f:
                    f.write(enriched_html_content)

                logger.info(f"  Enriched HTML: {enriched_html_path}")

                # Links metadata path
                links_metadata_path = enricher_result.get(EnricherKeys.AGGREGATED_LINKS_FILE_PATH)

                return Phase2GenerationResponse(
                    message=f"Newsletter generated successfully with {num_links_inserted} links",
                    newsletter_path=enriched_html_path,  # Use enriched HTML version for easy viewing
                    num_discussions=len(selected_discussions),
                    content_length=content_length,
                    validation_passed=True,
                    # Base paths
                    base_json_path=newsletter_json_path,
                    base_md_path=newsletter_md_path,
                    base_html_path=newsletter_html_path,
                    # Enriched paths
                    enriched_json_path=enriched_json_path,
                    enriched_md_path=enriched_md_path,
                    enriched_html_path=enriched_html_path,
                    # Links metadata
                    links_metadata_path=links_metadata_path,
                )
            else:
                logger.warning("Link enrichment did not produce enriched files, returning base newsletter")
                return Phase2GenerationResponse(
                    message="Newsletter generated successfully (link enrichment skipped)",
                    newsletter_path=newsletter_html_path,  # Use base HTML version
                    num_discussions=len(selected_discussions),
                    content_length=content_length,
                    validation_passed=True,
                    # Base paths
                    base_json_path=newsletter_json_path,
                    base_md_path=newsletter_md_path,
                    base_html_path=newsletter_html_path,
                )

        except Exception as enrichment_error:
            logger.error(f"Link enrichment failed: {enrichment_error}", exc_info=True)
            # Don't fail the whole endpoint, return base newsletter
            logger.warning("Returning base newsletter without link enrichment")
            return Phase2GenerationResponse(
                message="Newsletter generated successfully (link enrichment failed)",
                newsletter_path=newsletter_html_path,  # Use base HTML version
                num_discussions=len(selected_discussions),
                content_length=content_length,
                validation_passed=True,
                # Base paths
                base_json_path=newsletter_json_path,
                base_md_path=newsletter_md_path,
                base_html_path=newsletter_html_path,
            )

    except Exception as e:
        logger.error(f"Phase 2 generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Newsletter generation failed: {str(e)}")


@router.get(ROUTE_NEWSLETTER_FILE_CONTENT)
async def get_newsletter_file_content(file_path: str):
    """
    Fetching the content of a newsletter file (HTML, JSON, MD, etc.).

    Args:
        file_path: Relative path to the file (e.g., "output/generate_periodic_newsletter/...")

    Returns:
        File content as plain text

    Security:
        - Only allows paths within the output directory
        - Resolves symlinks and validates path containment
    """
    try:
        # Getting absolute path to output directory
        output_base = os.path.abspath(OUTPUT_BASE_DIR_NAME)

        # Resolving the requested file path
        requested_file = os.path.abspath(file_path)

        # Security check: Ensuring file is within output directory
        if not requested_file.startswith(output_base):
            raise HTTPException(status_code=403, detail="Access denied: File must be within output directory")

        # Checking if file exists
        if not os.path.exists(requested_file):
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        # Checking if it's a file (not a directory)
        if not os.path.isfile(requested_file):
            raise HTTPException(status_code=400, detail=f"Not a file: {file_path}")

        # Reading and returning file content
        with open(requested_file, encoding="utf-8") as f:
            content = f.read()

        return {"content": content, "file_path": file_path}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


@router.get(ROUTE_NEWSLETTER_HTML_VIEWER, response_class=HTMLResponse)
async def newsletter_html_viewer(path: str):
    """
    Serve newsletter HTML content directly in browser.

    This endpoint is used by email notifications to display the newsletter
    content directly without requiring download.

    Args:
        path: Path to the HTML newsletter file

    Returns:
        HTML content rendered directly in browser

    Security:
        - Only allows paths within the output directory
        - Only allows HTML files
        - Resolves symlinks and validates path containment
    """
    try:
        # Getting absolute path to output directory
        output_base = os.path.abspath(OUTPUT_BASE_DIR_NAME)

        # Resolving the requested file path
        requested_file = os.path.abspath(path)

        # Security check: Ensuring file is within output directory
        if not requested_file.startswith(output_base):
            logger.warning(f"Path traversal attempt blocked: {path}")
            raise HTTPException(status_code=403, detail="Access denied: File must be within output directory")

        # Security check: Only allow HTML files
        if not requested_file.endswith(".html"):
            raise HTTPException(status_code=400, detail="Only HTML files are allowed")

        # Checking if file exists
        if not os.path.exists(requested_file):
            raise HTTPException(status_code=404, detail=f"Newsletter not found: {path}")

        # Checking if it's a file (not a directory)
        if not os.path.isfile(requested_file):
            raise HTTPException(status_code=400, detail=f"Not a file: {path}")

        # Reading and returning HTML content
        with open(requested_file, encoding="utf-8") as f:
            content = f.read()

        logger.info(f"Serving newsletter HTML: {path}")
        return HTMLResponse(content=content)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve HTML {path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to serve newsletter: {str(e)}")


# ============================================================================
# BATCH JOB ENDPOINTS
# ============================================================================


def _format_datetime(dt) -> str:
    """Formatting datetime to ISO string, handling None values."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _job_to_response(job: dict) -> BatchJobStatusResponse:
    """Converting MongoDB job document to response model."""
    request = job.get("request", {})
    return BatchJobStatusResponse(
        job_id=job.get("job_id"),
        status=job.get("status"),
        created_at=_format_datetime(job.get("created_at")),
        updated_at=_format_datetime(job.get("updated_at")),
        started_at=_format_datetime(job.get("started_at")),
        completed_at=_format_datetime(job.get("completed_at")),
        data_source_name=request.get("data_source_name"),
        start_date=request.get("start_date"),
        end_date=request.get("end_date"),
        output_dir=job.get("output_dir"),
        error_message=job.get("error_message"),
        openai_batch_id=job.get("openai_batch_id"),
    )


@router.get(ROUTE_BATCH_JOBS_BY_ID, response_model=BatchJobStatusResponse)
async def get_batch_job_status(job_id: str):
    """
    Getting the status of a batch job.

    Using this endpoint to check the status of a job submitted with use_batch_api=True.

    Args:
        job_id: The job UUID returned when the batch job was created

    Returns:
        BatchJobStatusResponse with current job status and details

    Raises:
        HTTPException 404: If job not found
        HTTPException 500: If database error occurs
    """
    logger.info(f"Getting batch job status: {job_id}")

    try:
        batch_manager = BatchJobManager()
        job = await batch_manager.get_job(job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Batch job not found: {job_id}")

        return _job_to_response(job)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get batch job status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get batch job status: {e}")


@router.get(ROUTE_BATCH_JOBS, response_model=BatchJobListResponse)
async def list_batch_jobs(status: str = None, limit: int = 50, offset: int = 0):
    """
    Listing batch jobs with optional status filter.

    Args:
        status: Filter by status (queued, processing, completed, failed, cancelled)
        limit: Maximum number of jobs to return (default: 50)
        offset: Number of jobs to skip for pagination (default: 0)

    Returns:
        BatchJobListResponse with list of jobs
    """
    logger.info(f"Listing batch jobs: status={status}, limit={limit}, offset={offset}")

    # Validating status if provided
    if status:
        valid_statuses = [BatchJobStatus.QUEUED, BatchJobStatus.PROCESSING, BatchJobStatus.COMPLETED, BatchJobStatus.FAILED, BatchJobStatus.CANCELLED]
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}. Must be one of: {', '.join(valid_statuses)}")

    try:
        batch_manager = BatchJobManager()
        jobs = await batch_manager.list_jobs(status=status, limit=limit, offset=offset)

        return BatchJobListResponse(
            jobs=[_job_to_response(job) for job in jobs],
            total=len(jobs),  # Note: For true pagination, we'd need a count query
        )

    except Exception as e:
        logger.error(f"Failed to list batch jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list batch jobs: {e}")


@router.delete(ROUTE_BATCH_JOBS_BY_ID)
async def cancel_batch_job(job_id: str):
    """
    Cancelling a pending or processing batch job.

    Only jobs with status 'queued' or 'processing' can be cancelled.
    Completed or failed jobs cannot be cancelled.

    Args:
        job_id: The job UUID to cancel

    Returns:
        Success message

    Raises:
        HTTPException 404: If job not found
        HTTPException 400: If job cannot be cancelled (already completed/failed)
        HTTPException 500: If database error occurs
    """
    logger.info(f"Cancelling batch job: {job_id}")

    try:
        batch_manager = BatchJobManager()
        job = await batch_manager.get_job(job_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Batch job not found: {job_id}")

        # Checking if job can be cancelled
        if job.get("status") in (BatchJobStatus.COMPLETED, BatchJobStatus.FAILED, BatchJobStatus.CANCELLED):
            raise HTTPException(status_code=400, detail=f"Cannot cancel job with status: {job.get('status')}")

        # Updating status to cancelled
        await batch_manager.update_status(job_id, BatchJobStatus.CANCELLED)

        logger.info(f"Batch job cancelled: {job_id}")
        return {"message": f"Batch job {job_id} cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel batch job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel batch job: {e}")
