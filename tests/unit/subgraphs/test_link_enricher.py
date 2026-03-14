"""
Unit tests for link_enricher subgraph.

Test Coverage:
- Helper functions: URL extraction, deduplication, markdown conversion, loading
- Node functions: extract_links_from_messages, search_web_for_topics, aggregate_links, insert_links
- Graph construction and compilation

NOTE: Tests require Docker environment due to import dependencies.
Run in Docker: docker compose exec backend pytest tests/unit/subgraphs/test_link_enricher.py
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from tests.unit.subgraphs.conftest import requires_docker


# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================

@requires_docker
class TestExtractUrlsFromText:
    """Test URL extraction helper function."""

    def test_extract_http_url(self):
        """Test extraction of http:// URLs."""
        from graphs.subgraphs.link_enricher import extract_urls_from_text

        text = "Check out this link: http://example.com/page"
        urls = extract_urls_from_text(text)

        assert len(urls) == 1
        assert urls[0] == "http://example.com/page"

    def test_extract_https_url(self):
        """Test extraction of https:// URLs."""
        from graphs.subgraphs.link_enricher import extract_urls_from_text

        text = "Visit https://github.com/user/repo"
        urls = extract_urls_from_text(text)

        assert len(urls) == 1
        assert urls[0] == "https://github.com/user/repo"

    def test_extract_www_url_normalized(self):
        """Test that www. URLs are normalized to https://."""
        from graphs.subgraphs.link_enricher import extract_urls_from_text

        text = "Check www.example.com for more info"
        urls = extract_urls_from_text(text)

        assert len(urls) == 1
        assert urls[0] == "https://www.example.com"

    def test_extract_multiple_urls(self):
        """Test extraction of multiple URLs from text."""
        from graphs.subgraphs.link_enricher import extract_urls_from_text

        text = """
        Visit https://github.com and also check http://example.com
        More at www.docs.com
        """
        urls = extract_urls_from_text(text)

        assert len(urls) == 3

    def test_extract_no_urls(self):
        """Test text with no URLs returns empty list."""
        from graphs.subgraphs.link_enricher import extract_urls_from_text

        text = "This is plain text without any URLs"
        urls = extract_urls_from_text(text)

        assert urls == []

    def test_extract_url_with_path_and_params(self):
        """Test extraction of complex URLs with paths and parameters."""
        from graphs.subgraphs.link_enricher import extract_urls_from_text

        text = "API docs: https://api.example.com/v1/docs?format=json&lang=en"
        urls = extract_urls_from_text(text)

        assert len(urls) == 1
        assert "api.example.com" in urls[0]


@requires_docker
class TestDeduplicateLinks:
    """Test link deduplication helper function."""

    def test_deduplicate_identical_urls(self):
        """Test removal of identical URLs."""
        from graphs.subgraphs.link_enricher import deduplicate_links

        links = [
            {"url": "https://example.com/page", "source": "web"},
            {"url": "https://example.com/page", "source": "discussion"},
        ]
        result = deduplicate_links(links)

        assert len(result) == 1

    def test_deduplicate_preserves_first_occurrence(self):
        """Test that first occurrence is preserved."""
        from graphs.subgraphs.link_enricher import deduplicate_links

        links = [
            {"url": "https://example.com", "source": "first"},
            {"url": "https://example.com", "source": "second"},
        ]
        result = deduplicate_links(links)

        assert result[0]["source"] == "first"

    def test_deduplicate_normalizes_trailing_slash(self):
        """Test that URLs with/without trailing slash are deduplicated."""
        from graphs.subgraphs.link_enricher import deduplicate_links

        links = [
            {"url": "https://example.com/path/", "source": "one"},
            {"url": "https://example.com/path", "source": "two"},
        ]
        result = deduplicate_links(links)

        assert len(result) == 1

    def test_deduplicate_normalizes_domain_case(self):
        """Test that domain case is normalized."""
        from graphs.subgraphs.link_enricher import deduplicate_links

        links = [
            {"url": "https://EXAMPLE.COM/page", "source": "one"},
            {"url": "https://example.com/page", "source": "two"},
        ]
        result = deduplicate_links(links)

        assert len(result) == 1

    def test_deduplicate_keeps_different_urls(self):
        """Test that different URLs are kept."""
        from graphs.subgraphs.link_enricher import deduplicate_links

        links = [
            {"url": "https://example.com/page1", "source": "one"},
            {"url": "https://example.com/page2", "source": "two"},
        ]
        result = deduplicate_links(links)

        assert len(result) == 2

    def test_deduplicate_handles_empty_url(self):
        """Test that empty URLs are skipped."""
        from graphs.subgraphs.link_enricher import deduplicate_links

        links = [
            {"url": "", "source": "empty"},
            {"url": "https://example.com", "source": "valid"},
        ]
        result = deduplicate_links(links)

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com"


