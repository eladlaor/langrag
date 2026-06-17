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
from pymongo import WriteConcern
from pymongo.errors import DuplicateKeyError

from constants import COLLECTION_USERS, CURRENT_SCHEMA_VERSION_USER, SCHEMA_VERSION_FIELD, WRITE_CONCERN_MAJORITY
from custom_types.db_schemas import AuthProvider, UserDailyUsage, UserQuotas, UserRole
from custom_types.field_keys import UserKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    """Canonicalize an email for storage and lookup.

    Email is a case-insensitive identity for our purposes, so we lowercase and
    strip it at the repository boundary. Without this, `Alice@x.com` and
    `alice@x.com` would be two distinct accounts under the case-sensitive unique
    index, which both duplicates identities and lets a disabled account be
    reached under a different casing. Normalizing in the single chokepoint that
    every caller (login, admin-create, bootstrap) passes through closes that.
    """
    return email.strip().lower()


class UsersRepository(BaseRepository):
    """Repository for community-admin user records."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        # Durable record: majority write concern so an account (and its
        # disabled/role state) survives a primary failover on multi-node Atlas.
        super().__init__(db, COLLECTION_USERS, write_concern=WriteConcern(w=WRITE_CONCERN_MAJORITY))

    async def create_user(
        self,
        email: str,
        communities: list[str],
        role: UserRole = UserRole.ADMIN,
        preferences: dict[str, Any] | None = None,
        quotas: UserQuotas | None = None,
        password_hash: str | None = None,
    ) -> str:
        """Create a new user. Returns the new user_id (uuid4 string).

        Raises DuplicateKeyError if the email already exists.
        """
        user_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        email = normalize_email(email)
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_USER,
            Keys.USER_ID: user_id,
            Keys.EMAIL: email,
            Keys.ROLE: str(role),
            Keys.PASSWORD_HASH: password_hash,
            Keys.SESSION_EPOCH: 0,
            Keys.DISABLED: False,
            Keys.AUTH_PROVIDER: str(AuthProvider.PASSWORD),
            Keys.GOOGLE_SUB: None,
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

    async def create_self_signup_user(
        self,
        email: str,
        *,
        auth_provider: AuthProvider,
        password_hash: str | None = None,
        google_sub: str | None = None,
    ) -> str:
        """Create a self-signed-up user. Returns the new user_id (uuid4 string).

        VIEWER-only invariant: this method HARDCODES role=VIEWER and
        communities=[] and accepts no role/communities argument, so the
        self-signup path can never structurally mint an ADMIN. Admin
        provisioning goes through create_user instead.

        Raises DuplicateKeyError on a duplicate email or a duplicate google_sub
        (the latter validated by the sparse-unique index on google_sub).
        """
        user_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        email = normalize_email(email)
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_USER,
            Keys.USER_ID: user_id,
            Keys.EMAIL: email,
            Keys.ROLE: str(UserRole.VIEWER),
            Keys.PASSWORD_HASH: password_hash,
            Keys.SESSION_EPOCH: 0,
            Keys.DISABLED: False,
            Keys.AUTH_PROVIDER: str(auth_provider),
            Keys.GOOGLE_SUB: google_sub,
            Keys.COMMUNITIES: [],
            Keys.PREFERENCES: {},
            Keys.QUOTAS: UserQuotas().model_dump(),
            Keys.DAILY_USAGE: None,
            Keys.CREATED_AT: now,
            Keys.LAST_SEEN_AT: None,
        }
        try:
            await self.create(document)
        except DuplicateKeyError:
            logger.warning(
                "create_self_signup_user: duplicate key rejected",
                extra={"event": "self_signup_duplicate", "function": "create_self_signup_user", "email": email, "has_google_sub": google_sub is not None},
            )
            raise
        logger.info(
            "Created self-signup user",
            extra={"event": "self_signup_created", "function": "create_self_signup_user", "user_id": user_id, "auth_provider": str(auth_provider)},
        )
        return user_id

    async def find_by_google_sub(self, google_sub: str) -> dict[str, Any] | None:
        """Fetch a user by their Google OIDC subject identifier."""
        try:
            return await self.find_one({Keys.GOOGLE_SUB: google_sub})
        except Exception as e:
            logger.error(
                "find_by_google_sub failed",
                extra={"event": "find_by_google_sub_failed", "function": "find_by_google_sub", "error": str(e)},
            )
            raise

    async def link_google_identity(self, user_id: str, google_sub: str) -> bool:
        """Link a Google identity to an existing (password) account.

        Sets google_sub and flips auth_provider to PASSWORD_AND_GOOGLE. Raises
        DuplicateKeyError if that google_sub is already bound to another row
        (sub-hijack defense, enforced by the sparse-unique index).
        """
        try:
            return await self.update_one(
                {Keys.USER_ID: user_id},
                {"$set": {Keys.GOOGLE_SUB: google_sub, Keys.AUTH_PROVIDER: str(AuthProvider.PASSWORD_AND_GOOGLE)}},
            )
        except Exception as e:
            logger.error(
                "link_google_identity failed",
                extra={"event": "link_google_identity_failed", "function": "link_google_identity", "user_id": user_id, "error": str(e)},
            )
            raise

    async def set_password(self, user_id: str, password_hash: str) -> bool:
        """Set a new password hash and bump the session epoch.

        Bumping the epoch revokes every live session for the user, so a password
        reset forces re-login everywhere.
        """
        try:
            return await self.update_one(
                {Keys.USER_ID: user_id},
                {"$set": {Keys.PASSWORD_HASH: password_hash}, "$inc": {Keys.SESSION_EPOCH: 1}},
            )
        except Exception as e:
            logger.error(
                "set_password failed",
                extra={"event": "set_password_failed", "function": "set_password", "user_id": user_id, "error": str(e)},
            )
            raise

    async def bump_session_epoch(self, user_id: str) -> int:
        """Increment the user's session epoch and return the new value.

        Used to revoke all live sessions (e.g., on disable or forced logout).
        """
        try:
            updated = await self.collection.find_one_and_update(
                {Keys.USER_ID: user_id},
                {"$inc": {Keys.SESSION_EPOCH: 1}},
                return_document=True,
            )
            if updated is None:
                raise ValueError(f"bump_session_epoch: user not found: user_id={user_id}")
            return int(updated[Keys.SESSION_EPOCH])
        except Exception as e:
            logger.error(
                "bump_session_epoch failed",
                extra={"event": "bump_session_epoch_failed", "function": "bump_session_epoch", "user_id": user_id, "error": str(e)},
            )
            raise

    async def set_disabled(self, user_id: str, disabled: bool) -> bool:
        """Enable or disable an account. Disabling also revokes live sessions."""
        try:
            update: dict[str, Any] = {"$set": {Keys.DISABLED: disabled}}
            if disabled:
                update["$inc"] = {Keys.SESSION_EPOCH: 1}
            return await self.update_one({Keys.USER_ID: user_id}, update)
        except Exception as e:
            logger.error(
                "set_disabled failed",
                extra={"event": "set_disabled_failed", "function": "set_disabled", "user_id": user_id, "disabled": disabled, "error": str(e)},
            )
            raise

    async def list_users(self, limit: int = 200, skip: int = 0) -> list[dict[str, Any]]:
        """List users newest-first for admin browsing."""
        try:
            return await self.find_many(
                {},
                sort=[(Keys.CREATED_AT, -1)],
                limit=limit,
                skip=skip,
            )
        except Exception as e:
            logger.error(
                "list_users failed",
                extra={"event": "list_users_failed", "function": "list_users", "error": str(e)},
            )
            raise

    async def count_users(self) -> int:
        """Return the total number of user documents."""
        try:
            return await self.count({})
        except Exception as e:
            logger.error(
                "count_users failed",
                extra={"event": "count_users_failed", "function": "count_users", "error": str(e)},
            )
            raise

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user document. Returns True if a document was removed."""
        try:
            return await self.delete_one({Keys.USER_ID: user_id})
        except Exception as e:
            logger.error(
                "delete_user failed",
                extra={"event": "delete_user_failed", "function": "delete_user", "user_id": user_id, "error": str(e)},
            )
            raise

    async def find_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        """Fetch a user by user_id."""
        return await self.find_one({Keys.USER_ID: user_id})

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        """Fetch a user by email (normalized: case-insensitive, trimmed)."""
        return await self.find_one({Keys.EMAIL: normalize_email(email)})

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
