"""
Images Repository

MongoDB repository for storing and querying image metadata
extracted from WhatsApp messages.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import COLLECTION_IMAGES
from custom_types.common import ImageMetadata
from custom_types.field_keys import DbFieldKeys, ImageKeys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ImagesRepository(BaseRepository):
    """Repository for image metadata persistence and queries."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_IMAGES)

    async def store_image(self, image: ImageMetadata, run_id: str) -> str:
        """
        Store image metadata. Uses mxc_url as dedup key (upsert).

        Args:
            image: ImageMetadata to store
            run_id: Pipeline run ID

        Returns:
            image_id of the stored document
        """
        try:
            doc = {
                "_id": image.image_id,
                DbFieldKeys.RUN_ID: run_id,
                ImageKeys.MXC_URL: image.mxc_url,
                ImageKeys.STORAGE_PATH: image.storage_path,
                ImageKeys.MIMETYPE: image.mimetype,
                ImageKeys.WIDTH: image.width,
                ImageKeys.HEIGHT: image.height,
                ImageKeys.SIZE_BYTES: image.size_bytes,
                ImageKeys.FILENAME: image.filename,
                ImageKeys.SENDER_ID: image.sender_id,
                ImageKeys.TIMESTAMP: image.timestamp,
                ImageKeys.MESSAGE_ID: image.message_id,
                ImageKeys.CHAT_NAME: image.chat_name,
                ImageKeys.DATA_SOURCE_NAME: image.data_source_name,
                ImageKeys.DESCRIPTION: image.description,
                ImageKeys.DESCRIPTION_MODEL: image.description_model,
                ImageKeys.DISCUSSION_ID: image.discussion_id,
                DbFieldKeys.CREATED_AT: datetime.now(timezone.utc).isoformat(),
            }
            await self.collection.update_one(
                {ImageKeys.MXC_URL: image.mxc_url},
                {"$set": doc},
                upsert=True,
            )
            return image.image_id
        except Exception as e:
            logger.error(f"Failed to store image {image.image_id}: {e}")
            raise

    async def store_images_batch(self, images: list[ImageMetadata], run_id: str) -> int:
        """
        Store multiple image metadata documents.

        Returns:
            Number of images stored
        """
        stored = 0
        for image in images:
            try:
                await self.store_image(image, run_id)
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to store image {image.image_id}: {e}")
        return stored

    async def get_images_by_chat(
        self,
        chat_name: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get images for a specific chat, optionally filtered by date range."""
        query: dict[str, Any] = {ImageKeys.CHAT_NAME: chat_name}
        if start_date or end_date:
            ts_filter: dict[str, Any] = {}
            if start_date:
                ts_filter["$gte"] = _date_to_timestamp_ms(start_date)
            if end_date:
                ts_filter["$lte"] = _date_to_timestamp_ms(end_date, end_of_day=True)
            query[ImageKeys.TIMESTAMP] = ts_filter
        return await self.find_many(query, sort=[(ImageKeys.TIMESTAMP, -1)])

    async def get_images_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Get all images from a specific pipeline run."""
        return await self.find_many({DbFieldKeys.RUN_ID: run_id}, sort=[(ImageKeys.TIMESTAMP, -1)])

    async def get_images_by_discussion(self, discussion_id: str) -> list[dict[str, Any]]:
        """Get images associated with a specific discussion."""
        return await self.find_many(
            {ImageKeys.DISCUSSION_ID: discussion_id},
            sort=[(ImageKeys.TIMESTAMP, -1)],
        )

    async def get_all_images(
        self,
        data_source_name: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all images for a data source, optionally filtered by date range."""
        query: dict[str, Any] = {ImageKeys.DATA_SOURCE_NAME: data_source_name}
        if start_date or end_date:
            ts_filter: dict[str, Any] = {}
            if start_date:
                ts_filter["$gte"] = _date_to_timestamp_ms(start_date)
            if end_date:
                ts_filter["$lte"] = _date_to_timestamp_ms(end_date, end_of_day=True)
            query[ImageKeys.TIMESTAMP] = ts_filter
        return await self.find_many(query, sort=[(ImageKeys.TIMESTAMP, -1)])

    async def update_description(self, image_id: str, description: str, model: str) -> None:
        """Update the vision description for an image."""
        await self.update_one(
            {"_id": image_id},
            {"$set": {ImageKeys.DESCRIPTION: description, ImageKeys.DESCRIPTION_MODEL: model}},
        )

    async def update_discussion_id(self, image_id: str, discussion_id: str) -> None:
        """Associate an image with a discussion."""
        await self.update_one(
            {"_id": image_id},
            {"$set": {ImageKeys.DISCUSSION_ID: discussion_id}},
        )

    async def find_by_mxc_url(self, mxc_url: str) -> dict[str, Any] | None:
        """Find an image by its mxc URL (deduplication check)."""
        return await self.find_one({ImageKeys.MXC_URL: mxc_url})

    async def find_existing_mxc_urls(self, mxc_urls: list[str]) -> set[str]:
        """Return the set of mxc_urls that already exist in the collection (batch dedup)."""
        if not mxc_urls:
            return set()
        docs = await self.collection.find(
            {ImageKeys.MXC_URL: {"$in": mxc_urls}},
            {ImageKeys.MXC_URL: 1},
        ).to_list(length=None)
        return {doc[ImageKeys.MXC_URL] for doc in docs}


def _date_to_timestamp_ms(date_str: str, end_of_day: bool = False) -> int:
    """Convert ISO date string to millisecond timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return int(dt.timestamp() * 1000)
