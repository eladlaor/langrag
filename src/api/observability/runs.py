"""
Runs API - Historical Data Access & Observability

Provides endpoints for querying and analyzing past newsletter generation runs.
Data is sourced from both the file system (legacy) and MongoDB (current).

Endpoints:
- GET /runs - List all runs with filtering
- GET /runs/{run_id} - Get detailed run information
- GET /runs/{run_id}/newsletter - View newsletter content
- GET /runs/{run_id}/messages - Query messages for a run
- GET /runs/{run_id}/discussions - Query discussions for a run
- GET /runs/stats - Get system statistics
- GET /search/discussions - Semantic search across discussions
"""

import os
import json
import logging
from datetime import datetime, UTC

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import shutil

from constants import (
    COLLECTION_DISCUSSIONS,
    COLLECTION_RUNS,
    DEFAULT_EMBEDDING_MODEL,
    DIR_NAME_CONSOLIDATED,
    DIR_NAME_PER_CHAT,
    DIR_NAME_DISCUSSIONS_FOR_SELECTION,
    DIR_NAME_AFTER_SELECTION,
    DIR_NAME_NEWSLETTER,
    DIR_NAME_LINK_ENRICHMENT,
    DIR_NAME_FINAL_TRANSLATION,
    OUTPUT_FILENAME_RANKED_DISCUSSIONS,
    OUTPUT_FILENAME_NEWSLETTER_JSON,
    OUTPUT_FILENAME_ENRICHED_JSON,
    OUTPUT_FILESTEM_ENRICHED,
    OUTPUT_FILESTEM_ENRICHED_SUMMARY,
    OUTPUT_FILESTEM_NEWSLETTER,
    OUTPUT_BASE_DIR_NAME,
    OUTPUT_DIR_PERIODIC_NEWSLETTER,
    HITL_KEY_PHASE_1_COMPLETE,
    ROUTE_RUNS,
    ROUTE_RUN_NEWSLETTER,
    ROUTE_RUN_NEWSLETTER_RAW,
    ROUTE_RUN_DISCUSSIONS,
    ROUTE_SEARCH_DISCUSSIONS,
    ROUTE_RUNS_STATS,
    ROUTE_MONGODB_RUNS,
    ROUTE_MONGODB_RUN_BY_ID,
    ROUTE_MONGODB_RUN_MESSAGES,
    ROUTE_MONGODB_RUN_DISCUSSIONS,
    ROUTE_MONGODB_RUN_DIAGNOSTICS,
    ROUTE_MONGODB_RUN_POLLS,
    ROUTE_MONGODB_STATS,
    ENGLISH_LANGUAGE_CODES,
    FileFormat,
    NewsletterType,
    RunStatus,
    RunType,
    SearchMethod,
    TextDirection,
)
from custom_types.field_keys import DbFieldKeys, DiscussionKeys, RankingResultKeys

logger = logging.getLogger(__name__)

router = APIRouter()

# Output directories
OUTPUT_BASE_DIR = os.getenv("OUTPUT_DIR", OUTPUT_BASE_DIR_NAME)
PERIODIC_OUTPUT_DIR = os.path.join(OUTPUT_BASE_DIR, OUTPUT_DIR_PERIODIC_NEWSLETTER)


# ============================================================================
# Response Models
# ============================================================================


class RunInfo(BaseModel):
    """Information about a single run."""

    run_id: str = Field(..., description="Unique run identifier (directory name)")
    run_type: str = Field(..., description="Type of run: 'periodic'")
    data_source: str = Field(..., description="Data source name (e.g., 'langtalks')")
    start_date: str = Field(..., description="Start date of the run")
    end_date: str = Field(..., description="End date of the run")
    created_at: str | None = Field(None, description="When the run was created")
    has_consolidated: bool = Field(False, description="Whether consolidated output exists")
    has_per_chat: bool = Field(False, description="Whether per-chat outputs exist")
    has_hitl_pending: bool = Field(False, description="Whether HITL selection is pending")
    newsletter_paths: dict = Field(default_factory=dict, description="Available newsletter file paths")


class RunsListResponse(BaseModel):
    """Response for listing runs."""

    total: int = Field(..., description="Total number of runs")
    runs: list[RunInfo] = Field(..., description="List of run information")


class NewsletterContentResponse(BaseModel):
    """Response for newsletter content."""

    run_id: str
    content_html: str
    content_md: str | None = None
    direction: str = Field(TextDirection.RTL, description="Text direction: 'rtl' or 'ltr'")
    title: str | None = None


class RunSummary(BaseModel):
    """Summary information for a run (MongoDB)"""

    run_id: str
    data_source_name: str
    chat_names: list[str]
    start_date: str
    end_date: str
    status: str
    created_at: str
    completed_at: str | None = None
    metrics: dict | None = None


class RunDetail(BaseModel):
    """Detailed run information including chat status and outputs (MongoDB)"""

    run_id: str
    data_source_name: str
    chat_names: list[str]
    start_date: str
    end_date: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    config: dict
    chats: dict | None = None
    stages: dict | None = None
    consolidated: dict | None = None
    metrics: dict | None = None


