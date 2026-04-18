"""
RAG Evaluations Repository

CRUD operations for the rag_evaluations collection (DeepEval quality scores).
"""

import logging
from datetime import datetime, UTC
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from constants import COLLECTION_RAG_EVALUATIONS, EvaluationStatus
from custom_types.field_keys import RAGEvaluationKeys as Keys
from db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class EvaluationsRepository(BaseRepository):
    """Repository for RAG evaluation results."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        super().__init__(db, COLLECTION_RAG_EVALUATIONS)

    async def create_evaluation(
        self,
        evaluation_id: str,
        session_id: str,
        message_id: str,
        query: str,
        response: str,
        retrieved_contexts: list[str],
    ) -> str:
        """
        Create a pending evaluation record.

        Args:
            evaluation_id: UUID for this evaluation
            session_id: Parent conversation session
            message_id: The assistant message being evaluated
            query: The user query
            response: The assistant response
            retrieved_contexts: List of context strings used for generation

        Returns:
            evaluation_id
        """
        document = {
            Keys.EVALUATION_ID: evaluation_id,
            Keys.SESSION_ID: session_id,
            Keys.MESSAGE_ID: message_id,
            Keys.QUERY: query,
            Keys.RESPONSE: response,
            Keys.RETRIEVED_CONTEXTS: retrieved_contexts,
            Keys.SCORES: {},
            Keys.OVERALL_PASSED: False,
            Keys.EVALUATION_MODEL: "",
            Keys.EVALUATION_DURATION_MS: 0,
            Keys.STATUS: EvaluationStatus.PENDING,
            Keys.ERROR: None,
            Keys.CREATED_AT: datetime.now(UTC),
            Keys.COMPLETED_AT: None,
        }
        await self.create(document)
        return evaluation_id

    async def update_scores(
        self,
        evaluation_id: str,
        scores: dict[str, float],
        overall_passed: bool,
        evaluation_model: str,
        duration_ms: int,
    ) -> bool:
        """
        Update evaluation with computed scores.

        Args:
            evaluation_id: Evaluation to update
            scores: Dict of metric_name -> score
            overall_passed: Whether all thresholds passed
            evaluation_model: Model used for evaluation
            duration_ms: Time taken in milliseconds
        """
        return await self.update_one(
            {Keys.EVALUATION_ID: evaluation_id},
            {
                "$set": {
                    Keys.SCORES: scores,
                    Keys.OVERALL_PASSED: overall_passed,
                    Keys.EVALUATION_MODEL: evaluation_model,
                    Keys.EVALUATION_DURATION_MS: duration_ms,
                    Keys.STATUS: EvaluationStatus.COMPLETED,
                    Keys.COMPLETED_AT: datetime.now(UTC),
                }
            },
        )

    async def mark_failed(self, evaluation_id: str, error: str) -> bool:
        """Mark an evaluation as failed."""
        return await self.update_one(
            {Keys.EVALUATION_ID: evaluation_id},
            {
                "$set": {
                    Keys.STATUS: EvaluationStatus.FAILED,
                    Keys.ERROR: error,
                    Keys.COMPLETED_AT: datetime.now(UTC),
                }
            },
        )

    async def get_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        """Get a single evaluation by ID."""
        return await self.find_by_id(Keys.EVALUATION_ID, evaluation_id)

    async def get_session_evaluations(self, session_id: str) -> list[dict[str, Any]]:
        """Get all evaluations for a session."""
        return await self.find_many(
            {Keys.SESSION_ID: session_id},
            sort=[(Keys.CREATED_AT, -1)],
        )
