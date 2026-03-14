"""
Batch Job Manager

Manages batch API jobs in MongoDB with fail-hard behavior.
Unlike run tracking (fail-soft), batch job operations MUST succeed
because they are user-facing API operations.

Usage (async - LangGraph 1.0+ nodes and FastAPI endpoints):
    from db.batch_jobs import _get_manager

    manager = _get_manager()
    job_id = await manager.create_job(request_dict)
    job = await manager.get_job(job_id)
    jobs = await manager.get_pending_jobs()
"""

import logging
import uuid
from datetime import datetime, UTC
from typing import Any

from db.connection import get_database
from constants import COLLECTION_BATCH_JOBS, BatchJobStatus

logger = logging.getLogger(__name__)


class BatchJobManager:
    """
    Manages batch jobs in MongoDB.

    All methods are fail-hard - errors are raised to the caller.
    This is different from RunTracker which is fail-soft.
    """

    COLLECTION_NAME = COLLECTION_BATCH_JOBS

    def __init__(self):
        self._db = None
        self._collection = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Initialize MongoDB connection. Raises on failure."""
        if self._initialized:
            return

        try:
            self._db = await get_database()
            self._collection = self._db[self.COLLECTION_NAME]
            self._initialized = True
            logger.debug("BatchJobManager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize BatchJobManager: {e}")
            raise RuntimeError(f"MongoDB connection failed for batch jobs: {e}") from e

    @staticmethod
    def _generate_job_id() -> str:
        """Generate a unique job ID (UUID v4)."""
        return str(uuid.uuid4())

    async def create_job(self, request: dict[str, Any], webhook_url: str | None = None, notification_email: str | None = None) -> str:
        """
        Create a new batch job.

        Args:
            request: The original PeriodicNewsletterRequest as dict
            webhook_url: Optional URL to notify on completion
            notification_email: Optional email to notify on completion

        Returns:
            The job_id (UUID)

        Raises:
            RuntimeError: If job creation fails
        """
        await self._ensure_initialized()

        job_id = self._generate_job_id()
        now = datetime.now(UTC)

        job_document = {
            "job_id": job_id,
            "status": BatchJobStatus.QUEUED,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "request": request,
            "openai_batch_id": None,
            "openai_file_id": None,
            "output_dir": None,
            "error_message": None,
            "webhook_url": webhook_url,
            "notification_email": notification_email,
        }

        try:
            result = await self._collection.insert_one(job_document)
            if not result.inserted_id:
                raise RuntimeError("Insert returned no ID")

            logger.info(f"Created batch job: {job_id}")
            return job_id

        except Exception as e:
            logger.error(f"Failed to create batch job: {e}")
            raise RuntimeError(f"Failed to create batch job: {e}") from e

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """
        Get a job by ID.

        Args:
            job_id: The job UUID

        Returns:
            Job document dict or None if not found
        """
        await self._ensure_initialized()

        try:
            job = await self._collection.find_one(
                {"job_id": job_id},
                {"_id": 0},  # Exclude MongoDB _id from response
            )
            return job

        except Exception as e:
            logger.error(f"Failed to get batch job {job_id}: {e}")
            raise RuntimeError(f"Failed to get batch job: {e}") from e

    async def update_status(self, job_id: str, status: str, **kwargs: Any) -> bool:
        """
        Update job status and optional fields.

        Args:
            job_id: The job UUID
            status: New status (use BatchJobStatus constants)
            **kwargs: Additional fields to update (output_dir, error_message, etc.)

        Returns:
            True if job was found and updated

        Raises:
            RuntimeError: If update fails
        """
        await self._ensure_initialized()

        now = datetime.now(UTC)
        update_fields = {
            "status": status,
            "updated_at": now,
        }

        # Set timestamps based on status transition
        if status == BatchJobStatus.PROCESSING:
            update_fields["started_at"] = now
        elif status in (BatchJobStatus.COMPLETED, BatchJobStatus.FAILED, BatchJobStatus.CANCELLED):
            update_fields["completed_at"] = now

        # Add any additional fields
        for key, value in kwargs.items():
            if value is not None:
                update_fields[key] = value

        try:
            result = await self._collection.update_one({"job_id": job_id}, {"$set": update_fields})

            if result.matched_count == 0:
                logger.warning(f"Batch job not found for update: {job_id}")
                return False

            logger.info(f"Updated batch job {job_id} to status: {status}")
            return True

        except Exception as e:
            logger.error(f"Failed to update batch job {job_id}: {e}")
            raise RuntimeError(f"Failed to update batch job: {e}") from e

    async def get_pending_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get jobs that are queued and ready for processing.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job documents, ordered by created_at (oldest first)
        """
        await self._ensure_initialized()

        try:
            cursor = self._collection.find({"status": BatchJobStatus.QUEUED}, {"_id": 0}).sort("created_at", 1).limit(limit)

            jobs = await cursor.to_list(length=limit)
            return jobs

        except Exception as e:
            logger.error(f"Failed to get pending batch jobs: {e}")
            raise RuntimeError(f"Failed to get pending batch jobs: {e}") from e

    async def claim_job(self, job_id: str) -> bool:
        """
        Atomically claim a job for processing (prevents duplicate processing).

        Uses findOneAndUpdate with status check to ensure only one worker
        can claim a job.

        Args:
            job_id: The job UUID to claim

        Returns:
            True if job was successfully claimed, False if already claimed or not found
        """
        await self._ensure_initialized()

        now = datetime.now(UTC)

        try:
            result = await self._collection.find_one_and_update(
                {
                    "job_id": job_id,
                    "status": BatchJobStatus.QUEUED,  # Only claim if still queued
                },
                {"$set": {"status": BatchJobStatus.PROCESSING, "started_at": now, "updated_at": now}},
            )

            if result is None:
                logger.debug(f"Could not claim job {job_id} - already claimed or not found")
                return False

            logger.info(f"Claimed batch job: {job_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to claim batch job {job_id}: {e}")
            raise RuntimeError(f"Failed to claim batch job: {e}") from e

    async def complete_job(self, job_id: str, output_dir: str, openai_batch_id: str | None = None) -> bool:
        """
        Mark a job as completed.

        Args:
            job_id: The job UUID
            output_dir: Path to output directory
            openai_batch_id: Optional OpenAI batch ID for reference

        Returns:
            True if updated successfully
        """
        return await self.update_status(job_id, BatchJobStatus.COMPLETED, output_dir=output_dir, openai_batch_id=openai_batch_id)

    async def fail_job(self, job_id: str, error_message: str, openai_batch_id: str | None = None) -> bool:
        """
        Mark a job as failed.

        Args:
            job_id: The job UUID
            error_message: Description of the error
            openai_batch_id: Optional OpenAI batch ID for debugging

        Returns:
            True if updated successfully
        """
        return await self.update_status(job_id, BatchJobStatus.FAILED, error_message=error_message, openai_batch_id=openai_batch_id)

    async def list_jobs(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """
        List jobs with optional status filter.

        Args:
            status: Filter by status (optional)
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip

        Returns:
            List of job documents
        """
        await self._ensure_initialized()

        try:
            query = {}
            if status:
                query["status"] = status

            cursor = self._collection.find(query, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit)

            jobs = await cursor.to_list(length=limit)
            return jobs

        except Exception as e:
            logger.error(f"Failed to list batch jobs: {e}")
            raise RuntimeError(f"Failed to list batch jobs: {e}") from e


# ============================================================================
# Singleton Instance
# ============================================================================

_manager: BatchJobManager | None = None


def _get_manager() -> BatchJobManager:
    """Get the singleton BatchJobManager instance for use in async nodes."""
    global _manager
    if _manager is None:
        _manager = BatchJobManager()
    return _manager
