"""
Access Requests Repository

CRUD for the `access_requests` collection: self-signup contact-form
submissions from users who are not on the allowlist, persisted for later
admin review. See knowledge/plans/SELF_SIGNUP_GOOGLE_OAUTH.md, section 2.4.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from constants import COLLECTION_ACCESS_REQUESTS, CURRENT_SCHEMA_VERSION_ACCESS_REQUEST, SCHEMA_VERSION_FIELD
from custom_types.db_schemas import AccessRequestStatus
from custom_types.field_keys import AccessRequestKeys as Keys
from db.repositories.base import BaseRepository
from db.repositories.users import normalize_email

logger = logging.getLogger(__name__)


class AccessRequestsRepository(BaseRepository):
    """Repository for self-signup access requests."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_ACCESS_REQUESTS)

    async def create_request(
        self,
        email: str,
        *,
        name: str | None = None,
        message: str | None = None,
        requested_provider: str | None = None,
    ) -> str:
        """Persist a new access request. Returns the new request_id (uuid4).

        Email is normalized at the repository boundary, mirroring the users
        repo, so requests are stored under a canonical identity.
        """
        request_id = str(uuid.uuid4())
        email = normalize_email(email)
        document = {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_ACCESS_REQUEST,
            Keys.REQUEST_ID: request_id,
            Keys.EMAIL: email,
            Keys.NAME: name,
            Keys.MESSAGE: message,
            Keys.REQUESTED_PROVIDER: requested_provider,
            Keys.STATUS: str(AccessRequestStatus.PENDING),
            Keys.CREATED_AT: datetime.now(UTC),
            Keys.REVIEWED_AT: None,
            Keys.REVIEWED_BY: None,
        }
        try:
            await self.create(document)
        except Exception as e:
            logger.error(
                "create_request failed",
                extra={"event": "access_request_create_failed", "function": "create_request", "email": email, "error": str(e)},
            )
            raise
        logger.info(
            "Created access request",
            extra={"event": "access_request_created", "function": "create_request", "request_id": request_id},
        )
        return request_id

    async def list_requests(self, status: AccessRequestStatus | None = None, limit: int = 200, skip: int = 0) -> list[dict[str, Any]]:
        """List access requests newest-first, optionally filtered by status."""
        try:
            query: dict[str, Any] = {}
            if status is not None:
                query[Keys.STATUS] = str(status)
            return await self.find_many(
                query,
                sort=[(Keys.CREATED_AT, -1)],
                limit=limit,
                skip=skip,
            )
        except Exception as e:
            logger.error(
                "list_requests failed",
                extra={"event": "access_request_list_failed", "function": "list_requests", "error": str(e)},
            )
            raise
