"""search_podcasts contract tests.

  - pins retrieval to podcast content only (newsletters never served).
  - threads the optional `podcast` slug into the retrieval podcast_slug filter.
  - never generates (search-only, $0 generation).
Runs WITHOUT Docker (stubbed pipeline).
"""

from unittest.mock import AsyncMock, patch

from constants import ContentSourceType
from rag.mcp import tools as mcp_tools


def _stub(monkeypatch, captured: dict):
    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "__init__", lambda self: None)

    async def _fake_retrieve(self, *args, **kwargs):
        captured.update(kwargs)
        return {
            "context": "ctx",
            "citations": [{"index": 0}],
            "freshness_warning": False,
            "oldest_source_date": None,
            "newest_source_date": None,
        }

    monkeypatch.setattr(mcp_tools.RetrievalPipeline, "retrieve", _fake_retrieve)
    monkeypatch.setattr(mcp_tools, "create_rag_trace", lambda **kw: (None, "t-1"))
    monkeypatch.setattr(mcp_tools, "flush_langfuse", lambda: None)


class TestSearchPodcasts:
    async def test_pins_sources_to_podcast(self, monkeypatch):
        captured: dict = {}
        _stub(monkeypatch, captured)
        await mcp_tools.search_podcasts(query="mcp security")
        assert captured["content_sources"] == [str(ContentSourceType.PODCAST)]

    async def test_threads_podcast_slug(self, monkeypatch):
        captured: dict = {}
        _stub(monkeypatch, captured)
        await mcp_tools.search_podcasts(query="q", podcast="langtalks")
        assert captured["podcast_slug"] == "langtalks"

    async def test_omitted_podcast_searches_all(self, monkeypatch):
        captured: dict = {}
        _stub(monkeypatch, captured)
        await mcp_tools.search_podcasts(query="q")
        assert captured["podcast_slug"] is None

    async def test_never_generates(self, monkeypatch):
        captured: dict = {}
        _stub(monkeypatch, captured)
        with patch.object(mcp_tools, "generate_answer", AsyncMock(side_effect=AssertionError("must not generate"))):
            result = await mcp_tools.search_podcasts(query="q")
        assert "answer" not in result
        assert "citations" in result
