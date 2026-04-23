"""
Discussions Repository

Manages discussion records extracted from WhatsApp chats.
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_DISCUSSIONS, DEFAULT_EMBEDDING_MODEL
from custom_types.field_keys import DbFieldKeys, DiscussionKeys

logger = logging.getLogger(__name__)


class DiscussionsRepository(BaseRepository):
    """
    Repository for discussion storage and retrieval.

    Stores:
    - Discussion metadata (title, nutshell, chat name)
    - Ranking scores
    - Message counts
    - Links to messages
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_DISCUSSIONS)

    async def create_discussion(
        self,
        discussion_id: str,
        run_id: str,
        chat_name: str,
        title: str,
        nutshell: str,
        message_ids: list[str],
        ranking_score: float = 0.0,
        first_message_timestamp: int = None,
        metadata: dict[str, Any] = None,
        generate_embedding: bool = True,
    ) -> str:
        """
        Create a new discussion record with optional embedding generation.

        Args:
            discussion_id: Unique identifier for the discussion
            run_id: Associated pipeline run ID
            chat_name: Source chat name
            title: Discussion title
            nutshell: Brief summary
            message_ids: List of message IDs in this discussion
            ranking_score: Relevance ranking score (0-10)
            first_message_timestamp: Timestamp of first message
            metadata: Additional metadata
            generate_embedding: Auto-generate embedding for semantic search (default: True)

        Returns:
            Inserted document ID
        """
        document = {
            DbFieldKeys.DISCUSSION_ID: discussion_id,
            DbFieldKeys.RUN_ID: run_id,
            DbFieldKeys.CHAT_NAME: chat_name,
            DbFieldKeys.TITLE: title,
            DbFieldKeys.NUTSHELL: nutshell,
            DbFieldKeys.MESSAGE_IDS: message_ids,
            DbFieldKeys.MESSAGE_COUNT: len(message_ids),
            DbFieldKeys.RANKING_SCORE: ranking_score,
            DiscussionKeys.FIRST_MESSAGE_TIMESTAMP: first_message_timestamp,
            DbFieldKeys.METADATA: metadata or {},
            DbFieldKeys.CREATED_AT: datetime.now(UTC),
        }

        # Generate embedding for semantic search (fail-soft)
        # embed_text() is synchronous (OpenAI API call), offload to thread
        if generate_embedding:
            try:
                from utils.embedding import EmbeddingProviderFactory

                embedder = EmbeddingProviderFactory.create()
                discussion_text = f"{title}. {nutshell}"
                embedding = await asyncio.to_thread(embedder.embed_text, discussion_text)

                if embedding:
                    document[DbFieldKeys.EMBEDDING] = embedding
                    document[DbFieldKeys.EMBEDDING_MODEL] = DEFAULT_EMBEDDING_MODEL
                    document[DbFieldKeys.EMBEDDING_TIMESTAMP] = datetime.now(UTC)
                    logger.info(f"Generated embedding for discussion: {discussion_id}, " f"dimension={len(embedding)}")
                else:
                    logger.warning(f"Failed to generate embedding for discussion: {discussion_id}")

            except Exception as e:
                logger.error(f"Embedding generation failed for discussion {discussion_id}: {e}. " "Proceeding without embedding (fail-soft).")

        return await self.create(document)

    async def get_discussion(self, discussion_id: str) -> dict[str, Any] | None:
        """Get a discussion by its ID."""
        return await self.find_by_id(DbFieldKeys.DISCUSSION_ID, discussion_id)

    async def get_discussions_by_run(
        self,
        run_id: str,
        sort_by_ranking: bool = True,
        limit: int = 0,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get all discussions for a run.

        Args:
            run_id: Pipeline run ID
            sort_by_ranking: Sort by ranking score descending (default) or by creation date
            limit: Maximum discussions to return (0 = no limit)
            offset: Number of discussions to skip for pagination
        """
        sort = [(DbFieldKeys.RANKING_SCORE, -1)] if sort_by_ranking else [(DbFieldKeys.CREATED_AT, 1)]
        return await self.find_many({DbFieldKeys.RUN_ID: run_id}, sort=sort, limit=limit, skip=offset)

    async def get_top_discussions(
        self,
        run_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get top-ranked discussions for a run."""
        return await self.find_many(
            {DbFieldKeys.RUN_ID: run_id},
            sort=[(DbFieldKeys.RANKING_SCORE, -1)],
            limit=limit,
        )

    async def search_discussions(
        self,
        search_text: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text search on discussion titles and nutshells."""
        return await self.find_many(
            {"$text": {"$search": search_text}},
            limit=limit,
        )

    async def update_ranking(
        self,
        discussion_id: str,
        ranking_score: float,
    ) -> bool:
        """Update the ranking score for a discussion."""
        return await self.update_one(
            {DbFieldKeys.DISCUSSION_ID: discussion_id},
            {"$set": {DbFieldKeys.RANKING_SCORE: ranking_score}},
        )

    async def get_discussions_with_embeddings(self, run_ids: list[str], limit: int = 1000) -> list[dict[str, Any]]:
        """
        Retrieve historical discussions with pre-computed embeddings.

        Used by anti-repetition system to find similar discussions from
        previous newsletters via semantic similarity.

        Args:
            run_ids: List of run_ids to query (previous newsletters)
            limit: Maximum discussions to return

        Returns:
            List of discussion documents with embedding field

        Example:
            >>> repo = DiscussionsRepository(db)
            >>> historical = await repo.get_discussions_with_embeddings(
            ...     run_ids=["run_1", "run_2"],
            ...     limit=500
            ... )
            >>> for disc in historical:
            ...     similarity = compute_similarity(current_embedding, disc['embedding'])
        """
        try:
            cursor = self.collection.find(
                {
                    DbFieldKeys.RUN_ID: {"$in": run_ids},
                    DbFieldKeys.EMBEDDING: {"$exists": True},  # Only discussions with embeddings
                },
                {DbFieldKeys.DISCUSSION_ID: 1, DbFieldKeys.TITLE: 1, DbFieldKeys.NUTSHELL: 1, DbFieldKeys.RUN_ID: 1, DbFieldKeys.CHAT_NAME: 1, DbFieldKeys.EMBEDDING: 1, DbFieldKeys.EMBEDDING_MODEL: 1, DbFieldKeys.CREATED_AT: 1, "_id": 0},
            ).limit(limit)

            discussions = await cursor.to_list(length=limit)

            logger.info(f"Retrieved {len(discussions)} discussions with embeddings from " f"{len(run_ids)} run_ids")

            return discussions

        except Exception as e:
            logger.error(f"Failed to fetch discussions with embeddings: {e}, " f"run_ids={run_ids[:3]}...")
            raise
