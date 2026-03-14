"""
Runs Repository

Manages pipeline run records for tracking newsletter generation executions.
"""

import logging
from datetime import datetime, UTC
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_RUNS, RunStatus

logger = logging.getLogger(__name__)


class RunsRepository(BaseRepository):
    """
    Repository for pipeline run tracking.

    Tracks:
    - Run metadata (dates, data source, chat names)
    - Status transitions (pending -> running -> completed/failed)
    - Timing information
    - Output paths
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_RUNS)

    async def create_run(
        self,
        run_id: str,
        data_source_name: str,
        chat_names: list[str],
        start_date: str,
        end_date: str,
        config: dict[str, Any] = None,
    ) -> str:
        """
        Create a new pipeline run record.

        Args:
            run_id: Unique identifier for the run
            data_source_name: Data source (e.g., "langtalks", "mcp_israel")
            chat_names: List of chat names included in the run
            start_date: Start date for message extraction (YYYY-MM-DD)
            end_date: End date for message extraction (YYYY-MM-DD)
            config: Additional configuration options

        Returns:
            Inserted document ID
        """
        document = {
            "run_id": run_id,
            "data_source_name": data_source_name,
            "chat_names": chat_names,
            "start_date": start_date,
            "end_date": end_date,
            "config": config or {},
            "status": RunStatus.PENDING,
            "created_at": datetime.now(UTC),
            "started_at": None,
            "completed_at": None,
            "error": None,
            "output_path": None,
            "stages": {},
        }
        return await self.create(document)

    async def start_run(self, run_id: str) -> bool:
        """Mark run as started."""
        return await self.update_one(
            {"run_id": run_id},
            {"$set": {"status": RunStatus.RUNNING, "started_at": datetime.now(UTC)}},
        )

    async def complete_run(self, run_id: str, output_path: str = None) -> bool:
        """Mark run as completed."""
        return await self.update_one(
            {"run_id": run_id},
            {
                "$set": {
                    "status": RunStatus.COMPLETED,
                    "completed_at": datetime.now(UTC),
                    "output_path": output_path,
                }
            },
        )

    async def fail_run(self, run_id: str, error: str) -> bool:
        """Mark run as failed."""
        return await self.update_one(
            {"run_id": run_id},
            {
                "$set": {
                    "status": RunStatus.FAILED,
                    "completed_at": datetime.now(UTC),
                    "error": error,
                }
            },
        )

    async def update_stage(
        self,
        run_id: str,
        stage_name: str,
        status: str,
        details: dict[str, Any] = None,
    ) -> bool:
        """Update progress for a specific stage."""
        return await self.update_one(
            {"run_id": run_id},
            {
                "$set": {
                    f"stages.{stage_name}": {
                        "status": status,
                        "timestamp": datetime.now(UTC),
                        "details": details or {},
                    }
                }
            },
        )

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a run by its ID."""
        return await self.find_by_id("run_id", run_id)

    async def get_recent_runs(
        self,
        limit: int = 10,
        data_source_name: str = None,
        status: str = None,
    ) -> list[dict[str, Any]]:
        """Get recent runs, optionally filtered."""
        query = {}
        if data_source_name:
            query["data_source_name"] = data_source_name
        if status:
            query["status"] = status

        return await self.find_many(
            query,
            sort=[("created_at", -1)],
            limit=limit,
        )
