"""
Scheduled Newsletter API Endpoints

Provides REST API for managing newsletter generation schedules.
Schedules are stored in MongoDB and executed by APScheduler (background).

Endpoints:
- POST /api/schedules - Create a new schedule
- GET /api/schedules - List all schedules
- GET /api/schedules/due - Get schedules due to run
- GET /api/schedules/status - Get scheduler status
- POST /api/schedules/trigger - Manually trigger schedule check
- GET /api/schedules/{schedule_id} - Get a specific schedule
- PATCH /api/schedules/{schedule_id} - Update a schedule
- DELETE /api/schedules/{schedule_id} - Delete a schedule
- PATCH /api/schedules/{schedule_id}/toggle - Enable/disable a schedule
- POST /api/schedules/{schedule_id}/mark_complete - Mark schedule run complete
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from constants import SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME, ScheduleRunStatus, DEFAULT_LANGUAGE, SummaryFormats
from db.scheduled_newsletters import _get_schedule_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])


# =============================================================================
# Pydantic Request/Response Models
# =============================================================================


class ScheduleCreateRequest(BaseModel):
    """Request model for creating a new newsletter schedule."""

    name: str = Field(..., min_length=1, max_length=100, description="Schedule name")
    interval_days: int = Field(..., ge=1, le=30, description="Days between newsletter runs (1-30)")
    run_time: str = Field(SCHEDULE_DEFAULT_RUN_TIME, description="Time to run the newsletter generation (HH:MM in UTC)")
    data_source_name: str = Field(..., description="Data source name (langtalks, mcp_israel, n8n_israel, etc.)")
    whatsapp_chat_names_to_include: list[str] = Field(..., min_length=1, description="WhatsApp chat names to include in newsletter")
    email_recipients: list[str] = Field(..., min_length=1, description="Email addresses to send newsletter notifications to")
    desired_language_for_summary: str = Field(DEFAULT_LANGUAGE, description="Target language for newsletter summary")
    summary_format: str = Field(SummaryFormats.LANGTALKS_FORMAT, description="Newsletter format (langtalks_format or mcp_israel_format)")
    consolidate_chats: bool = Field(True, description="Consolidate multiple chats into single newsletter")
    enabled: bool = Field(True, description="Whether schedule is enabled")

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, v: str) -> str:
        """Validate run_time is in HH:MM format."""
        try:
            parts = v.split(":")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time values")
            return f"{hour:02d}:{minute:02d}"
        except (ValueError, AttributeError) as e:
            raise ValueError(f"run_time must be in HH:MM format (24-hour): {e}")

    @field_validator("email_recipients")
    @classmethod
    def validate_email_recipients(cls, v: list[str]) -> list[str]:
        """Basic email format validation."""
        for email in v:
            if "@" not in email or "." not in email:
                raise ValueError(f"Invalid email format: {email}")
        return v


class ScheduleUpdateRequest(BaseModel):
    """Request model for updating a schedule."""

    name: str | None = Field(None, min_length=1, max_length=100)
    interval_days: int | None = Field(None, ge=1, le=30)
    run_time: str | None = None
    data_source_name: str | None = None
    whatsapp_chat_names_to_include: list[str] | None = None
    email_recipients: list[str] | None = None
    desired_language_for_summary: str | None = None
    summary_format: str | None = None
    consolidate_chats: bool | None = None
    enabled: bool | None = None

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, v: str | None) -> str | None:
        """Validate run_time is in HH:MM format."""
        if v is None:
            return v
        try:
            parts = v.split(":")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Invalid time values")
            return f"{hour:02d}:{minute:02d}"
        except (ValueError, AttributeError) as e:
            raise ValueError(f"run_time must be in HH:MM format (24-hour): {e}")


class MarkCompleteRequest(BaseModel):
    """Request model for marking a schedule run as complete."""

    success: bool = Field(True, description="Whether the run succeeded")
    error_message: str | None = Field(None, description="Error message if failed")


class ScheduleResponse(BaseModel):
    """Response model for a single schedule."""

    id: str
    name: str
    interval_days: int
    run_time: str
    data_source_name: str
    whatsapp_chat_names_to_include: list[str]
    email_recipients: list[str]
    desired_language_for_summary: str
    summary_format: str
    consolidate_chats: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_run: datetime | None
    last_run_status: str | None
    next_run: datetime
    run_count: int

    @classmethod
    def from_db(cls, doc: dict) -> "ScheduleResponse":
        """Create response from MongoDB document."""
        return cls(
            id=doc["_id"],
            name=doc["name"],
            interval_days=doc["interval_days"],
            run_time=doc.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME),
            data_source_name=doc["data_source_name"],
            whatsapp_chat_names_to_include=doc["whatsapp_chat_names_to_include"],
            email_recipients=doc["email_recipients"],
            desired_language_for_summary=doc.get("desired_language_for_summary", DEFAULT_LANGUAGE),
            summary_format=doc.get("summary_format", SummaryFormats.LANGTALKS_FORMAT),
            consolidate_chats=doc.get("consolidate_chats", True),
            enabled=doc.get("enabled", True),
            created_at=doc["created_at"],
            updated_at=doc.get("updated_at", doc["created_at"]),
            last_run=doc.get("last_run"),
            last_run_status=doc.get("last_run_status"),
            next_run=doc["next_run"],
            run_count=doc.get("run_count", 0),
        )


class ScheduleListResponse(BaseModel):
    """Response model for listing schedules."""

    schedules: list[ScheduleResponse]
    total: int


class DueSchedulesResponse(BaseModel):
    """Response model for due schedules."""

    schedules: list[dict]  # Raw dict for consumption
    count: int


class SchedulerStatusResponse(BaseModel):
    """Response model for scheduler status."""

    running: bool
    next_check: str | None = None
    message: str


# =============================================================================
# API Endpoints
# =============================================================================


@router.get("/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status():
    """
    Get the current status of the newsletter scheduler.

    Returns whether the scheduler is running and when
    the next schedule check will occur.
    """
    try:
        from scheduler.newsletter_scheduler import is_scheduler_running, get_scheduler

        running = is_scheduler_running()
        scheduler = get_scheduler()

        next_check = None
        if running:
            job = scheduler.get_job("newsletter_schedule_checker")
            if job and job.next_run_time:
                next_check = job.next_run_time.isoformat()

        return SchedulerStatusResponse(running=running, next_check=next_check, message="Scheduler is running" if running else "Scheduler is not running")
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        return SchedulerStatusResponse(running=False, message=f"Error checking scheduler: {str(e)}")


@router.post("/trigger")
async def trigger_schedule_check():
    """
    Manually trigger a schedule check.

    This will immediately check for due schedules and execute them,
    regardless of the regular polling interval.
    """
    try:
        from scheduler.newsletter_scheduler import check_and_run_schedules

        logger.info("Manual schedule check triggered via API")
        await check_and_run_schedules()

        return {"message": "Schedule check completed"}
    except Exception as e:
        logger.error(f"Manual schedule check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=dict, status_code=201)
async def create_schedule(request: ScheduleCreateRequest):
    """
    Create a new newsletter schedule.

    The schedule will be stored in MongoDB and executed
    automatically by the background scheduler.
    """
    try:
        manager = _get_schedule_manager()
        schedule_data = request.model_dump()
        schedule_id = await manager.create_schedule(schedule_data)

        logger.info(f"Created schedule: {schedule_id} (name: {request.name})")
        return {"id": schedule_id, "message": f"Schedule '{request.name}' created successfully"}
    except Exception as e:
        logger.error(f"Failed to create schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=ScheduleListResponse)
async def list_schedules():
    """
    List all newsletter schedules.

    Returns all schedules sorted by creation date (newest first).
    """
    try:
        manager = _get_schedule_manager()
        schedules = await manager.list_all()

        return ScheduleListResponse(schedules=[ScheduleResponse.from_db(s) for s in schedules], total=len(schedules))
    except Exception as e:
        logger.error(f"Failed to list schedules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/due", response_model=DueSchedulesResponse)
async def get_due_schedules():
    """
    Get schedules that are due to run.

    This endpoint is polled by n8n to check for schedules
    that need to be executed. Returns raw schedule documents
    for n8n workflow consumption.

    A schedule is due when:
    - enabled = True
    - next_run <= current time
    """
    try:
        manager = _get_schedule_manager()
        schedules = await manager.get_due_schedules()

        logger.info(f"Returning {len(schedules)} due schedules for n8n")
        return DueSchedulesResponse(schedules=schedules, count=len(schedules))
    except Exception as e:
        logger.error(f"Failed to get due schedules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(schedule_id: str):
    """Get a specific schedule by ID."""
    try:
        manager = _get_schedule_manager()
        schedule = await manager.get_by_id(schedule_id)

        if not schedule:
            raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")

        return ScheduleResponse.from_db(schedule)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(schedule_id: str, request: ScheduleUpdateRequest):
    """
    Update a schedule.

    Only provided fields will be updated.
    """
    try:
        manager = _get_schedule_manager()

        # Only include fields that were explicitly provided in the request
        updates = request.model_dump(exclude_unset=True)

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        updated = await manager.update(schedule_id, updates)
        logger.info(f"Updated schedule: {schedule_id}")
        return ScheduleResponse.from_db(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    try:
        manager = _get_schedule_manager()
        deleted = await manager.delete(schedule_id)

        if not deleted:
            raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")

        logger.info(f"Deleted schedule: {schedule_id}")
        return {"message": f"Schedule {schedule_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{schedule_id}/toggle", response_model=ScheduleResponse)
async def toggle_schedule(schedule_id: str):
    """
    Toggle schedule enabled/disabled status.

    If the schedule is disabled, it will be enabled.
    If enabled, it will be disabled.
    When re-enabled, next_run is recalculated.
    """
    try:
        manager = _get_schedule_manager()
        updated = await manager.toggle(schedule_id)

        status = "enabled" if updated["enabled"] else "disabled"
        logger.info(f"Toggled schedule {schedule_id} to {status}")
        return ScheduleResponse.from_db(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to toggle schedule {schedule_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{schedule_id}/mark_complete")
async def mark_schedule_complete(schedule_id: str, request: MarkCompleteRequest = None):
    """
    Mark a schedule run as complete.

    Called by n8n after newsletter generation completes (success or failure).
    Updates last_run timestamp and calculates next_run.

    Args:
        schedule_id: Schedule ID
        request: Optional body with success flag and error message
    """
    try:
        manager = _get_schedule_manager()

        success = True
        error_message = None
        if request:
            success = request.success
            error_message = request.error_message

        await manager.mark_complete(schedule_id, success=success, error_message=error_message)

        status = ScheduleRunStatus.SUCCESS if success else ScheduleRunStatus.FAILED
        logger.info(f"Marked schedule {schedule_id} complete (status: {status})")
        return {"message": f"Schedule {schedule_id} marked complete", "status": status}
    except Exception as e:
        logger.error(f"Failed to mark schedule {schedule_id} complete: {e}")
        raise HTTPException(status_code=500, detail=str(e))
