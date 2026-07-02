"""
Podcasts Catalog Repository

CRUD for the `podcasts` catalog collection: one row per podcast (tenant) on the
multi-podcast platform. `list_podcasts()` reads the active rows; the seed slug is
`langtalks`. Adding a new show is an insert here plus its ingest — no schema
migration and no client change (the public MCP tools are podcast-generic).
"""

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from constants import (
    COLLECTION_PODCASTS,
    PODCAST_DESCRIPTION_LANGTALKS,
    PODCAST_SLUG_LANGTALKS,
    PODCAST_TITLE_LANGTALKS,
)
from custom_types.field_keys import PodcastCatalogKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class PodcastsRepository(BaseRepository):
    """Repository for the podcast catalog."""

    def __init__(self, db: AsyncDatabase) -> None:
        super().__init__(db, COLLECTION_PODCASTS)

    async def upsert_podcast(
        self,
        slug: str,
        title: str,
        description: str,
        active: bool = True,
    ) -> None:
        """Insert or update a catalog row by slug.

        Idempotent and deterministic: a repeat call with the same slug updates the
        display fields but never duplicates the row and never resets created_at
        (created_at is only set on first insert via $setOnInsert).
        """
        try:
            await self.update_one(
                {Keys.SLUG: slug},
                {
                    "$set": {
                        Keys.TITLE: title,
                        Keys.DESCRIPTION: description,
                        Keys.ACTIVE: active,
                    },
                    "$setOnInsert": {
                        Keys.SLUG: slug,
                        Keys.CREATED_AT: datetime.now(UTC),
                    },
                },
                upsert=True,
            )
            logger.info(f"Upserted podcast catalog row: slug={slug}, active={active}")
        except Exception as e:
            logger.error(f"Failed to upsert podcast catalog row slug={slug}: {e}")
            raise

    async def seed_langtalks(self) -> None:
        """Seed the LangTalks catalog row (podcast #1). Idempotent."""
        await self.upsert_podcast(
            slug=PODCAST_SLUG_LANGTALKS,
            title=PODCAST_TITLE_LANGTALKS,
            description=PODCAST_DESCRIPTION_LANGTALKS,
            active=True,
        )

    async def list_active(self) -> list[dict[str, Any]]:
        """Return active catalog rows (slug/title/description/created_at), no _id."""
        try:
            rows = await self.find_many(
                {Keys.ACTIVE: True},
                sort=[(Keys.SLUG, 1)],
                projection={"_id": 0},
            )
            return rows
        except Exception as e:
            logger.error(f"Failed to list active podcasts: {e}")
            raise

    async def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        """Return a single catalog row by slug, or None."""
        try:
            return await self.find_one({Keys.SLUG: slug})
        except Exception as e:
            logger.error(f"Failed to get podcast by slug={slug}: {e}")
            raise
