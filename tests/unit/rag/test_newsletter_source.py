"""
Unit tests for NewsletterSource.

Tests version selection priority, error handling, metadata extraction.
All DB dependencies are mocked.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from constants import ContentSourceType, NewsletterVersionType
from custom_types.field_keys import DbFieldKeys, NewsletterStructureKeys


def _make_newsletter_doc(
    newsletter_id: str = "nl-001",
    data_source_name: str = "langtalks",
    start_date: str = "2025-03-01",
    end_date: str = "2025-03-14",
    chat_name: str | None = "LangTalks Community",
    desired_language: str = "hebrew",
    newsletter_type: str = "per_chat",
    translated_markdown: str | None = None,
    enriched_markdown: str | None = None,
    original_markdown: str | None = None,
) -> dict:
    """Build a mock newsletter document matching MongoDB schema."""
    versions = {}
    if original_markdown is not None:
        versions[str(NewsletterVersionType.ORIGINAL)] = {
            NewsletterStructureKeys.MARKDOWN_CONTENT: original_markdown,
        }
    if enriched_markdown is not None:
        versions[str(NewsletterVersionType.ENRICHED)] = {
            NewsletterStructureKeys.MARKDOWN_CONTENT: enriched_markdown,
        }
    if translated_markdown is not None:
        versions[str(NewsletterVersionType.TRANSLATED)] = {
            NewsletterStructureKeys.MARKDOWN_CONTENT: translated_markdown,
        }

    return {
        DbFieldKeys.NEWSLETTER_ID: newsletter_id,
        DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
        DbFieldKeys.START_DATE: start_date,
        DbFieldKeys.END_DATE: end_date,
        DbFieldKeys.CHAT_NAME: chat_name,
        DbFieldKeys.DESIRED_LANGUAGE: desired_language,
        DbFieldKeys.NEWSLETTER_TYPE: newsletter_type,
        DbFieldKeys.VERSIONS: versions,
    }


@pytest.fixture
def mock_db_and_repo():
    """Patch get_database and NewslettersRepository for NewsletterSource."""
    mock_repo = AsyncMock()

    with patch("rag.sources.newsletter_source.get_database", new_callable=AsyncMock) as mock_get_db, \
         patch("rag.sources.newsletter_source.NewslettersRepository", return_value=mock_repo), \
         patch("rag.sources.newsletter_source.get_settings") as mock_settings:
        mock_get_db.return_value = MagicMock()
        mock_settings.return_value.rag.newsletter_chunk_size = 1500
        mock_settings.return_value.rag.newsletter_chunk_overlap = 300
        yield mock_repo


class TestNewsletterSource:
    """Tests for NewsletterSource."""

    async def test_extract_selects_translated_version_first(self, mock_db_and_repo):
        """When translated version exists, it should be selected over enriched/original."""
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=_make_newsletter_doc(
            translated_markdown="## Translated Section\n\nTranslated content.",
            enriched_markdown="## Enriched Section\n\nEnriched content.",
            original_markdown="## Original Section\n\nOriginal content.",
        ))

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()
        chunks = await source.extract("nl-001")

        assert len(chunks) >= 1
        assert "Translated" in chunks[0].content
        assert chunks[0].metadata["version_used"] == str(NewsletterVersionType.TRANSLATED)

    async def test_extract_falls_back_to_enriched(self, mock_db_and_repo):
        """When no translated version, enriched should be used."""
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=_make_newsletter_doc(
            translated_markdown=None,
            enriched_markdown="## Enriched Section\n\nEnriched content.",
            original_markdown="## Original Section\n\nOriginal content.",
        ))

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()
        chunks = await source.extract("nl-001")

        assert "Enriched" in chunks[0].content
        assert chunks[0].metadata["version_used"] == str(NewsletterVersionType.ENRICHED)

    async def test_extract_falls_back_to_original(self, mock_db_and_repo):
        """When no translated or enriched, original should be used."""
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=_make_newsletter_doc(
            translated_markdown=None,
            enriched_markdown=None,
            original_markdown="## Original Section\n\nOriginal content.",
        ))

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()
        chunks = await source.extract("nl-001")

        assert "Original" in chunks[0].content
        assert chunks[0].metadata["version_used"] == str(NewsletterVersionType.ORIGINAL)

    async def test_extract_raises_when_newsletter_not_found(self, mock_db_and_repo):
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=None)

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()

        with pytest.raises(ValueError, match="Newsletter not found"):
            await source.extract("nonexistent-id")

    async def test_extract_raises_when_no_markdown(self, mock_db_and_repo):
        """Newsletter exists but no version has markdown content."""
        doc = _make_newsletter_doc()
        doc[DbFieldKeys.VERSIONS] = {
            str(NewsletterVersionType.ORIGINAL): {NewsletterStructureKeys.MARKDOWN_CONTENT: None},
        }
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=doc)

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()

        with pytest.raises(ValueError, match="No markdown content"):
            await source.extract("nl-001")

    async def test_extract_raises_when_versions_empty(self, mock_db_and_repo):
        """Newsletter exists but versions dict is empty."""
        doc = _make_newsletter_doc()
        doc[DbFieldKeys.VERSIONS] = {}
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=doc)

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()

        with pytest.raises(ValueError, match="No markdown content"):
            await source.extract("nl-001")

    async def test_extract_returns_correct_chunk_fields(self, mock_db_and_repo):
        mock_db_and_repo.get_newsletter = AsyncMock(return_value=_make_newsletter_doc(
            original_markdown="## Discussion\n\nSome interesting content about AI agents.",
        ))

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()
        chunks = await source.extract("nl-001")

        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.content_source == ContentSourceType.NEWSLETTER
        assert chunk.source_id == "nl-001"
        assert "langtalks" in chunk.source_title.lower() or "Langtalks" in chunk.source_title
        assert chunk.metadata["newsletter_date_range"] == "2025-03-01 to 2025-03-14"
        assert chunk.metadata["data_source_name"] == "langtalks"
        assert chunk.metadata["language"] == "hebrew"
        assert chunk.metadata["newsletter_type"] == "per_chat"
        assert "chat_names_covered" in chunk.metadata

    async def test_list_sources_returns_metadata(self, mock_db_and_repo):
        mock_db_and_repo.get_recent_newsletters = AsyncMock(return_value=[
            _make_newsletter_doc(newsletter_id="nl-001"),
            _make_newsletter_doc(newsletter_id="nl-002", start_date="2025-03-15", end_date="2025-03-28"),
        ])

        from rag.sources.newsletter_source import NewsletterSource
        source = NewsletterSource()
        sources = await source.list_sources()

        assert len(sources) == 2
        assert sources[0]["source_id"] == "nl-001"
        assert sources[1]["source_id"] == "nl-002"
        assert "title" in sources[0]
        assert "data_source_name" in sources[0]
        assert "start_date" in sources[0]
        assert "end_date" in sources[0]

    def test_build_source_title_with_chat_name(self):
        from rag.sources.newsletter_source import NewsletterSource
        title = NewsletterSource._build_source_title(
            data_source_name="langtalks",
            start_date="2025-03-01",
            end_date="2025-03-14",
            chat_name="LangTalks Community",
        )
        assert "Langtalks" in title
        assert "Newsletter" in title
        assert "LangTalks Community" in title
        assert "2025-03-01" in title
        assert "2025-03-14" in title

    def test_build_source_title_without_chat_name(self):
        from rag.sources.newsletter_source import NewsletterSource
        title = NewsletterSource._build_source_title(
            data_source_name="mcp_israel",
            start_date="2025-03-01",
            end_date="2025-03-14",
            chat_name=None,
        )
        assert "Mcp Israel" in title
        assert "Newsletter" in title
        assert "2025-03-01" in title