@requires_docker
class TestConvertNewsletterJsonToMarkdown:
    """Test newsletter JSON to Markdown conversion."""

    def test_convert_langtalks_format(self):
        """Test conversion of LangTalks format newsletter."""
        from graphs.subgraphs.link_enricher import convert_newsletter_json_to_markdown

        newsletter = {
            "primary_discussion": {
                "title": "Main Topic",
                "bullet_points": [
                    {"label": "Summary", "content": "This is the main point."},
                    {"label": "Details", "content": "More details here."}
                ]
            },
            "secondary_discussions": [
                {
                    "title": "Secondary Topic",
                    "bullet_points": [
                        {"content": "Secondary content here."}
                    ]
                }
            ],
            "worth_mentioning": [
                "Brief mention 1",
                "Brief mention 2"
            ]
        }

        markdown = convert_newsletter_json_to_markdown(newsletter)

        assert "Main Topic" in markdown
        assert "Summary" in markdown  # Bullet point label
        assert "This is the main point" in markdown
        assert "Secondary Topic" in markdown
        assert "Brief mention 1" in markdown

    def test_convert_mcp_format_uses_markdown_content(self):
        """Test that MCP format uses existing markdown_content field."""
        from graphs.subgraphs.link_enricher import convert_newsletter_json_to_markdown

        newsletter = {
            "markdown_content": "# Pre-rendered MCP Newsletter\n\nContent here."
        }

        markdown = convert_newsletter_json_to_markdown(newsletter)

        assert markdown == "# Pre-rendered MCP Newsletter\n\nContent here."

    def test_convert_empty_newsletter(self):
        """Test conversion of empty newsletter."""
        from graphs.subgraphs.link_enricher import convert_newsletter_json_to_markdown

        newsletter = {
            "primary_discussion": {},
            "secondary_discussions": [],
            "worth_mentioning": []
        }

        markdown = convert_newsletter_json_to_markdown(newsletter)

        # Should produce some output without errors
        assert isinstance(markdown, str)


