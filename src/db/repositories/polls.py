"""
Polls Repository

Manages poll records extracted from WhatsApp chats via Beeper/Matrix.
Polls are stored as first-class entities with structured question, options, and vote data.
"""

import logging
from datetime import datetime, UTC
from typing import Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_POLLS
from custom_types.field_keys import PollDbKeys

logger = logging.getLogger(__name__)


class PollsRepository(BaseRepository):
    """
    Repository for poll storage and retrieval.

    Stores:
    - Poll question and options
    - Vote counts per option
    - Sender and timestamp metadata
    - Links to runs and chats
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_POLLS)

    async def create_poll(
        self,
        poll_id: str,
        run_id: str,
        chat_name: str,
        data_source_name: str,
        sender: str,
        timestamp: int,
        question: str,
        matrix_event_id: str,
        options: list[dict[str, Any]],
        total_votes: int,
        unique_voter_count: int,
    ) -> str:
        """
        Create a new poll record.

        Args:
            poll_id: Unique identifier ({run_id}_poll_{matrix_event_id})
            run_id: Associated pipeline run ID
            chat_name: Source chat name
            data_source_name: Data source identifier
            sender: Anonymized sender ID
            timestamp: Unix timestamp in milliseconds
            question: Poll question text
            matrix_event_id: Original Matrix event ID
            options: List of option dicts with option_id, text, vote_count
            total_votes: Total number of votes across all options
            unique_voter_count: Number of unique voters

        Returns:
            Inserted document ID
        """
        document = {
            PollDbKeys.POLL_ID: poll_id,
            PollDbKeys.RUN_ID: run_id,
            PollDbKeys.CHAT_NAME: chat_name,
            PollDbKeys.DATA_SOURCE_NAME: data_source_name,
            PollDbKeys.SENDER: sender,
            PollDbKeys.TIMESTAMP: timestamp,
            PollDbKeys.QUESTION: question,
            PollDbKeys.MATRIX_EVENT_ID: matrix_event_id,
            PollDbKeys.OPTIONS: options,
            PollDbKeys.TOTAL_VOTES: total_votes,
            PollDbKeys.UNIQUE_VOTER_COUNT: unique_voter_count,
            PollDbKeys.CREATED_AT: datetime.now(UTC),
        }

        return await self.create(document)

    async def get_polls_by_run(self, run_id: str, chat_name: str | None = None) -> list[dict[str, Any]]:
        """
        Get all polls for a pipeline run, optionally filtered by chat.

        Args:
            run_id: Pipeline run ID
            chat_name: Optional chat name filter

        Returns:
            List of poll documents sorted by timestamp descending
        """
        query = {PollDbKeys.RUN_ID: run_id}
        if chat_name:
            query[PollDbKeys.CHAT_NAME] = chat_name

        return await self.find_many(query, sort=[(PollDbKeys.TIMESTAMP, -1)])

    async def get_poll(self, poll_id: str) -> dict[str, Any] | None:
        """
        Get a single poll by its ID.

        Args:
            poll_id: Unique poll identifier

        Returns:
            Poll document or None
        """
        return await self.find_by_id(PollDbKeys.POLL_ID, poll_id)

    async def get_polls_by_data_source(self, data_source_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get recent polls for a data source across all runs.

        Args:
            data_source_name: Data source identifier
            limit: Maximum number of polls to return

        Returns:
            List of poll documents sorted by timestamp descending
        """
        query = {PollDbKeys.DATA_SOURCE_NAME: data_source_name}
        return await self.find_many(query, sort=[(PollDbKeys.TIMESTAMP, -1)], limit=limit)