class MessageSummary(BaseModel):
    """Summary of a message (MongoDB)"""

    message_id: str
    chat_name: str
    sender: str
    timestamp: int | None = None
    content: str
    word_count: int
    is_translated: bool


class DiscussionInfo(BaseModel):
    """Discussion information."""

    discussion_id: str
    run_id: str
    chat_name: str
    title: str
    nutshell: str = ""
    ranking_score: float | None = None
    rank: int | None = None
    created_at: str | None = None


class DiscussionsResponse(BaseModel):
    """Response for listing discussions."""

    run_id: str
    total: int
    discussions: list[DiscussionInfo]


class DiscussionSummary(BaseModel):
    """Summary of a discussion (MongoDB)"""

    discussion_id: str
    chat_name: str
    title: str
    nutshell: str
    ranking_score: float
    message_count: int
    first_message_timestamp: int | None = None


class SearchResult(BaseModel):
    """Search result with similarity score."""

    discussion_id: str
    run_id: str
    chat_name: str
    title: str
    nutshell: str = ""
    score: float | None = None
    created_at: str | None = None
    similarity_score: float | None = Field(None, description="Cosine similarity (0-1) for vector search")


class SearchResponse(BaseModel):
    """Response for discussion search."""

    query: str
    total: int
    results: list[SearchResult]
    search_metadata: dict = Field(default_factory=dict, description="Search configuration and method used")


class MongoDBStats(BaseModel):
    """MongoDB collection statistics"""

    total_runs: int
    total_messages: int
    total_discussions: int
    completed_runs: int
    failed_runs: int


class RunStats(BaseModel):
    """Run statistics."""

    total_runs: int
    completed_runs: int
    failed_runs: int
    total_discussions: int
    runs_by_source: dict
    recent_runs: list[dict]


class DiagnosticIssueResponse(BaseModel):
    """A single diagnostic issue."""

    severity: str = Field(..., description="Severity: critical, warning, or info")
    category: str = Field(..., description="Issue category (e.g., link_enrichment, translation)")
    message: str = Field(..., description="Human-readable issue description")
    node: str | None = Field(None, description="Graph node where issue occurred")
    timestamp: str = Field(..., description="When the issue was captured")
    details: dict = Field(default_factory=dict, description="Additional context")


class DiagnosticReportResponse(BaseModel):
    """Diagnostic report for a completed run."""

    run_id: str = Field(..., description="Run identifier")
    status: str = Field(..., description="Report status: clean or issues_found")
    total_issues: int | None = Field(None, description="Total number of issues")
    by_severity: dict | None = Field(None, description="Issue counts by severity")
    report: dict | None = Field(None, description="LLM-generated analysis")
    raw_issues: list[DiagnosticIssueResponse] | None = Field(None, description="All captured issues")
    generated_at: str | None = Field(None, description="When the report was generated")


class PollOptionResponse(BaseModel):
    """A single poll option with vote count."""

    option_id: str = Field(..., description="Option identifier")
    text: str = Field(..., description="Option text")
    vote_count: int = Field(0, description="Number of votes for this option")


class PollResponse(BaseModel):
    """A poll extracted from a WhatsApp chat."""

    poll_id: str = Field(..., description="Unique poll identifier")
    chat_name: str = Field(..., description="Source chat name")
    sender: str = Field(..., description="Anonymized sender ID")
    timestamp: int = Field(..., description="Unix timestamp in milliseconds")
    question: str = Field(..., description="Poll question text")
    options: list[PollOptionResponse] = Field(..., description="Poll options with vote counts")
    total_votes: int = Field(0, description="Total votes across all options")
    unique_voter_count: int = Field(0, description="Number of unique voters")


# ============================================================================
# Helper Functions
# ============================================================================


def parse_run_directory(dir_name: str) -> dict:
    """
    Parse run directory name to extract metadata.

    Expected format: {data_source}_{start_date}_to_{end_date}
    Example: langtalks_2025-11-12_to_2025-11-30
    """
    try:
        parts = dir_name.split("_")
        # Find the 'to' separator
        to_index = parts.index("to")

        data_source = "_".join(parts[: to_index - 1])
        start_date = parts[to_index - 1]
        end_date = parts[to_index + 1]

        return {"data_source": data_source, "start_date": start_date, "end_date": end_date}
    except (ValueError, IndexError):
        # Fallback for non-standard naming
        return {"data_source": "unknown", "start_date": "unknown", "end_date": "unknown"}