@requires_docker
class TestLoadDiscussions:
    """Test discussion loading helper function."""

    def test_load_discussions_file_not_found(self):
        """Test that FileNotFoundError is raised for missing file."""
        from graphs.subgraphs.link_enricher import load_discussions

        with pytest.raises(FileNotFoundError):
            load_discussions("/nonexistent/path/discussions.json")

    def test_load_discussions_success(self):
        """Test successful loading of discussions."""
        from graphs.subgraphs.link_enricher import load_discussions

        discussions_data = {
            "discussions": [
                {"id": "disc_1", "title": "Test Discussion"}
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(discussions_data, f)
            temp_path = f.name

        try:
            result = load_discussions(temp_path)
            assert len(result) == 1
            assert result[0]["id"] == "disc_1"
        finally:
            os.unlink(temp_path)


@requires_docker
class TestLoadNewsletter:
    """Test newsletter loading helper function."""

    def test_load_newsletter_file_not_found(self):
        """Test that FileNotFoundError is raised for missing file."""
        from graphs.subgraphs.link_enricher import load_newsletter

        with pytest.raises(FileNotFoundError):
            load_newsletter("/nonexistent/path/newsletter.json")

    def test_load_newsletter_success(self):
        """Test successful loading of newsletter."""
        from graphs.subgraphs.link_enricher import load_newsletter

        newsletter_data = {
            "primary_discussion": {"title": "Test"},
            "secondary_discussions": []
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(newsletter_data, f)
            temp_path = f.name

        try:
            result = load_newsletter(temp_path)
            assert result["primary_discussion"]["title"] == "Test"
        finally:
            os.unlink(temp_path)


# ============================================================================
# NODE FUNCTION TESTS
# ============================================================================

@requires_docker
class TestExtractLinksFromMessagesNode:
    """Test extract_links_from_messages node function."""

    def test_extract_links_from_messages_success(self):
        """Test successful extraction of links from discussion messages."""
        from graphs.subgraphs.link_enricher import extract_links_from_messages

        # Create temp discussions file
        discussions_data = {
            "discussions": [
                {
                    "id": "disc_1",
                    "title": "Test Discussion",
                    "messages": [
                        {"id": "msg_1", "content": "Check out https://example.com for more info"},
                        {"id": "msg_2", "content": "Also see http://docs.example.com/guide"}
                    ]
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(discussions_data, f)
            temp_path = f.name

        try:
            state = {"separate_discussions_file_path": temp_path}
            result = extract_links_from_messages(state)

            assert "extracted_links" in result
            assert len(result["extracted_links"]) == 2
            assert result["extracted_links"][0]["source"] == "discussion_message"
        finally:
            os.unlink(temp_path)

    def test_extract_links_file_not_found_raises(self):
        """Test that missing file raises RuntimeError."""
        from graphs.subgraphs.link_enricher import extract_links_from_messages

        state = {"separate_discussions_file_path": "/nonexistent/file.json"}

        with pytest.raises(RuntimeError):
            extract_links_from_messages(state)


@requires_docker
class TestSearchWebForTopicsNode:
    """Test search_web_for_topics node function."""

    @pytest.mark.asyncio
    @patch('graphs.subgraphs.link_enricher.WebSearchAgent')
    async def test_search_web_graceful_degradation_on_api_error(self, mock_searcher_class):
        """Test graceful degradation when Google API fails."""
        from graphs.subgraphs.link_enricher import search_web_for_topics

        # Simulate API key not configured
        mock_searcher_class.side_effect = ValueError("API key not configured")

        # Create temp discussions file
        discussions_data = {
            "discussions": [
                {"id": "disc_1", "title": "Test", "num_messages": 10}
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(discussions_data, f)
            temp_path = f.name

        try:
            state = {
                "separate_discussions_file_path": temp_path,
                "summary_format": "langtalks_format",
                "extracted_links": [],
            }
            result = await search_web_for_topics(state)

            # Should return empty list, not raise
            assert result == {"searched_links": []}
        finally:
            os.unlink(temp_path)

    @pytest.mark.asyncio
    @patch('graphs.subgraphs.link_enricher.WebSearchAgent')
    async def test_search_web_success(self, mock_searcher_class):
        """Test successful web search."""
        from graphs.subgraphs.link_enricher import search_web_for_topics

        # Mock searcher with async search_for_discussion method
        mock_agent = MagicMock()
        mock_agent.search_for_discussion = AsyncMock(return_value=[
            {"url": "https://result.com", "title": "Result", "snippet": "Description", "source": "web_search"}
        ])
        mock_searcher_class.return_value = mock_agent

        # Create temp discussions file
        discussions_data = {
            "discussions": [
                {"id": "disc_1", "title": "LangChain Tutorial", "nutshell": "Learning about LangChain", "num_messages": 10}
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(discussions_data, f)
            temp_path = f.name

        try:
            state = {
                "separate_discussions_file_path": temp_path,
                "summary_format": "langtalks_format",
                "extracted_links": [],
            }
            result = await search_web_for_topics(state)

            assert "searched_links" in result
            assert len(result["searched_links"]) > 0
            assert result["searched_links"][0]["source"] == "web_search"
        finally:
            os.unlink(temp_path)


@requires_docker
class TestAggregateLinksNode:
    """Test aggregate_links node function."""

    def test_aggregate_links_success(self):
        """Test successful aggregation and deduplication."""
        from graphs.subgraphs.link_enricher import aggregate_links

        with tempfile.TemporaryDirectory() as temp_dir:
            state = {
                "extracted_links": [
                    {"url": "https://example.com/page1", "source": "message"},
                    {"url": "https://example.com/page2", "source": "message"}
                ],
                "searched_links": [
                    {"url": "https://example.com/page1", "source": "web"},  # Duplicate
                    {"url": "https://docs.com", "source": "web"}
                ],
                "link_enrichment_dir": temp_dir
            }

            result = aggregate_links(state)

            assert "aggregated_links_file_path" in result
            assert result["num_links_extracted"] == 2
            assert result["num_links_searched"] == 2
            assert os.path.exists(result["aggregated_links_file_path"])

            # Verify deduplication
            with open(result["aggregated_links_file_path"], 'r') as f:
                data = json.load(f)
                # Should have 3 unique links (one duplicate removed)
                assert data["count"] == 3


@requires_docker
class TestInsertLinksIntoContentNode:
    """Test insert_links_into_content node function."""

    @pytest.mark.asyncio
    async def test_mcp_format_copies_newsletter(self):
        """Test that MCP format copies newsletter without LLM enrichment."""
        from graphs.subgraphs.link_enricher import insert_links_into_content

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create newsletter file
            newsletter_data = {
                "markdown_content": "# MCP Newsletter",
                "primary_discussion": {"title": "Test"}
            }
            newsletter_path = os.path.join(temp_dir, "newsletter.json")
            with open(newsletter_path, 'w') as f:
                json.dump(newsletter_data, f)

            # Create empty aggregated links file
            links_path = os.path.join(temp_dir, "links.json")
            with open(links_path, 'w') as f:
                json.dump({"links": []}, f)

            enriched_json = os.path.join(temp_dir, "enriched.json")
            enriched_md = os.path.join(temp_dir, "enriched.md")

            state = {
                "aggregated_links_file_path": links_path,
                "newsletter_json_path": newsletter_path,
                "expected_enriched_newsletter_json": enriched_json,
                "expected_enriched_newsletter_md": enriched_md,
                "summary_format": "mcp_israel_format"
            }

            result = await insert_links_into_content(state)

            assert result["num_links_inserted"] == 0
            assert os.path.exists(enriched_json)

    @pytest.mark.asyncio
    async def test_no_links_available_copies_newsletter(self):
        """Test that empty links list copies newsletter unchanged."""
        from graphs.subgraphs.link_enricher import insert_links_into_content

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create newsletter file
            newsletter_data = {
                "primary_discussion": {"title": "Test", "bullet_points": []},
                "secondary_discussions": [],
                "worth_mentioning": []
            }
            newsletter_path = os.path.join(temp_dir, "newsletter.json")
            with open(newsletter_path, 'w') as f:
                json.dump(newsletter_data, f)

            # Create empty aggregated links file
            links_path = os.path.join(temp_dir, "links.json")
            with open(links_path, 'w') as f:
                json.dump({"links": []}, f)

            enriched_json = os.path.join(temp_dir, "enriched.json")
            enriched_md = os.path.join(temp_dir, "enriched.md")

            state = {
                "aggregated_links_file_path": links_path,
                "newsletter_json_path": newsletter_path,
                "expected_enriched_newsletter_json": enriched_json,
                "expected_enriched_newsletter_md": enriched_md,
                "summary_format": "langtalks_format"
            }

            result = await insert_links_into_content(state)

            assert result["num_links_inserted"] == 0


# ============================================================================
# GRAPH CONSTRUCTION TESTS
# ============================================================================

@requires_docker
class TestBuildLinkEnricherGraph:
    """Test link enricher graph construction."""

    def test_build_graph_compiles_successfully(self):
        """Test that graph builds and compiles without errors."""
        from graphs.subgraphs.link_enricher import build_link_enricher_graph

        graph = build_link_enricher_graph()

        assert graph is not None
        # Verify it has the expected nodes
        assert hasattr(graph, 'invoke')

    def test_exported_graph_exists(self):
        """Test that the exported graph is available."""
        from graphs.subgraphs.link_enricher import link_enricher_graph

        assert link_enricher_graph is not None
