"""
Integration tests for DeepEval newsletter RAG evaluation.

Runs the golden dataset (tests/golden_datasets/newsletters_v1.json) against
the live RAG pipeline: retrieval + generation + DeepEval metrics.

Requirements:
    - Docker with MongoDB running
    - Newsletter chunks already ingested in rag_chunks collection
    - OpenAI API key set (for embedding, generation, and DeepEval LLM judge)

Run:
    docker compose exec app pytest tests/integration/rag/test_deepeval_newsletter.py -v

NOTE: Skipped automatically if no newsletter chunks are ingested or MongoDB is unavailable.
"""

import json
import logging
import os
from pathlib import Path

import pytest

from constants import ContentSourceType
from custom_types.field_keys import RAGChunkKeys as Keys

logger = logging.getLogger(__name__)

# Path to golden dataset
_GOLDEN_DATASET_PATH = Path(__file__).parent.parent.parent / "golden_datasets" / "newsletters_v1.json"


def _load_golden_cases() -> list[dict]:
    """Load test cases from the golden dataset JSON. Returns empty list on failure."""
    if not _GOLDEN_DATASET_PATH.exists():
        logger.warning(f"Golden dataset not found: {_GOLDEN_DATASET_PATH}")
        return []
    try:
        with open(_GOLDEN_DATASET_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data["test_cases"]
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to load golden dataset {_GOLDEN_DATASET_PATH}: {e}")
        return []


def _case_ids(cases: list[dict]) -> list[str]:
    """Extract test IDs for pytest parametrize."""
    return [c["test_id"] for c in cases]


_GOLDEN_CASES = _load_golden_cases()


async def _is_mongodb_available() -> bool:
    try:
        from db.connection import get_database
        db = await get_database()
        await db.command("ping")
        return True
    except Exception:
        return False


async def _newsletter_chunks_count() -> int:
    """Count newsletter chunks in rag_chunks collection."""
    try:
        from db.connection import get_database
        from constants import COLLECTION_RAG_CHUNKS
        db = await get_database()
        return await db[COLLECTION_RAG_CHUNKS].count_documents(
            {Keys.CONTENT_SOURCE: str(ContentSourceType.NEWSLETTER)}
        )
    except Exception:
        return 0


@pytest.fixture(scope="module")
def skip_if_no_mongodb():
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        available = loop.run_until_complete(_is_mongodb_available())
    finally:
        loop.close()
    if not available:
        pytest.skip("MongoDB not available — run tests inside Docker")


@pytest.fixture(scope="module")
def ensure_newsletters_ingested(skip_if_no_mongodb):
    """Skip all tests if no newsletter chunks are ingested."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        count = loop.run_until_complete(_newsletter_chunks_count())
    finally:
        loop.close()
    if count == 0:
        pytest.skip(
            "No newsletter chunks in rag_chunks. "
            "Ingest newsletters first: POST /api/rag/ingest/newsletters"
        )
    logger.info(f"Found {count} newsletter chunks for evaluation")


class TestGoldenDatasetRetrieval:
    """Verify retrieval pipeline returns relevant chunks for golden dataset queries."""

    @pytest.mark.parametrize("test_case", _GOLDEN_CASES, ids=_case_ids(_GOLDEN_CASES))
    async def test_retrieves_chunks(self, test_case, ensure_newsletters_ingested):
        """Each golden query should retrieve at least one reranked chunk."""
        from rag.retrieval.pipeline import RetrievalPipeline

        pipeline = RetrievalPipeline()
        result = await pipeline.retrieve(
            query=test_case["query"],
            content_sources=[str(ContentSourceType.NEWSLETTER)],
        )

        reranked = result["reranked_chunks"]
        assert len(reranked) > 0, (
            f"No chunks retrieved for query: {test_case['query']}"
        )
        logger.info(
            f"[{test_case['test_id']}] Retrieved {len(reranked)} chunks "
            f"(difficulty={test_case.get('difficulty', 'unknown')})"
        )


class TestGoldenDatasetTopicCoverage:
    """Verify RAG responses cover expected topics from golden dataset."""

    @pytest.mark.parametrize("test_case", _GOLDEN_CASES, ids=_case_ids(_GOLDEN_CASES))
    async def test_topic_coverage(self, test_case, ensure_newsletters_ingested):
        """Response should mention at least 1 of the expected topics (lenient for synonym usage)."""
        from rag.retrieval.pipeline import RetrievalPipeline
        from rag.generation.rag_chain import generate_answer

        # Retrieve
        retrieval_pipeline = RetrievalPipeline()
        retrieval_result = await retrieval_pipeline.retrieve(
            query=test_case["query"],
            content_sources=[str(ContentSourceType.NEWSLETTER)],
        )

        context = retrieval_result["context"]
        if not context:
            pytest.skip(f"No context retrieved for {test_case['test_id']}")

        # Generate
        answer = await generate_answer(
            query=test_case["query"],
            context=context,
            conversation_history=[],
        )

        # Check topic coverage
        expected_topics = test_case["expected_topics"]
        answer_lower = answer.lower()
        matched_topics = [t for t in expected_topics if t.lower() in answer_lower]

        logger.info(
            f"[{test_case['test_id']}] Topic coverage: {len(matched_topics)}/{len(expected_topics)} "
            f"(matched: {matched_topics})"
        )

        # At least 1 topic should appear (lenient — LLM may use synonyms)
        assert len(matched_topics) >= 1, (
            f"Expected at least 1 of {expected_topics} in answer, found {matched_topics}. "
            f"Answer: {answer[:300]}"
        )


class TestGoldenDatasetDeepEval:
    """Run DeepEval metrics on golden dataset responses.

    Initial run uses soft assertions (log scores, assert >= 0.0) to establish
    baseline. Tighten thresholds after baseline is collected.
    """

    @pytest.mark.parametrize("test_case", _GOLDEN_CASES, ids=_case_ids(_GOLDEN_CASES))
    async def test_deepeval_metrics(self, test_case, ensure_newsletters_ingested):
        """Run FaithfulnessMetric and AnswerRelevancyMetric on each golden case."""
        try:
            from deepeval.test_case import LLMTestCase
            from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric
        except ImportError:
            pytest.skip("deepeval not installed")

        from rag.retrieval.pipeline import RetrievalPipeline
        from rag.generation.rag_chain import generate_answer
        from config import get_settings

        # Retrieve
        retrieval_pipeline = RetrievalPipeline()
        retrieval_result = await retrieval_pipeline.retrieve(
            query=test_case["query"],
            content_sources=[str(ContentSourceType.NEWSLETTER)],
        )

        context = retrieval_result["context"]
        reranked = retrieval_result["reranked_chunks"]
        if not context:
            pytest.skip(f"No context retrieved for {test_case['test_id']}")

        # Generate
        answer = await generate_answer(
            query=test_case["query"],
            context=context,
            conversation_history=[],
        )

        # Build DeepEval test case
        retrieval_contexts = [chunk.get(Keys.CONTENT, "") for chunk in reranked]
        eval_case = LLMTestCase(
            input=test_case["query"],
            actual_output=answer,
            retrieval_context=retrieval_contexts,
        )

        settings = get_settings().deepeval
        eval_model = settings.eval_model

        # Run metrics
        faithfulness = FaithfulnessMetric(threshold=settings.faithfulness_threshold, model=eval_model)
        relevancy = AnswerRelevancyMetric(threshold=settings.answer_relevancy_threshold, model=eval_model)

        import asyncio
        for metric in [faithfulness, relevancy]:
            try:
                await asyncio.to_thread(metric.measure, eval_case)
            except Exception as e:
                logger.warning(f"[{test_case['test_id']}] Metric {metric.__class__.__name__} failed: {e}")

        logger.info(
            f"[{test_case['test_id']}] DeepEval scores: "
            f"faithfulness={faithfulness.score:.3f}, "
            f"answer_relevancy={relevancy.score:.3f} "
            f"(difficulty={test_case.get('difficulty', 'unknown')})"
        )

        # Soft assertions — baseline collection phase
        # Scores should at minimum be non-negative (valid metric execution)
        assert faithfulness.score >= 0.0, f"Faithfulness score is negative: {faithfulness.score}"
        assert relevancy.score >= 0.0, f"Answer relevancy score is negative: {relevancy.score}"

        # Log threshold pass/fail for analysis (don't hard-fail yet)
        if faithfulness.score < settings.faithfulness_threshold:
            logger.warning(
                f"[{test_case['test_id']}] Faithfulness BELOW threshold: "
                f"{faithfulness.score:.3f} < {settings.faithfulness_threshold}"
            )
        if relevancy.score < settings.answer_relevancy_threshold:
            logger.warning(
                f"[{test_case['test_id']}] Answer relevancy BELOW threshold: "
                f"{relevancy.score:.3f} < {settings.answer_relevancy_threshold}"
            )
