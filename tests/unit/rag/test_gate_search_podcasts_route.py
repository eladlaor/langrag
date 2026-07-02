"""EVAL-1: the eval gate can route a case through the public search_podcasts path
(retrieval-only) instead of rag_query, scoring recall@k + date_filter_honored and
asserting results are pinned to the podcast source (no newsletter leakage).

No network: search_podcasts is mocked. Verifies the gate dispatches by case mode,
threads the podcast slug, and computes retrieval-only scores.
"""

from unittest.mock import AsyncMock, patch

from rag.evaluation import gate
from rag.evaluation.gate import CASE_MODE_SEARCH_PODCASTS


def _podcast_citations():
    return [
        {"source_type": "podcast", "source_title": "LangTalks Ep 1", "snippet": "about MCP", "source_date_start": "2026-03-05", "source_date_end": "2026-03-05", "metadata": {}, "chunk_id": "c1"},
    ]


class TestSearchPodcastsRoute:
    async def test_routes_search_case_through_search_podcasts(self):
        case = {
            "test_id": "podcast_search_001",
            "query": "What did the podcast cover about MCP?",
            "mode": CASE_MODE_SEARCH_PODCASTS,
            "podcast": "langtalks",
            "expected_topics": ["MCP"],
        }
        fake = AsyncMock(return_value={"citations": _podcast_citations(), "date_filter": {"date_start": None, "date_end": None}})
        with patch.object(gate, "search_podcasts", fake), patch.object(gate, "rag_query", AsyncMock(side_effect=AssertionError("search case must not call rag_query"))):
            result = await gate._run_case(case)

        # Slug threaded through.
        assert fake.call_args.kwargs["podcast"] == "langtalks"
        # Retrieval-only recall computed and non-empty.
        assert result.scores["retrieval_recall_at_5"] == 1.0

    async def test_asserts_sources_pinned_to_podcast(self):
        case = {
            "test_id": "podcast_search_pin",
            "query": "MCP",
            "mode": CASE_MODE_SEARCH_PODCASTS,
            "expected_topics": ["MCP"],
        }
        leaked = _podcast_citations() + [{"source_type": "newsletter", "snippet": "leak", "metadata": {}}]
        with patch.object(gate, "search_podcasts", AsyncMock(return_value={"citations": leaked, "date_filter": {}})):
            result = await gate._run_case(case)
        # A newsletter citation on the podcast surface fails the pinned-source metric.
        assert result.scores[gate.METRIC_PODCAST_SOURCE_PINNED] == 0.0

    async def test_pinned_metric_passes_when_all_podcast(self):
        case = {
            "test_id": "podcast_search_pin_ok",
            "query": "MCP",
            "mode": CASE_MODE_SEARCH_PODCASTS,
            "expected_topics": ["MCP"],
        }
        with patch.object(gate, "search_podcasts", AsyncMock(return_value={"citations": _podcast_citations(), "date_filter": {}})):
            result = await gate._run_case(case)
        assert result.scores[gate.METRIC_PODCAST_SOURCE_PINNED] == 1.0