def get_run_info(run_dir: str, run_type: str) -> RunInfo | None:
    """Get detailed information about a run from its directory."""
    run_id = os.path.basename(run_dir)
    parsed = parse_run_directory(run_id)

    # Get creation time from directory
    try:
        created_at = datetime.fromtimestamp(os.path.getctime(run_dir), tz=UTC).isoformat()
    except OSError:
        created_at = None

    # Check for consolidated outputs
    consolidated_dir = os.path.join(run_dir, DIR_NAME_CONSOLIDATED)
    has_consolidated = os.path.isdir(consolidated_dir)

    # Check for per-chat outputs
    per_chat_dir = os.path.join(run_dir, DIR_NAME_PER_CHAT)
    has_per_chat = os.path.isdir(per_chat_dir)

    # Check for HITL pending state
    has_hitl_pending = False
    ranked_file = os.path.join(consolidated_dir, DIR_NAME_DISCUSSIONS_FOR_SELECTION, OUTPUT_FILENAME_RANKED_DISCUSSIONS)
    after_selection_dir = os.path.join(consolidated_dir, DIR_NAME_AFTER_SELECTION)

    # HITL is NOT pending if after_selection output exists (Phase 2 completed)
    phase2_completed = os.path.isdir(after_selection_dir) and any(os.path.exists(os.path.join(after_selection_dir, subdir, f)) for subdir in [DIR_NAME_NEWSLETTER, DIR_NAME_LINK_ENRICHMENT] for f in [OUTPUT_FILENAME_NEWSLETTER_JSON, OUTPUT_FILENAME_ENRICHED_JSON])

    if not phase2_completed and os.path.exists(ranked_file):
        try:
            with open(ranked_file) as f:
                ranked_data = json.load(f)
                # HITL is pending if phase_1_complete but Phase 2 not done
                has_hitl_pending = ranked_data.get(HITL_KEY_PHASE_1_COMPLETE, False)
        except (OSError, json.JSONDecodeError):
            pass

    # Find available newsletter paths
    newsletter_paths = {}

    # Check consolidated/after_selection first (HITL completed)
    after_selection_dir = os.path.join(consolidated_dir, DIR_NAME_AFTER_SELECTION, DIR_NAME_LINK_ENRICHMENT)
    if os.path.isdir(after_selection_dir):
        for ext in ["html", "md", "json"]:
            path = os.path.join(after_selection_dir, f"{OUTPUT_FILESTEM_ENRICHED}.{ext}")
            if os.path.exists(path):
                newsletter_paths[f"consolidated_{ext}"] = path

    # Fallback to consolidated/newsletter
    if not newsletter_paths:
        newsletter_dir = os.path.join(consolidated_dir, DIR_NAME_NEWSLETTER)
        if os.path.isdir(newsletter_dir):
            for ext in ["html", "md", "json"]:
                path = os.path.join(newsletter_dir, f"{OUTPUT_FILESTEM_NEWSLETTER}.{ext}")
                if os.path.exists(path):
                    newsletter_paths[f"consolidated_{ext}"] = path

    # Also check link_enrichment in consolidated root
    link_enrichment_dir = os.path.join(consolidated_dir, DIR_NAME_LINK_ENRICHMENT)
    if os.path.isdir(link_enrichment_dir):
        for ext in ["html", "md", "json"]:
            for prefix in [OUTPUT_FILESTEM_ENRICHED, OUTPUT_FILESTEM_ENRICHED_SUMMARY]:
                path = os.path.join(link_enrichment_dir, f"{prefix}.{ext}")
                if os.path.exists(path) and f"consolidated_{ext}" not in newsletter_paths:
                    newsletter_paths[f"consolidated_{ext}"] = path
                    break

    # Check per-chat directories for single-chat runs (no consolidated output)
    # This handles runs where only one chat is processed (no consolidated output)
    if not newsletter_paths and not has_consolidated:
        for chat_dir_name in os.listdir(run_dir):
            chat_dir = os.path.join(run_dir, chat_dir_name)
            if not os.path.isdir(chat_dir) or chat_dir_name in [DIR_NAME_CONSOLIDATED, DIR_NAME_PER_CHAT]:
                continue

            # Check link_enrichment first (enriched newsletter)
            chat_enrichment_dir = os.path.join(chat_dir, DIR_NAME_LINK_ENRICHMENT)
            if os.path.isdir(chat_enrichment_dir):
                for ext in ["html", "md", "json"]:
                    for prefix in [OUTPUT_FILESTEM_ENRICHED_SUMMARY, OUTPUT_FILESTEM_ENRICHED]:
                        path = os.path.join(chat_enrichment_dir, f"{prefix}.{ext}")
                        if os.path.exists(path):
                            newsletter_paths[f"per_chat_{ext}"] = path
                            break

            # Fallback to newsletter directory
            if not newsletter_paths:
                chat_newsletter_dir = os.path.join(chat_dir, DIR_NAME_NEWSLETTER)
                if os.path.isdir(chat_newsletter_dir):
                    for ext in ["html", "md", "json"]:
                        path = os.path.join(chat_newsletter_dir, f"{OUTPUT_FILESTEM_NEWSLETTER}.{ext}")
                        if os.path.exists(path):
                            newsletter_paths[f"per_chat_{ext}"] = path

            # Only need to find one chat's newsletter for single-chat runs
            if newsletter_paths:
                break

    return RunInfo(run_id=run_id, run_type=run_type, data_source=parsed["data_source"], start_date=parsed["start_date"], end_date=parsed["end_date"], created_at=created_at, has_consolidated=has_consolidated, has_per_chat=has_per_chat, has_hitl_pending=has_hitl_pending, newsletter_paths=newsletter_paths)


# ============================================================================
# File-Based Endpoints (Legacy)
# ============================================================================


