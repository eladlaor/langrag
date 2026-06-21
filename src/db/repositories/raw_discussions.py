"""
Raw Discussions Repository

Persists the pre-rank / pre-merge per-chat discussions (output of
`separate_discussions`) to the `raw_discussions` collection, each stamped with
the community (`data_source_name`) and exact group (`chat_name`). Distinct from
DiscussionsRepository, which stores the *ranked* discussions.

Writes are idempotent per (run_id, chat_name, local_id) so re-running a run does
not duplicate rows.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

from constants import COLLECTION_RAW_DISCUSSIONS
from custom_types.db_schemas import RawDiscussionDocument
from custom_types.field_keys import DbFieldKeys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)

# Local field-key constants for this collection (no inlined literals).
_RAW_DISCUSSION_ID = "raw_discussion_id"


class RawDiscussionsRepository(BaseRepository):
    """Repository for raw (pre-merge) per-chat discussions."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_RAW_DISCUSSIONS)

    async def store_raw_discussions(
        self,
        run_id: str,
        chat_name: str,
        data_source_name: str | None,
        discussions: list[dict[str, Any]],
    ) -> int:
        """Upsert a chat's raw discussions.

        Args:
            run_id: Owning pipeline run id.
            chat_name: Exact source group name.
            data_source_name: Community key (e.g. 'langtalks').
            discussions: Raw discussion dicts from separate_discussions. Each is
                expected to carry an id/local id, title, nutshell, message count,
                and optionally message ids + first-message timestamp.

        Returns:
            Number of raw discussions upserted.
        """
        if not discussions:
            return 0

        now = datetime.now(UTC)
        ops: list[UpdateOne] = []
        for disc in discussions:
            local_id = str(disc.get("id") or disc.get("local_id") or "")
            if not local_id:
                logger.warning(
                    "Raw discussion without an id for run=%s chat=%s; skipping one row.",
                    run_id, chat_name,
                )
                continue

            raw_discussion_id = f"{run_id}_{chat_name}_{local_id}"
            message_ids = disc.get("message_ids") or []
            message_count = disc.get("num_messages")
            if message_count is None:
                message_count = len(message_ids)

            # Build through the Pydantic model so the schema is the source of truth.
            doc = RawDiscussionDocument(
                raw_discussion_id=raw_discussion_id,
                run_id=run_id,
                chat_name=chat_name,
                data_source_name=data_source_name,
                local_id=local_id,
                title=disc.get("title"),
                nutshell=disc.get("nutshell"),
                message_ids=message_ids,
                message_count=message_count,
                first_message_timestamp=disc.get("first_message_in_discussion_timestamp")
                or disc.get("first_message_timestamp"),
                created_at=now,
            ).model_dump()

            ops.append(UpdateOne({_RAW_DISCUSSION_ID: raw_discussion_id}, {"$set": doc}, upsert=True))

        if not ops:
            return 0

        try:
            result = await self.collection.bulk_write(ops, ordered=False)
            upserted = (result.upserted_count or 0) + (result.modified_count or 0)
            logger.info(
                "Stored %d raw discussions for run=%s chat=%s community=%s",
                len(ops), run_id, chat_name, data_source_name,
            )
            return upserted
        except Exception as e:
            logger.error(
                "Failed to store raw discussions for run=%s chat=%s: %s",
                run_id, chat_name, e,
                extra={DbFieldKeys.RUN_ID: run_id, DbFieldKeys.CHAT_NAME: chat_name},
            )
            raise
