"""
Integration test: per-request runtime scoring dual-writes to MongoDB + Langfuse.

Drives the RAG conversation graph end-to-end with the LLM judge and Langfuse
client patched to fakes. Verifies that:
  - One `rag_evaluations` document lands in MongoDB with status COMPLETED and
    score keys equal to EvaluationMetric values (NOT DeepEval class names).
  - One `langfuse.score(...)` call is made per metric with the trace id that
    was injected into state.

Gated on RUNTIME_EVAL_INTEGRATION_ENABLED=true so the default pytest run does
not require a live MongoDB or burn OpenAI credits. CI flips it.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from constants import COLLECTION_RAG_EVALUATIONS, EvaluationMetric, EvaluationStatus
from custom_types.field_keys import RAGEvaluationKeys


pytestmark = pytest.mark.skipif(
    os.getenv("RUNTIME_EVAL_INTEGRATION_ENABLED", "false").lower() != "true",
    reason="Set RUNTIME_EVAL_INTEGRATION_ENABLED=true to run the runtime scoring integration",
)


def _ai_message(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    return msg


@pytest.mark.asyncio
async def test_rag_graph_dual_writes_scores_to_mongo_and_langfuse(monkeypatch):
    from db.connection import get_database
    from graphs.rag_conversation.graph import rag_conversation_graph
    from graphs.state_keys import RAGConversationStateKeys as Keys

    # 1. Force runtime eval on at full sampling
    monkeypatch.setenv("RUNTIME_EVAL_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_EVAL_SAMPLING_RATE", "1.0")
    from config import get_settings

    get_settings.cache_clear()

    trace_id = "integration-trace-1"
    session_id = "integration-session-1"

    # 2. Patch the LLM judge to always return a fixed JSON score
    chat_instance = MagicMock()
    chat_instance.ainvoke = AsyncMock(
        return_value=_ai_message('{"score": 0.9, "reasoning": "integration"}')
    )

    # 3. Capture langfuse.score() calls on a fake client
    fake_langfuse = MagicMock()
    fake_langfuse.score = MagicMock()

    # 4. Pre-seed the retrieval pipeline so the graph doesn't try to hit Mongo for chunks
    fake_retrieval = AsyncMock(
        return_value={
            "retrieved_chunks": [],
            "reranked_chunks": [{"content": "integration context"}],
            "context": "integration context",
            "citations": [],
            "freshness_warning": False,
            "oldest_source_date": None,
            "newest_source_date": None,
        }
    )

    fake_answer = AsyncMock(return_value="integration answer")

    with (
        patch("rag.evaluation.runtime.judge.ChatOpenAI", return_value=chat_instance),
        patch(
            "rag.evaluation.runtime.scorer.get_langfuse_client",
            return_value=fake_langfuse,
        ),
        patch("graphs.rag_conversation.nodes.RetrievalPipeline") as pipeline_cls,
        patch("graphs.rag_conversation.nodes.generate_answer", fake_answer),
    ):
        pipeline_cls.return_value.retrieve = fake_retrieval

        state = {
            Keys.SESSION_ID: session_id,
            Keys.QUERY: "what is integration?",
            Keys.CONTENT_SOURCES: [],
            Keys.CONVERSATION_HISTORY: [],
            Keys.LANGFUSE_TRACE_ID: trace_id,
        }

        result = await rag_conversation_graph.ainvoke(state)

    evaluation_id = result.get(Keys.EVALUATION_ID)
    assert evaluation_id, "Graph did not schedule an evaluation"

    # 5. The background scorer task is fire-and-forget. Drain pending tasks.
    import asyncio

    pending = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
    if pending:
        await asyncio.wait(pending, timeout=5)

    # 6. Assert: Mongo doc with status COMPLETED and enum-value score keys
    db = await get_database()
    doc = await db[COLLECTION_RAG_EVALUATIONS].find_one({RAGEvaluationKeys.EVALUATION_ID: evaluation_id})
    assert doc is not None, "No rag_evaluations doc was written"
    assert doc[RAGEvaluationKeys.STATUS] == EvaluationStatus.COMPLETED
    scores = doc[RAGEvaluationKeys.SCORES]
    assert set(scores.keys()) == {
        str(EvaluationMetric.FAITHFULNESS),
        str(EvaluationMetric.ANSWER_RELEVANCY),
        str(EvaluationMetric.HALLUCINATION),
    }, f"Score keys must be StrEnum values, got: {set(scores.keys())}"

    # 7. Assert: Langfuse received one score per metric, all with the same trace id
    assert fake_langfuse.score.call_count == 3
    for call in fake_langfuse.score.call_args_list:
        assert call.kwargs["trace_id"] == trace_id

    posted_names = {c.kwargs["name"] for c in fake_langfuse.score.call_args_list}
    assert posted_names == {
        str(EvaluationMetric.FAITHFULNESS),
        str(EvaluationMetric.ANSWER_RELEVANCY),
        str(EvaluationMetric.HALLUCINATION),
    }
