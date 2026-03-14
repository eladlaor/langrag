"""
Async Batch Orchestration API

Provides endpoints for managing background batch jobs for newsletter generation.
Jobs are queued, processed asynchronously, and their status can be monitored.

Endpoints:
- POST /batch_jobs - Create a new batch job (done via newsletter_gen endpoint with use_batch_api=True)
- GET /batch_jobs/{job_id} - Get job status
- GET /batch_jobs - List all jobs with filtering
- DELETE /batch_jobs/{job_id} - Cancel a pending/processing job

Job Lifecycle:
1. queued - Job created and waiting for worker
2. processing - Worker picked up the job
3. completed - Job finished successfully
4. failed - Job encountered an error
5. cancelled - Job was cancelled by user

Note: Job creation is handled by the newsletter_gen endpoint with use_batch_api=True.
This module only handles status monitoring and cancellation.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from custom_types.api_schemas import (
    BatchJobStatusResponse,
    BatchJobListResponse,
)
from db.batch_jobs import BatchJobManager, BatchJobStatus
from constants import (
    ROUTE_BATCH_JOBS_BY_ID,
    ROUTE_BATCH_JOBS,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================


def _format_datetime(dt) -> str | None:
    """Format datetime to ISO string, handling None values."""
    try:
        if dt is None:
            return None
        if hasattr(dt, "isoformat"):
            return dt.isoformat()
        return str(dt)
    except Exception as e:
        logger.error(f"Unexpected error formatting datetime: {e}, dt={dt}")
        raise RuntimeError(f"Failed to format datetime: {e}") from e


def _job_to_response(job: dict) -> BatchJobStatusResponse:
    """Convert MongoDB job document to response model."""
    try:
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
    except Exception as e:
        logger.error(f"Unexpected error converting job to response: {e}, job_id={job.get('job_id')}")
        raise RuntimeError(f"Failed to convert job to response: {e}") from e


# ============================================================================
# Endpoints
# ============================================================================


@router.get(ROUTE_BATCH_JOBS_BY_ID, response_model=BatchJobStatusResponse)
async def get_batch_job_status(job_id: str):
    """
    Get the status of a batch job.

    Use this endpoint to check the status of a job submitted with use_batch_api=True.

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
async def list_batch_jobs(status: str | None = Query(None, description="Filter by status (queued, processing, completed, failed, cancelled)"), limit: int = Query(50, ge=1, le=200, description="Maximum number of jobs to return"), offset: int = Query(0, ge=0, description="Number of jobs to skip for pagination")):
    """
    List batch jobs with optional status filter.

    Args:
        status: Filter by status (queued, processing, completed, failed, cancelled)
        limit: Maximum number of jobs to return (default: 50)
        offset: Number of jobs to skip for pagination (default: 0)

    Returns:
        BatchJobListResponse with list of jobs
    """
    logger.info(f"Listing batch jobs: status={status}, limit={limit}, offset={offset}")

    # Validate status if provided
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
    Cancel a pending or processing batch job.

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

        # Check if job can be cancelled
        if job.get("status") in (BatchJobStatus.COMPLETED, BatchJobStatus.FAILED, BatchJobStatus.CANCELLED):
            raise HTTPException(status_code=400, detail=f"Cannot cancel job with status: {job.get('status')}")

        # Update status to cancelled
        await batch_manager.update_status(job_id, BatchJobStatus.CANCELLED)

        logger.info(f"Batch job cancelled: {job_id}")
        return {"message": f"Batch job {job_id} cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel batch job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel batch job: {e}")
