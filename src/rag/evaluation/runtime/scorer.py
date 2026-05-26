"""
Runtime RAG quality scorer.

Orchestrates the LLM judges and dual-writes scores to:
  1. MongoDB (rag_evaluations collection) -> preserves Grafana dashboards.
  2. Langfuse (trace scores via langfuse.score) -> attaches scores to traces.

Mongo and Langfuse writes are independent fail-soft try/except blocks. A
failure on either side is logged and swallowed; the conversation never breaks
because of a scoring problem.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from config import get_settings
from constants import EvaluationMetric
from db.connection import get_database
from db.repositories.rag_evaluations import EvaluationsRepository
from observability.llm.langfuse_client import get_langfuse_client
from rag.evaluation.runtime.judge import JudgeResult, LLMJudge


logger = logging.getLogger(__name__)


def _coerce_metric(name: str) -> EvaluationMetric | None:
    try:
        return EvaluationMetric(name)
    except ValueError:
        logger.warning(f"Unknown runtime metric requested: {name}")
        return None


def _passes_threshold(metric: EvaluationMetric, score: float, settings: Any) -> bool:
    """
    Return True if `score` meets the metric's threshold.

    Hallucination is inverted: lower scores are better, so we check score <= threshold.
    Other metrics use score >= threshold.
    """
    if metric == EvaluationMetric.FAITHFULNESS:
        return score >= settings.faithfulness_threshold
    if metric == EvaluationMetric.ANSWER_RELEVANCY:
        return score >= settings.answer_relevancy_threshold
    if metric == EvaluationMetric.HALLUCINATION:
        return score <= settings.hallucination_threshold
    # Unknown metric -> conservative pass=False
    return False


def _post_langfuse_score(
    langfuse: Any,
    *,
    trace_id: str,
    name: str,
    value: float,
    comment: str | None,
) -> None:
    """Local helper mirroring observability/llm/evaluation._submit_score."""
    score_kwargs: dict[str, Any] = {
        "trace_id": trace_id,
        "name": name,
        "value": value,
    }
    if comment:
        score_kwargs["comment"] = comment
    langfuse.score(**score_kwargs)


async def score_response(
    *,
    evaluation_id: str,
    session_id: str,
    query: str,
    answer: str,
    contexts: list[str],
    langfuse_trace_id: str | None,
    message_id: str = "",
) -> dict[str, Any] | None:
    """
    Score a single RAG response and dual-write the results.

    Returns a result dict (evaluation_id, scores, overall_passed, duration_ms)
    on completion, or None if the very first step (creating the pending Mongo
    record) fails. Mongo update failures and Langfuse failures are fail-soft.
    """
    settings = get_settings().runtime_eval

    # 1. Create pending Mongo record so partial results have a doc to update.
    try:
        db = await get_database()
        eval_repo = EvaluationsRepository(db)
        await eval_repo.create_evaluation(
            evaluation_id=evaluation_id,
            session_id=session_id,
            message_id=message_id,
            query=query,
            response=answer,
            retrieved_contexts=contexts,
        )
    except Exception as exc:
        logger.warning(f"Failed to create pending evaluation record (evaluation_id={evaluation_id}): {exc}")
        return None

    # 2. Resolve which metrics to run from the config.
    metrics: list[EvaluationMetric] = []
    for name in settings.metrics:
        coerced = _coerce_metric(name)
        if coerced is not None:
            metrics.append(coerced)

    if not metrics:
        logger.warning(f"No valid runtime metrics configured (evaluation_id={evaluation_id})")
        return None

    # 3. Run all judges concurrently. The judge itself is fail-soft (returns
    #    JudgeResult with `score=None` on failure), but we still pass
    #    return_exceptions=True as belt-and-braces for unexpected exceptions.
    context_str = "\n\n".join(contexts) if contexts else ""
    judge = LLMJudge(model=settings.eval_model, timeout=float(settings.judge_timeout_seconds))

    start_time = time.monotonic()
    raw_results = await asyncio.gather(
        *(judge.evaluate(metric=m, query=query, answer=answer, context=context_str) for m in metrics),
        return_exceptions=True,
    )
    duration_ms = int((time.monotonic() - start_time) * 1000)

    # 4. Build the scores dict and overall_passed flag.
    scores: dict[str, float] = {}
    reasonings: dict[str, str] = {}
    overall_passed = True

    for metric, raw in zip(metrics, raw_results):
        if isinstance(raw, BaseException) or not isinstance(raw, JudgeResult) or raw.score is None:
            # Judge failed or returned no score -> overall fails, no score recorded.
            overall_passed = False
            continue
        scores[str(metric)] = raw.score
        if raw.reasoning:
            reasonings[str(metric)] = raw.reasoning
        if not _passes_threshold(metric, raw.score, settings):
            overall_passed = False

    # 5. Mongo write (fail-soft).
    try:
        await eval_repo.update_scores(
            evaluation_id=evaluation_id,
            scores=scores,
            overall_passed=overall_passed,
            evaluation_model=settings.eval_model,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to write runtime eval scores to Mongo (evaluation_id={evaluation_id}): {exc}"
        )

    # 6. Langfuse write (fail-soft, only if trace id + client available).
    if langfuse_trace_id:
        langfuse = get_langfuse_client()
        if langfuse:
            for metric_name, score in scores.items():
                try:
                    _post_langfuse_score(
                        langfuse,
                        trace_id=langfuse_trace_id,
                        name=metric_name,
                        value=score,
                        comment=reasonings.get(metric_name),
                    )
                except Exception as exc:
                    logger.warning(
                        f"Failed to post runtime eval score to Langfuse "
                        f"(evaluation_id={evaluation_id}, metric={metric_name}): {exc}"
                    )

    return {
        "evaluation_id": evaluation_id,
        "scores": scores,
        "overall_passed": overall_passed,
        "duration_ms": duration_ms,
    }
