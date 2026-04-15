"""
RAG Quality Evaluator

Runs DeepEval metrics asynchronously in the background.
Fail-soft: evaluation failures never block or crash the conversation.
"""

import asyncio
import logging
import time
from typing import Any

from config import get_settings
from db.connection import get_database
from db.repositories.rag_evaluations import EvaluationsRepository

logger = logging.getLogger(__name__)


async def run_evaluation(
    evaluation_id: str,
    session_id: str,
    query: str,
    answer: str,
    contexts: list[str],
    message_id: str = "",
) -> dict[str, Any] | None:
    """
    Run DeepEval metrics against a RAG response.

    This function is designed to be called via asyncio.create_task() for
    non-blocking background evaluation.

    Args:
        evaluation_id: UUID for this evaluation run
        session_id: Parent conversation session
        query: The user query
        answer: The assistant response
        contexts: Retrieved context strings
        message_id: The assistant message ID

    Returns:
        Evaluation result dict, or None if evaluation fails
    """
    settings = get_settings().deepeval

    db = await get_database()
    eval_repo = EvaluationsRepository(db)

    # Create pending record
    await eval_repo.create_evaluation(
        evaluation_id=evaluation_id,
        session_id=session_id,
        message_id=message_id,
        query=query,
        response=answer,
        retrieved_contexts=contexts,
    )

    try:
        from deepeval.test_case import LLMTestCase
        from rag.evaluation.metrics import create_metrics
    except ImportError:
        logger.warning("deepeval not installed, skipping evaluation")
        await eval_repo.mark_failed(evaluation_id, "deepeval not installed")
        return None

    start_time = time.monotonic()

    try:
        # Build test case
        test_case = LLMTestCase(
            input=query,
            actual_output=answer,
            retrieval_context=contexts,
        )

        # Create and run metrics
        metrics = create_metrics()
        scores: dict[str, float] = {}
        all_passed = True

        for metric in metrics:
            try:
                await asyncio.to_thread(metric.measure, test_case)
                scores[metric.__class__.__name__] = metric.score
                if not metric.is_successful():
                    all_passed = False
            except Exception as e:
                logger.warning(f"Metric {metric.__class__.__name__} failed: {e}")
                scores[metric.__class__.__name__] = 0.0
                all_passed = False

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Store results
        await eval_repo.update_scores(
            evaluation_id=evaluation_id,
            scores=scores,
            overall_passed=all_passed,
            evaluation_model=settings.eval_model,
            duration_ms=duration_ms,
        )

        logger.info(
            f"Evaluation complete: evaluation_id={evaluation_id}, "
            f"passed={all_passed}, duration={duration_ms}ms, "
            f"scores={scores}"
        )

        return {
            "evaluation_id": evaluation_id,
            "scores": scores,
            "overall_passed": all_passed,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        logger.warning(f"Evaluation failed: evaluation_id={evaluation_id}, error={e}")
        await eval_repo.mark_failed(evaluation_id, str(e))
        return None