@router.get(ROUTE_RUNS, response_model=RunsListResponse)
async def list_runs(run_type: str | None = Query(None, description="Filter by run type: 'periodic'"), data_source: str | None = Query(None, description="Filter by data source"), limit: int = Query(50, ge=1, le=200, description="Maximum number of runs to return"), offset: int = Query(0, ge=0, description="Offset for pagination")):
    """
    List all newsletter generation runs.

    Returns runs sorted by creation date (newest first).
    Sources data from file system (legacy) for backward compatibility.
    """
    runs = []

    # Scan periodic runs
    if run_type is None or run_type == RunType.PERIODIC:
        if os.path.isdir(PERIODIC_OUTPUT_DIR):
            for dir_name in os.listdir(PERIODIC_OUTPUT_DIR):
                dir_path = os.path.join(PERIODIC_OUTPUT_DIR, dir_name)
                if os.path.isdir(dir_path):
                    run_info = get_run_info(dir_path, RunType.PERIODIC)
                    if run_info:
                        runs.append(run_info)

    # Filter by data source if specified
    if data_source:
        runs = [r for r in runs if r.data_source == data_source]

    # Sort by creation date (newest first)
    runs.sort(key=lambda r: r.created_at or "", reverse=True)

    # Apply pagination
    total = len(runs)
    runs = runs[offset : offset + limit]

    return RunsListResponse(total=total, runs=runs)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, run_type: str = Query(RunType.PERIODIC, description="Run type: 'periodic'")):
    """
    Delete a newsletter generation run and all its associated files.

    Removes the entire run directory from the file system.
    """
    # Determine base directory
    if run_type == RunType.PERIODIC:
        base_dir = PERIODIC_OUTPUT_DIR
    else:
        raise HTTPException(status_code=400, detail=f"Invalid run_type: {run_type}. Only 'periodic' is supported.")

    run_dir = os.path.join(base_dir, run_id)

    if not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    try:
        shutil.rmtree(run_dir)
        logger.info(f"Deleted run directory: {run_dir}")
        return {"status": "deleted", "run_id": run_id, "message": f"Run {run_id} deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {str(e)}")


