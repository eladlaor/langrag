"""
Local LLM-as-a-judge for runtime RAG quality scoring.

The judge calls `gpt-4.1-mini` (configurable) with a metric-specific prompt
template, parses the JSON response, clamps the score to [0, 1], and returns
a `JudgeResult`. Timeouts and parse errors are surfaced as `JudgeResult.error`
rather than raised; callers are expected to be fail-soft.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from langchain_openai import ChatOpenAI

from constants import EvaluationMetric
from rag.evaluation.runtime.prompts import PROMPT_BY_METRIC


logger = logging.getLogger(__name__)


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class JudgeResult:
    """Result of a single LLM-judge call. `score=None` means the call failed."""

    score: float | None
    reasoning: str | None
    error: str | None


class LLMJudge:
    """
    Single-shot LLM judge.

    Re-instantiate per scorer call rather than caching across requests so the
    `ChatOpenAI` client picks up env-driven config changes during tests.
    """

    def __init__(self, model: str, timeout: float) -> None:
        self._timeout = timeout
        self._client = ChatOpenAI(model=model, temperature=0)

    async def evaluate(
        self,
        metric: EvaluationMetric,
        query: str,
        answer: str,
        context: str,
    ) -> JudgeResult:
        prompt_template = PROMPT_BY_METRIC.get(metric)
        if prompt_template is None:
            return JudgeResult(score=None, reasoning=None, error=f"no_prompt_for_metric:{metric}")

        prompt = prompt_template.format(query=query, answer=answer, context=context)

        try:
            message = await asyncio.wait_for(self._client.ainvoke(prompt), timeout=self._timeout)
        except TimeoutError:
            logger.warning(f"Judge timeout for metric={metric}, timeout={self._timeout}s")
            return JudgeResult(score=None, reasoning=None, error="timeout")
        except Exception as exc:
            logger.warning(f"Judge call failed for metric={metric}: {exc}")
            return JudgeResult(score=None, reasoning=None, error=f"call_error:{type(exc).__name__}")

        content = getattr(message, "content", "")
        return self._parse(content, metric)

    def _parse(self, content: str, metric: EvaluationMetric) -> JudgeResult:
        if not isinstance(content, str) or not content.strip():
            return JudgeResult(score=None, reasoning=None, error="parse_error")

        match = _JSON_OBJECT_RE.search(content)
        if not match:
            return JudgeResult(score=None, reasoning=None, error="parse_error")

        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return JudgeResult(score=None, reasoning=None, error="parse_error")

        if not isinstance(payload, dict) or "score" not in payload:
            return JudgeResult(score=None, reasoning=None, error="parse_error")

        raw_score = payload.get("score")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            return JudgeResult(score=None, reasoning=None, error="parse_error")

        clamped = max(0.0, min(1.0, score))
        reasoning = payload.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            reasoning = str(reasoning)

        return JudgeResult(score=clamped, reasoning=reasoning, error=None)
