"""
RAG Chunks Repository

CRUD operations for the rag_chunks collection (embedded content chunks).
"""

import logging
from datetime import datetime, UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import COLLECTION_RAG_CHUNKS
from custom_types.field_keys import RAGChunkKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ChunksRepository(BaseRepository):
    """Repository for RAG content chunks."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_CHUNKS)

    async def store_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """
        Store multiple chunks with embeddings.

        Args:
            chunks: List of chunk documents (must include chunk_id, content, embedding, etc.)

        Returns:
            Number of chunks inserted
        """
        if not chunks:
            return 0

        now = datetime.now(UTC)
        for chunk in chunks:
            chunk[Keys.CREATED_AT] = now

        try:
            await self.create_many(chunks)
            logger.info(f"Stored {len(chunks)} chunks")
            return len(chunks)
        except Exception as e:
            logger.error(f"Failed to store chunks: {e}")
            raise

    async def source_exists(self, source_id: str) -> bool:
        """Check if chunks for a given source_id already exist (idempotency guard)."""
        return await self.exists({Keys.SOURCE_ID: source_id})

    async def get_chunks_by_source(self, source_id: str) -> list[dict[str, Any]]:
        """Get all chunks for a source, ordered by chunk_index."""
        return await self.find_many(
            {Keys.SOURCE_ID: source_id},
            sort=[(Keys.CHUNK_INDEX, 1)],
        )

    async def delete_source_chunks(self, source_id: str) -> int:
        """Delete all chunks for a given source (for re-ingestion)."""
        count = await self.delete_many({Keys.SOURCE_ID: source_id})
        logger.info(f"Deleted {count} chunks for source_id={source_id}")
        return count

    async def count_by_source_type(self) -> dict[str, int]:
        """Get chunk counts grouped by content_source type."""
        pipeline = [
            {"$group": {"_id": f"${Keys.CONTENT_SOURCE}", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=None)
        return {doc["_id"]: doc["count"] for doc in results}

    async def list_ingested_sources(self, content_source: str | None = None) -> list[dict]:
        """
        List distinct ingested sources with metadata.

        Args:
            content_source: Optional filter by content source type

        Returns:
            List of dicts with source_id, source_title, content_source, chunk_count
        """
        match_stage = {}
        if content_source:
            match_stage[Keys.CONTENT_SOURCE] = content_source

        pipeline = [
            {"$match": match_stage} if match_stage else {"$match": {}},
            {
                "$group": {
                    "_id": f"${Keys.SOURCE_ID}",
                    "source_title": {"$first": f"${Keys.SOURCE_TITLE}"},
                    "content_source": {"$first": f"${Keys.CONTENT_SOURCE}"},
                    "chunk_count": {"$sum": 1},
                    "created_at": {"$min": f"${Keys.CREATED_AT}"},
                }
            },
            {"$sort": {"created_at": -1}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=None)
        return [
            {
                Keys.SOURCE_ID: doc["_id"],
                Keys.SOURCE_TITLE: doc["source_title"],
                Keys.CONTENT_SOURCE: doc["content_source"],
                "chunk_count": doc["chunk_count"],
                Keys.CREATED_AT: doc["created_at"],
            }
            for doc in results
        ]
