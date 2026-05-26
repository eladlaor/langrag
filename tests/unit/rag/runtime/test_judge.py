"""
Unit tests for the runtime LLM judge.

The judge wraps a ChatOpenAI call with a prompt template, parses a JSON score
out of the response, clamps it to [0, 1], and classifies failures (parse error,
timeout) without raising.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import EvaluationMetric


@pytest.fixture
def fake_chat_response():
    """Build a fake langchain AIMessage-like response with a `content` attribute."""

    def _build(content: str) -> MagicMock:
        msg = MagicMock()
        msg.content = content
        return msg

    return _build


@pytest.fixture
def patched_chat_openai(fake_chat_response):
    """
    Patch langchain_openai.ChatOpenAI used by the judge.

    Yields a tuple (chat_openai_class_mock, instance_mock). The instance has
    `ainvoke` as an AsyncMock you can configure per test.
    """
    instance = MagicMock()
    instance.ainvoke = AsyncMock(return_value=fake_chat_response('{"score": 0.5, "reasoning": "neutral"}'))
    with patch("rag.evaluation.runtime.judge.ChatOpenAI", return_value=instance) as cls:
        yield cls, instance


class TestLLMJudge:
    """Tests for rag.evaluation.runtime.judge.LLMJudge."""

    async def test_returns_parsed_score_in_unit_interval(self, patched_chat_openai, fake_chat_response):
        from rag.evaluation.runtime.judge import LLMJudge

        _, instance = patched_chat_openai
        instance.ainvoke.return_value = fake_chat_response('{"score": 0.87, "reasoning": "well grounded"}')

        judge = LLMJudge(model="gpt-4.1-mini", timeout=10.0)
        result = await judge.evaluate(
            metric=EvaluationMetric.FAITHFULNESS,
            query="What is RAG?",
            answer="RAG is retrieval augmented generation.",
            context="RAG combines retrieval with generation.",
        )

        assert result.score == pytest.approx(0.87)
        assert result.reasoning == "well grounded"
        assert result.error is None

    async def test_clamps_score_above_one(self, patched_chat_openai, fake_chat_response):
        from rag.evaluation.runtime.judge import LLMJudge

        _, instance = patched_chat_openai
        instance.ainvoke.return_value = fake_chat_response('{"score": 1.5, "reasoning": "too high"}')

        judge = LLMJudge(model="gpt-4.1-mini", timeout=10.0)
        result = await judge.evaluate(EvaluationMetric.FAITHFULNESS, "q", "a", "c")

        assert result.score == 1.0
        assert result.error is None

    async def test_clamps_score_below_zero(self, patched_chat_openai, fake_chat_response):
        from rag.evaluation.runtime.judge import LLMJudge

        _, instance = patched_chat_openai
        instance.ainvoke.return_value = fake_chat_response('{"score": -0.2, "reasoning": "negative"}')

        judge = LLMJudge(model="gpt-4.1-mini", timeout=10.0)
        result = await judge.evaluate(EvaluationMetric.FAITHFULNESS, "q", "a", "c")

        assert result.score == 0.0
        assert result.error is None

    async def test_malformed_output_returns_parse_error(self, patched_chat_openai, fake_chat_response):
        from rag.evaluation.runtime.judge import LLMJudge

        _, instance = patched_chat_openai
        instance.ainvoke.return_value = fake_chat_response("banana — not JSON at all")

        judge = LLMJudge(model="gpt-4.1-mini", timeout=10.0)
        result = await judge.evaluate(EvaluationMetric.FAITHFULNESS, "q", "a", "c")

        assert result.score is None
        assert result.error == "parse_error"

    async def test_json_without_score_field_returns_parse_error(self, patched_chat_openai, fake_chat_response):
        from rag.evaluation.runtime.judge import LLMJudge

        _, instance = patched_chat_openai
        instance.ainvoke.return_value = fake_chat_response('{"reasoning": "no score key"}')

        judge = LLMJudge(model="gpt-4.1-mini", timeout=10.0)
        result = await judge.evaluate(EvaluationMetric.FAITHFULNESS, "q", "a", "c")

        assert result.score is None
        assert result.error == "parse_error"

    async def test_timeout_returns_timeout_error(self, patched_chat_openai):
        from rag.evaluation.runtime.judge import LLMJudge

        _, instance = patched_chat_openai

        async def slow_ainvoke(_):
            await asyncio.sleep(5)

        instance.ainvoke = AsyncMock(side_effect=slow_ainvoke)

        judge = LLMJudge(model="gpt-4.1-mini", timeout=0.05)
        result = await judge.evaluate(EvaluationMetric.FAITHFULNESS, "q", "a", "c")

        assert result.score is None
        assert result.error == "timeout"

    async def test_chat_openai_constructed_with_configured_model(self, patched_chat_openai):
        from rag.evaluation.runtime.judge import LLMJudge

        cls, _ = patched_chat_openai
        LLMJudge(model="gpt-4.1-mini", timeout=10.0)

        cls.assert_called_once()
        kwargs = cls.call_args.kwargs
        assert kwargs.get("model") == "gpt-4.1-mini"
        # temperature=0 keeps the judge deterministic
        assert kwargs.get("temperature") == 0

    # Note: the AST-based regression guard for deepeval imports lives in
    # tests/unit/rag/runtime/test_no_deepeval_import.py — that test is robust
    # to sys.modules pollution from other tests in the same session.
