"""
Scheduled Newsletter MongoDB Operations

Manages scheduled newsletter configurations stored in MongoDB.
Supports CRUD operations for newsletter generation schedules.

Usage (from async context):
    from db.scheduled_newsletters import _get_schedule_manager

    manager = _get_schedule_manager()
    schedule_id = await manager.create_schedule(schedule_data)
    due_schedules = await manager.get_due_schedules()
"""

import logging
from datetime import datetime, timedelta, UTC

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from constants import (
    COLLECTION_SCHEDULED_NEWSLETTERS,
    SCHEDULE_FIELD_INTERVAL_DAYS,
    SCHEDULE_FIELD_RUN_TIME,
    SCHEDULE_DEFAULT_RUN_TIME,
    ScheduleRunStatus,
)
from custom_types.field_keys import DbFieldKeys

logger = logging.getLogger(__name__)

COLLECTION_NAME = COLLECTION_SCHEDULED_NEWSLETTERS


class ScheduledNewsletterManager:
    """
    Manages scheduled newsletter CRUD operations.

    All methods are async and use Motor for non-blocking MongoDB operations.
    Follows fail-fast pattern - raises exceptions on errors.
    """

    def __init__(self):
        self._db: AsyncIOMotorDatabase | None = None
        self._collection: AsyncIOMotorCollection | None = None
        self._initialized = False

    async def _ensure_initialized(self) -> bool:
        """Lazily initialize MongoDB connection."""
        if self._initialized:
            return True

        try:
            from db.connection import get_database

            self._db = await get_database()
            self._collection = self._db[COLLECTION_NAME]
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ScheduledNewsletterManager: {e}")
            raise RuntimeError(f"MongoDB connection failed: {e}") from e

    def _calculate_next_run(self, interval_days: int, run_time: str) -> datetime:
        """
        Calculate next run datetime.

        Args:
            interval_days: Days between runs
            run_time: Time of day to run (HH:MM format)

        Returns:
            datetime of next scheduled run
        """
        try:
            hour, minute = map(int, run_time.split(":"))
        except (ValueError, AttributeError):
            logger.warning(f"Invalid run_time format: {run_time}, defaulting to 08:00")
            hour, minute = 8, 0

        # Start from today at the specified time
        next_run = datetime.now(UTC).replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If the time has already passed today, start from tomorrow
        if next_run <= datetime.now(UTC):
            next_run += timedelta(days=1)

        return next_run

    async def create_schedule(self, schedule: dict) -> str:
        """
        Create a new scheduled newsletter.

        Args:
            schedule: Schedule configuration dict with:
                - name: Schedule name
                - interval_days: Days between runs
                - run_time: Time to run (HH:MM)
                - data_source_name: Data source
                - whatsapp_chat_names_to_include: Chat names list
                - email_recipients: Email recipients list
                - desired_language_for_summary: Target language
                - summary_format: Newsletter format
                - consolidate_chats: Whether to consolidate

        Returns:
            str: Created schedule ID

        Raises:
            RuntimeError: If MongoDB operation fails
        """
        await self._ensure_initialized()

        try:
            # Add metadata
            schedule[DbFieldKeys.CREATED_AT] = datetime.now(UTC)
            schedule[DbFieldKeys.UPDATED_AT] = datetime.now(UTC)
            schedule[DbFieldKeys.ENABLED] = schedule.get(DbFieldKeys.ENABLED, True)
            schedule[DbFieldKeys.LAST_RUN] = None
            schedule[DbFieldKeys.LAST_RUN_STATUS] = None
            schedule[DbFieldKeys.LAST_RUN_ERROR] = None
            schedule[DbFieldKeys.NEXT_RUN] = self._calculate_next_run(schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7), schedule.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME))
            schedule[DbFieldKeys.RUN_COUNT] = 0

            result = await self._collection.insert_one(schedule)
            schedule_id = str(result.inserted_id)
            logger.info(f"Created schedule: {schedule_id} (name: {schedule.get('name')})")
            return schedule_id
        except Exception as e:
            logger.error(f"Failed to create schedule: {e}")
            raise RuntimeError(f"Failed to create schedule: {e}") from e

    async def get_due_schedules(self) -> list[dict]:
        """
        Get all schedules that are due to run.

        Returns schedules where:
        - enabled = True
        - next_run <= now

        Returns:
            List of schedule documents ready to execute
        """
        await self._ensure_initialized()

        try:
            now = datetime.now(UTC)
            cursor = self._collection.find({DbFieldKeys.ENABLED: True, DbFieldKeys.NEXT_RUN: {"$lte": now}})
            schedules = await cursor.to_list(length=100)

            # Convert ObjectId to string for JSON serialization
            for schedule in schedules:
                schedule["_id"] = str(schedule["_id"])

            logger.info(f"Found {len(schedules)} due schedules")
            return schedules
        except Exception as e:
            logger.error(f"Failed to get due schedules: {e}")
            raise RuntimeError(f"Failed to get due schedules: {e}") from e

    async def mark_complete(self, schedule_id: str, success: bool = True, error_message: str | None = None) -> None:
        """
        Mark schedule run as completed and calculate next run.

        Args:
            schedule_id: Schedule ID
            success: Whether the run succeeded
            error_message: Error message if failed
        """
        await self._ensure_initialized()

        try:
            schedule = await self._collection.find_one({"_id": ObjectId(schedule_id)})
            if not schedule:
                logger.warning(f"Schedule not found: {schedule_id}")
                return

            next_run = self._calculate_next_run(schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7), schedule.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME))

            # Add interval_days to next_run (since _calculate_next_run starts from today)
            next_run = datetime.now(UTC).replace(hour=int(schedule.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME).split(":")[0]), minute=int(schedule.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME).split(":")[1]), second=0, microsecond=0) + timedelta(days=schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7))

            update_doc = {"$set": {DbFieldKeys.LAST_RUN: datetime.now(UTC), DbFieldKeys.LAST_RUN_STATUS: ScheduleRunStatus.SUCCESS if success else ScheduleRunStatus.FAILED, DbFieldKeys.LAST_RUN_ERROR: error_message, DbFieldKeys.NEXT_RUN: next_run, DbFieldKeys.UPDATED_AT: datetime.now(UTC)}, "$inc": {DbFieldKeys.RUN_COUNT: 1}}

            await self._collection.update_one({"_id": ObjectId(schedule_id)}, update_doc)
            logger.info(f"Marked schedule {schedule_id} complete (success={success})")
        except Exception as e:
            logger.error(f"Failed to mark schedule complete: {e}")
            raise RuntimeError(f"Failed to mark schedule complete: {e}") from e

    async def list_all(self) -> list[dict]:
        """
        List all schedules.

        Returns:
            List of all schedule documents
        """
        await self._ensure_initialized()

        try:
            cursor = self._collection.find({}).sort("created_at", -1)
            schedules = await cursor.to_list(length=1000)

            # Convert ObjectId to string for JSON serialization
            for schedule in schedules:
                schedule["_id"] = str(schedule["_id"])

            return schedules
        except Exception as e:
            logger.error(f"Failed to list schedules: {e}")
            raise RuntimeError(f"Failed to list schedules: {e}") from e

    async def get_by_id(self, schedule_id: str) -> dict | None:
        """
        Get a schedule by ID.

        Args:
            schedule_id: Schedule ID

        Returns:
            Schedule document or None if not found
        """
        await self._ensure_initialized()

        try:
            schedule = await self._collection.find_one({"_id": ObjectId(schedule_id)})
            if schedule:
                schedule["_id"] = str(schedule["_id"])
            return schedule
        except Exception as e:
            logger.error(f"Failed to get schedule {schedule_id}: {e}")
            raise RuntimeError(f"Failed to get schedule: {e}") from e

    async def delete(self, schedule_id: str) -> bool:
        """
        Delete a schedule.

        Args:
            schedule_id: Schedule ID

        Returns:
            True if deleted, False if not found
        """
        await self._ensure_initialized()

        try:
            result = await self._collection.delete_one({"_id": ObjectId(schedule_id)})
            deleted = result.deleted_count > 0
            if deleted:
                logger.info(f"Deleted schedule: {schedule_id}")
            else:
                logger.warning(f"Schedule not found for deletion: {schedule_id}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete schedule {schedule_id}: {e}")
            raise RuntimeError(f"Failed to delete schedule: {e}") from e

    async def toggle(self, schedule_id: str) -> dict:
        """
        Toggle schedule enabled/disabled status.

        Args:
            schedule_id: Schedule ID

        Returns:
            Updated schedule document

        Raises:
            ValueError: If schedule not found
        """
        await self._ensure_initialized()

        try:
            schedule = await self._collection.find_one({"_id": ObjectId(schedule_id)})
            if not schedule:
                raise ValueError(f"Schedule not found: {schedule_id}")

            new_enabled = not schedule.get(DbFieldKeys.ENABLED, True)

            # If re-enabling, recalculate next_run
            update_doc = {"$set": {DbFieldKeys.ENABLED: new_enabled, DbFieldKeys.UPDATED_AT: datetime.now(UTC)}}

            if new_enabled:
                update_doc["$set"][DbFieldKeys.NEXT_RUN] = self._calculate_next_run(schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7), schedule.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME))

            await self._collection.update_one({"_id": ObjectId(schedule_id)}, update_doc)

            # Return updated schedule
            updated = await self.get_by_id(schedule_id)
            logger.info(f"Toggled schedule {schedule_id} to enabled={new_enabled}")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to toggle schedule {schedule_id}: {e}")
            raise RuntimeError(f"Failed to toggle schedule: {e}") from e

    async def update(self, schedule_id: str, updates: dict) -> dict:
        """
        Update a schedule.

        Args:
            schedule_id: Schedule ID
            updates: Fields to update

        Returns:
            Updated schedule document

        Raises:
            ValueError: If schedule not found
        """
        await self._ensure_initialized()

        try:
            schedule = await self._collection.find_one({"_id": ObjectId(schedule_id)})
            if not schedule:
                raise ValueError(f"Schedule not found: {schedule_id}")

            # Don't allow updating internal fields
            protected_fields = ["_id", DbFieldKeys.CREATED_AT, DbFieldKeys.RUN_COUNT, DbFieldKeys.LAST_RUN, DbFieldKeys.LAST_RUN_STATUS]
            for field in protected_fields:
                updates.pop(field, None)

            updates[DbFieldKeys.UPDATED_AT] = datetime.now(UTC)

            # Recalculate next_run if interval or run_time changed
            if SCHEDULE_FIELD_INTERVAL_DAYS in updates or SCHEDULE_FIELD_RUN_TIME in updates:
                updates[DbFieldKeys.NEXT_RUN] = self._calculate_next_run(updates.get(SCHEDULE_FIELD_INTERVAL_DAYS, schedule.get(SCHEDULE_FIELD_INTERVAL_DAYS, 7)), updates.get(SCHEDULE_FIELD_RUN_TIME, schedule.get(SCHEDULE_FIELD_RUN_TIME, SCHEDULE_DEFAULT_RUN_TIME)))

            await self._collection.update_one({"_id": ObjectId(schedule_id)}, {"$set": updates})

            updated = await self.get_by_id(schedule_id)
            logger.info(f"Updated schedule: {schedule_id}")
            return updated
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to update schedule {schedule_id}: {e}")
            raise RuntimeError(f"Failed to update schedule: {e}") from e


# Singleton instance
_manager: ScheduledNewsletterManager | None = None


def _get_schedule_manager() -> ScheduledNewsletterManager:
    """Get the singleton ScheduledNewsletterManager instance."""
    global _manager
    if _manager is None:
        _manager = ScheduledNewsletterManager()
    return _manager
