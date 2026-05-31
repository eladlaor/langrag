"""
Users Repository

CRUD for the `users` collection used by the agentic chatbot layer.
See knowledge/plans/AGENTIC_CHATBOT_LAYER.md, section A.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from constants import COLLECTION_USERS, CURRENT_SCHEMA_VERSION_USER, SCHEMA_VERSION_FIELD
from custom_types.db_schemas import UserDailyUsage, UserQuotas, UserRole
from custom_types.field_keys import UserKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class UsersRepository(BaseRepository):
    """Repository for community-admin user records."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_USERS)

    async def create_user(
        self,
        email: str,
        communities: list[str],
        role: UserRole = UserRole.ADMIN,
        preferences: dict[str, Any] | None = None,
        quotas: UserQuotas | None = None,
    ) -> str:
        """Create a new user. Returns the new user_id (uuid4 string).

        Raises DuplicateKeyError if the email already exists.
        """
        user_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_USER,
            Keys.USER_ID: user_id,
            Keys.EMAIL: email,
            Keys.ROLE: str(role),
            Keys.COMMUNITIES: list(communities),
            Keys.PREFERENCES: preferences or {},
            Keys.QUOTAS: (quotas or UserQuotas()).model_dump(),
            Keys.DAILY_USAGE: None,
            Keys.CREATED_AT: now,
            Keys.LAST_SEEN_AT: None,
        }
        try:
            await self.create(document)
        except DuplicateKeyError:
            logger.warning(f"create_user: duplicate email rejected: email={email}")
            raise
        logger.info(f"Created user: user_id={user_id} email={email} communities={communities}")
        return user_id

    async def find_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        """Fetch a user by user_id."""
        return await self.find_one({Keys.USER_ID: user_id})

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        """Fetch a user by email."""
        return await self.find_one({Keys.EMAIL: email})

    async def touch_last_seen(self, user_id: str) -> None:
        """Best-effort update of last_seen_at."""
        try:
            await self.update_one(
                {Keys.USER_ID: user_id},
                {"$set": {Keys.LAST_SEEN_AT: datetime.now(UTC)}},
            )
        except Exception as e:
            logger.warning(f"touch_last_seen failed: user_id={user_id} error={e}")

    async def set_daily_usage(self, user_id: str, usage: UserDailyUsage) -> bool:
        """Overwrite the rolling daily usage counters on the user document."""
        return await self.update_one(
            {Keys.USER_ID: user_id},
            {"$set": {Keys.DAILY_USAGE: usage.model_dump()}},
        )