@router.get(ROUTE_RUN_NEWSLETTER)
async def get_newsletter_content(run_id: str, run_type: str = Query(RunType.PERIODIC, description="Run type: 'periodic'"), format: str = Query(FileFormat.HTML, description="Content format: 'html', 'md', or 'json'"), source: str = Query(NewsletterType.CONSOLIDATED, description="Source: 'consolidated' or 'per_chat'")):
    """
    Get newsletter content for a specific run.

    Returns the newsletter in the requested format with metadata for UI rendering.
    """
    # Determine base directory
    if run_type == RunType.PERIODIC:
        base_dir = PERIODIC_OUTPUT_DIR
    else:
        raise HTTPException(status_code=400, detail=f"Invalid run_type: {run_type}. Only 'periodic' is supported.")

    run_dir = os.path.join(base_dir, run_id)

    if not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # Search for newsletter file
    search_paths = []

    if source == NewsletterType.CONSOLIDATED:
        # Priority order for consolidated newsletters
        search_paths = [
            os.path.join(run_dir, DIR_NAME_CONSOLIDATED, DIR_NAME_AFTER_SELECTION, DIR_NAME_LINK_ENRICHMENT, f"{OUTPUT_FILESTEM_ENRICHED}.{format}"),
            os.path.join(run_dir, DIR_NAME_CONSOLIDATED, DIR_NAME_LINK_ENRICHMENT, f"{OUTPUT_FILESTEM_ENRICHED}.{format}"),
            os.path.join(run_dir, DIR_NAME_CONSOLIDATED, DIR_NAME_LINK_ENRICHMENT, f"{OUTPUT_FILESTEM_ENRICHED_SUMMARY}.{format}"),
            os.path.join(run_dir, DIR_NAME_CONSOLIDATED, DIR_NAME_NEWSLETTER, f"{OUTPUT_FILESTEM_NEWSLETTER}.{format}"),
            os.path.join(run_dir, DIR_NAME_CONSOLIDATED, DIR_NAME_FINAL_TRANSLATION, f"*_translated_summary.{format}"),
        ]

    # Find first existing file
    content_path = None
    for path in search_paths:
        if "*" in path:
            # Handle glob pattern
            parent = os.path.dirname(path)
            if os.path.isdir(parent):
                for f in os.listdir(parent):
                    if f.endswith(f".{format}"):
                        content_path = os.path.join(parent, f)
                        break
        elif os.path.exists(path):
            content_path = path
            break

    # Fallback to per-chat directories for single-chat runs (no consolidated output)
    if not content_path:
        for chat_dir_name in os.listdir(run_dir):
            chat_dir = os.path.join(run_dir, chat_dir_name)
            if not os.path.isdir(chat_dir) or chat_dir_name in [DIR_NAME_CONSOLIDATED, DIR_NAME_PER_CHAT]:
                continue

            # Check link_enrichment first
            per_chat_paths = [
                os.path.join(chat_dir, DIR_NAME_LINK_ENRICHMENT, f"{OUTPUT_FILESTEM_ENRICHED_SUMMARY}.{format}"),
                os.path.join(chat_dir, DIR_NAME_LINK_ENRICHMENT, f"{OUTPUT_FILESTEM_ENRICHED}.{format}"),
                os.path.join(chat_dir, DIR_NAME_NEWSLETTER, f"{OUTPUT_FILESTEM_NEWSLETTER}.{format}"),
            ]
            for path in per_chat_paths:
                if os.path.exists(path):
                    content_path = path
                    break
            if content_path:
                break

    if not content_path:
        raise HTTPException(status_code=404, detail=f"Newsletter not found for run {run_id} in {format} format")

    # Read content
    try:
        with open(content_path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read newsletter: {e}")

    # Determine text direction based on content or metadata
    direction = TextDirection.RTL  # Default for Hebrew

    # Try to detect from ranked_discussions.json
    ranked_file = os.path.join(run_dir, DIR_NAME_CONSOLIDATED, DIR_NAME_DISCUSSIONS_FOR_SELECTION, OUTPUT_FILENAME_RANKED_DISCUSSIONS)
    if os.path.exists(ranked_file):
        try:
            with open(ranked_file) as f:
                ranked_data = json.load(f)
                summary_format = ranked_data.get("summary_format", "")
                # English format typically means LTR
                if any(code in summary_format.lower() for code in ENGLISH_LANGUAGE_CODES):
                    direction = TextDirection.LTR
        except (OSError, json.JSONDecodeError):
            pass

    # Extract title if HTML
    title = None
    if format == FileFormat.HTML:
        import re

        title_match = re.search(r"<h1[^>]*>([^<]+)</h1>", content)
        if title_match:
            title = title_match.group(1)

    # For HTML format, return raw HTML response for direct rendering
    if format == FileFormat.HTML:
        return {"run_id": run_id, "content_html": content, "content_md": None, "direction": direction, "title": title, "file_path": content_path}
    elif format == FileFormat.MARKDOWN:
        return {"run_id": run_id, "content_html": None, "content_md": content, "direction": direction, "title": None, "file_path": content_path}
    else:
        # JSON format
        return {"run_id": run_id, "content_json": content, "direction": direction, "file_path": content_path}


@router.get(ROUTE_RUN_NEWSLETTER_RAW, response_class=HTMLResponse)
async def get_newsletter_raw_html(run_id: str, run_type: str = Query(RunType.PERIODIC, description="Run type: 'periodic'")):
    """
    Get raw HTML newsletter for direct browser rendering.

    This endpoint returns the HTML file directly, suitable for iframe embedding
    or direct viewing.
    """
    result = await get_newsletter_content(run_id, run_type, FileFormat.HTML, NewsletterType.CONSOLIDATED)
    return HTMLResponse(content=result["content_html"])


# ============================================================================
# MongoDB-Backed Endpoints
# ============================================================================


@router.get(ROUTE_MONGODB_RUNS, response_model=list[RunSummary])
async def list_mongodb_runs(data_source: str | None = Query(None, description="Filter by data source"), status: str | None = Query(None, description="Filter by status"), limit: int = Query(20, ge=1, le=100, description="Maximum runs to return")):
    """
    List recent runs from MongoDB with optional filtering.

    Returns runs sorted by creation date (newest first).
    """
    try:
        from db.connection import get_database
        from db.repositories.runs import RunsRepository

        db = await get_database()
        runs_repo = RunsRepository(db)

        runs = await runs_repo.get_recent_runs(limit=limit, data_source_name=data_source, status=status)

        return [RunSummary(run_id=run["run_id"], data_source_name=run.get("data_source_name", "unknown"), chat_names=run.get("chat_names", []), start_date=run.get("start_date", ""), end_date=run.get("end_date", ""), status=run.get("status", "unknown"), created_at=str(run.get("created_at", "")), completed_at=str(run.get("completed_at")) if run.get("completed_at") else None, metrics=run.get("metrics")) for run in runs]
    except Exception as e:
        logger.error(f"Failed to list runs from MongoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch runs: {str(e)}")


@router.get(ROUTE_MONGODB_RUN_BY_ID, response_model=RunDetail)
async def get_mongodb_run(run_id: str):
    """
    Get detailed information about a specific run from MongoDB.

    Includes chat-level status, stage progress, and output paths.
    """
    try:
        from db.connection import get_database
        from db.repositories.runs import RunsRepository

        db = await get_database()
        runs_repo = RunsRepository(db)

        run = await runs_repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        return RunDetail(
            run_id=run["run_id"],
            data_source_name=run.get("data_source_name", "unknown"),
            chat_names=run.get("chat_names", []),
            start_date=run.get("start_date", ""),
            end_date=run.get("end_date", ""),
            status=run.get("status", "unknown"),
            created_at=str(run.get("created_at", "")),
            started_at=str(run.get("started_at")) if run.get("started_at") else None,
            completed_at=str(run.get("completed_at")) if run.get("completed_at") else None,
            config=run.get("config", {}),
            chats=run.get("chats"),
            stages=run.get("stages"),
            consolidated=run.get("consolidated"),
            metrics=run.get("metrics"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get run {run_id} from MongoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch run: {str(e)}")


@router.get(ROUTE_MONGODB_RUN_MESSAGES, response_model=list[MessageSummary])
async def get_mongodb_run_messages(run_id: str, chat_name: str | None = Query(None, description="Filter by chat name"), limit: int = Query(1000, ge=1, le=10000, description="Maximum messages to return")):
    """
    Get messages for a specific run from MongoDB.

    Optionally filter by chat name. Returns messages sorted chronologically.
    """
    try:
        from db.connection import get_database
        from db.repositories.messages import MessagesRepository

        db = await get_database()
        messages_repo = MessagesRepository(db)

        messages = await messages_repo.get_messages_by_run(run_id=run_id, chat_name=chat_name, limit=limit)

        return [MessageSummary(message_id=msg["message_id"], chat_name=msg.get(DbFieldKeys.CHAT_NAME, "unknown"), sender=msg.get("sender", "unknown"), timestamp=msg.get("timestamp"), content=msg.get(DbFieldKeys.CONTENT, ""), word_count=msg.get("word_count", 0), is_translated=msg.get("is_translated", False)) for msg in messages]
    except Exception as e:
        logger.error(f"Failed to get messages for run {run_id} from MongoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch messages: {str(e)}")


@router.get(ROUTE_MONGODB_RUN_DISCUSSIONS, response_model=list[DiscussionSummary])
async def get_mongodb_run_discussions(run_id: str, sort_by_ranking: bool = Query(True, description="Sort by ranking score (highest first)")):
    """
    Get discussions for a specific run from MongoDB.

    Returns discussions with their rankings, sorted by score or creation date.
    """
    try:
        from db.connection import get_database
        from db.repositories.discussions import DiscussionsRepository

        db = await get_database()
        discussions_repo = DiscussionsRepository(db)

        discussions = await discussions_repo.get_discussions_by_run(run_id=run_id, sort_by_ranking=sort_by_ranking)

        return [DiscussionSummary(discussion_id=disc[DbFieldKeys.DISCUSSION_ID], chat_name=disc.get(DbFieldKeys.CHAT_NAME, "unknown"), title=disc.get(DbFieldKeys.TITLE, ""), nutshell=disc.get(DbFieldKeys.NUTSHELL, ""), ranking_score=float(disc.get(DbFieldKeys.RANKING_SCORE, 0)), message_count=disc.get(DbFieldKeys.MESSAGE_COUNT, 0), first_message_timestamp=disc.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP)) for disc in discussions]
    except Exception as e:
        logger.error(f"Failed to get discussions for run {run_id} from MongoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch discussions: {str(e)}")


@router.get(ROUTE_MONGODB_RUN_DIAGNOSTICS, response_model=DiagnosticReportResponse)
async def get_mongodb_run_diagnostics(run_id: str):
    """
    Get diagnostic report for a specific run from MongoDB.

    Returns diagnostic issues captured during the run, including:
    - Link enrichment failures (web search, metadata fetch)
    - Translation service issues
    - Low message counts
    - LLM-generated analysis and recommendations

    If no diagnostics are available, returns a "clean" status.
    """
    try:
        from db.connection import get_database
        from db.repositories.runs import RunsRepository

        db = await get_database()
        runs_repo = RunsRepository(db)

        run = await runs_repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

        diagnostic_report = run.get("diagnostic_report")

        # No diagnostic report available
        if not diagnostic_report:
            return DiagnosticReportResponse(run_id=run_id, status="clean", total_issues=0, by_severity={"critical": 0, "warning": 0, "info": 0}, report=None, raw_issues=[], generated_at=None)

        # Convert raw_issues to response model
        raw_issues = diagnostic_report.get("raw_issues", [])
        issues_response = [DiagnosticIssueResponse(severity=issue["severity"], category=issue["category"], message=issue["message"], node=issue.get("node"), timestamp=issue["timestamp"], details=issue.get("details", {})) for issue in raw_issues]

        return DiagnosticReportResponse(run_id=run_id, status=diagnostic_report.get("status", "unknown"), total_issues=diagnostic_report.get("total_issues"), by_severity=diagnostic_report.get("by_severity"), report=diagnostic_report.get("report"), raw_issues=issues_response, generated_at=diagnostic_report.get("generated_at").isoformat() if diagnostic_report.get("generated_at") else None)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get diagnostics for run {run_id} from MongoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch diagnostics: {str(e)}")


@router.get(ROUTE_MONGODB_STATS, response_model=MongoDBStats)
async def get_mongodb_stats():
    """
    Get MongoDB collection statistics.

    Returns counts for runs, messages, discussions, and run statuses.
    """
    try:
        from db.connection import get_database
        from db.repositories.runs import RunsRepository
        from db.repositories.messages import MessagesRepository
        from db.repositories.discussions import DiscussionsRepository

        db = await get_database()
        runs_repo = RunsRepository(db)
        messages_repo = MessagesRepository(db)
        discussions_repo = DiscussionsRepository(db)

        # Count documents
        total_runs = await runs_repo.count({})
        total_messages = await messages_repo.count({})
        total_discussions = await discussions_repo.count({})
        completed_runs = await runs_repo.count({"status": RunStatus.COMPLETED})
        failed_runs = await runs_repo.count({"status": RunStatus.FAILED})

        return MongoDBStats(total_runs=total_runs, total_messages=total_messages, total_discussions=total_discussions, completed_runs=completed_runs, failed_runs=failed_runs)
    except Exception as e:
        logger.error(f"Failed to get MongoDB stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")


@router.get(ROUTE_RUN_DISCUSSIONS, response_model=DiscussionsResponse)
async def get_run_discussions(run_id: str, limit: int = Query(100, ge=1, le=500, description="Maximum discussions to return"), offset: int = Query(0, ge=0, description="Offset for pagination")):
    """
    Get discussions for a specific run.

    Returns all discussions stored during the run, including their rankings
    and metadata.
    """
    try:
        from db.connection import get_database
        from db.repositories.discussions import DiscussionsRepository

        db = await get_database()
        repo = DiscussionsRepository(db)

        # Get discussions for this run
        discussions = await repo.get_discussions_by_run(run_id, limit=limit, offset=offset)

        if not discussions:
            # Check if run exists at all
            from db.repositories.runs import RunsRepository

            runs_repo = RunsRepository(db)
            run = await runs_repo.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
            # Run exists but no discussions stored
            return DiscussionsResponse(run_id=run_id, total=0, discussions=[])

        # Transform to response model
        result_discussions = [DiscussionInfo(discussion_id=d.get(DbFieldKeys.DISCUSSION_ID, ""), run_id=d.get("run_id", ""), chat_name=d.get(DbFieldKeys.CHAT_NAME, ""), title=d.get(DbFieldKeys.TITLE, ""), nutshell=d.get(DbFieldKeys.NUTSHELL, ""), ranking_score=d.get(DbFieldKeys.RANKING_SCORE), rank=d.get(RankingResultKeys.RANK), created_at=d.get("created_at").isoformat() if d.get("created_at") else None) for d in discussions]

        return DiscussionsResponse(run_id=run_id, total=len(result_discussions), discussions=result_discussions)

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to get discussions from MongoDB: {e}")
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


@router.get(ROUTE_SEARCH_DISCUSSIONS, response_model=SearchResponse)
async def search_discussions(query: str = Query(..., min_length=2, description="Search query"), run_id: str | None = Query(None, description="Filter by run ID"), time_range_days: int | None = Query(None, ge=1, le=365, description="Limit to last N days"), min_similarity: float = Query(0.75, ge=0.0, le=1.0, description="Minimum similarity score (vector search only)"), limit: int = Query(20, ge=1, le=100, description="Maximum results")):
    """
    Semantic search across all historical discussions.

    **Features:**
    - Vector search for semantic similarity (if mongot available)
    - Time-based filtering (last N days)
    - Minimum similarity threshold
    - Graceful fallback to text search

    **Use Cases:**
    - "Has the community discussed RAG chunking before?"
    - "Find all discussions about LangGraph state management"
    - "What did we talk about regarding API rate limiting?"

    **Example:**
        GET /api/search/discussions?query=RAG+chunking&time_range_days=90&limit=5
    """
    try:
        from datetime import timedelta
        from db.connection import get_database
        from db.repositories.discussions import DiscussionsRepository

        logger.info(f"Semantic search: query='{query}', time_range={time_range_days}, " f"min_similarity={min_similarity}, limit={limit}")

        db = await get_database()
        repo = DiscussionsRepository(db)

        # Try vector search first if embeddings available
        results = []
        search_method = "unknown"

        try:
            from utils.embedding import EmbeddingProviderFactory

            embedder = EmbeddingProviderFactory.create()
            query_embedding = embedder.embed_text(query)

            if query_embedding:
                # Vector search pipeline
                pipeline = [
                    {
                        "$vectorSearch": {
                            "index": "discussion_embeddings",
                            "path": "embedding",
                            "queryVector": query_embedding,
                            "numCandidates": limit * 10,
                            "limit": limit,
                        }
                    },
                    {"$addFields": {"similarity_score": {"$meta": "vectorSearchScore"}}},
                    {"$match": {"similarity_score": {"$gte": min_similarity}}},
                ]

                # Add time range filter if specified
                if time_range_days:
                    cutoff_date = datetime.now(UTC) - timedelta(days=time_range_days)
                    pipeline.insert(1, {"$match": {"created_at": {"$gte": cutoff_date}}})

                # Add run_id filter if specified
                if run_id:
                    pipeline.insert(1, {"$match": {"run_id": run_id}})

                # Project fields
                pipeline.append({"$project": {"_id": 0, DbFieldKeys.DISCUSSION_ID: 1, "run_id": 1, DbFieldKeys.CHAT_NAME: 1, DbFieldKeys.TITLE: 1, DbFieldKeys.NUTSHELL: 1, "created_at": 1, "similarity_score": 1}})

                collection = db[COLLECTION_DISCUSSIONS]
                results = await collection.aggregate(pipeline).to_list(length=limit)
                search_method = SearchMethod.VECTOR

                logger.info(f"Vector search returned {len(results)} results")

        except Exception as vector_err:
            logger.debug(f"Vector search unavailable: {vector_err}, falling back to text search")

        # Fall back to text search if vector search failed or returned nothing
        if not results:
            results = await repo.search_discussions(query=query, limit=limit)
            # Filter by run_id if specified (text search doesn't support it natively)
            if run_id:
                results = [r for r in results if r.get("run_id") == run_id]
            search_method = SearchMethod.FULL_TEXT

            logger.info(f"Text search returned {len(results)} results")

        search_results = [SearchResult(discussion_id=r.get(DbFieldKeys.DISCUSSION_ID, ""), run_id=r.get("run_id", ""), chat_name=r.get(DbFieldKeys.CHAT_NAME, ""), title=r.get(DbFieldKeys.TITLE, ""), nutshell=r.get(DbFieldKeys.NUTSHELL, ""), score=r.get("score"), created_at=r.get("created_at").isoformat() if r.get("created_at") else None, similarity_score=r.get("similarity_score")) for r in results]

        return SearchResponse(query=query, total=len(search_results), results=search_results, search_metadata={"method": search_method, "embedding_model": DEFAULT_EMBEDDING_MODEL if search_method == SearchMethod.VECTOR else None, "min_similarity": min_similarity if search_method == SearchMethod.VECTOR else None, "time_range_days": time_range_days, "run_id_filter": run_id})

    except Exception as e:
        logger.warning(f"Discussion search failed: {e}")
        raise HTTPException(status_code=503, detail=f"Search unavailable: {e}")


@router.get(ROUTE_RUNS_STATS, response_model=RunStats)
async def get_run_stats():
    """
    Get aggregated statistics about all runs.

    Returns counts, breakdowns by source, and recent runs.
    """
    try:
        from db.connection import get_database
        from db.repositories.runs import RunsRepository
        from db.repositories.discussions import DiscussionsRepository

        db = await get_database()
        runs_repo = RunsRepository(db)
        disc_repo = DiscussionsRepository(db)

        # Get run counts by status
        runs_collection = db[COLLECTION_RUNS]
        discussions_collection = db[COLLECTION_DISCUSSIONS]

        total_runs = await runs_collection.count_documents({})
        completed_runs = await runs_collection.count_documents({"status": RunStatus.COMPLETED})
        failed_runs = await runs_collection.count_documents({"status": RunStatus.FAILED})
        total_discussions = await discussions_collection.count_documents({})

        # Get runs grouped by data source
        pipeline = [{"$group": {"_id": "$data_source_name", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
        source_counts = await runs_collection.aggregate(pipeline).to_list(length=20)
        runs_by_source = {item["_id"]: item["count"] for item in source_counts if item["_id"]}

        # Get recent runs
        recent = await runs_repo.get_recent_runs(limit=5)
        recent_runs = [{"run_id": r.get("run_id"), "data_source_name": r.get("data_source_name"), "status": r.get("status"), "created_at": r.get("created_at").isoformat() if r.get("created_at") else None} for r in recent]

        return RunStats(total_runs=total_runs, completed_runs=completed_runs, failed_runs=failed_runs, total_discussions=total_discussions, runs_by_source=runs_by_source, recent_runs=recent_runs)

    except Exception as e:
        logger.warning(f"Failed to get run stats from MongoDB: {e}")
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


@router.get(ROUTE_MONGODB_RUN_POLLS, response_model=list[PollResponse])
async def get_mongodb_run_polls(run_id: str, chat_name: str | None = Query(None, description="Filter by chat name")):
    """
    Get polls for a specific run from MongoDB.

    Returns polls with their questions, options, and vote counts.
    """
    try:
        from db.connection import get_database
        from db.repositories.polls import PollsRepository
        from custom_types.field_keys import PollDbKeys

        db = await get_database()
        polls_repo = PollsRepository(db)

        polls = await polls_repo.get_polls_by_run(run_id=run_id, chat_name=chat_name)

        return [PollResponse(poll_id=poll[PollDbKeys.POLL_ID], chat_name=poll.get(PollDbKeys.CHAT_NAME, "unknown"), sender=poll.get(PollDbKeys.SENDER, ""), timestamp=poll.get(PollDbKeys.TIMESTAMP, 0), question=poll.get(PollDbKeys.QUESTION, ""), options=[PollOptionResponse(option_id=opt.get(PollDbKeys.OPTION_ID, ""), text=opt.get(PollDbKeys.OPTION_TEXT, ""), vote_count=opt.get(PollDbKeys.VOTE_COUNT, 0)) for opt in poll.get(PollDbKeys.OPTIONS, [])], total_votes=poll.get(PollDbKeys.TOTAL_VOTES, 0), unique_voter_count=poll.get(PollDbKeys.UNIQUE_VOTER_COUNT, 0)) for poll in polls]
    except Exception as e:
        logger.error(f"Failed to get polls for run {run_id} from MongoDB: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch polls: {str(e)}")
