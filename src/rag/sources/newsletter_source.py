"""
Newsletter Content Source

Implements ContentSourceInterface for newsletters stored in MongoDB.
Reads from the existing `newsletters` collection, chunks markdown content
via MarkdownChunker, and returns ContentChunk list for the ingestion pipeline.
"""

import logging
from typing import Any

from config import get_settings
from constants import ContentSourceType, NewsletterVersionType, FileFormat, NewsletterStatus
from custom_types.field_keys import DbFieldKeys, NewsletterStructureKeys
from db.connection import get_database
from db.repositories.newsletters import NewslettersRepository
from rag.chunking.markdown_chunker import MarkdownChunker
from rag.sources.base import ContentChunk, ContentSourceInterface

logger = logging.getLogger(__name__)

# Version selection priority: best available version for chunking
_VERSION_PRIORITY = [
    NewsletterVersionType.TRANSLATED,
    NewsletterVersionType.ENRICHED,
    NewsletterVersionType.ORIGINAL,
]


class NewsletterSource(ContentSourceInterface):
    """
    Content source for newsletters stored in MongoDB.

    Flow:
    1. Reads newsletter from `newsletters` collection
    2. Selects best available version (translated > enriched > original)
    3. Gets markdown content (most structured for chunking)
    4. Chunks via MarkdownChunker (section-aware)
    5. Returns ContentChunk list with newsletter metadata
    """

    source_type = ContentSourceType.NEWSLETTER

    def __init__(self) -> None:
        settings = get_settings().rag
        self._chunker = MarkdownChunker(
            chunk_size=settings.newsletter_chunk_size,
            chunk_overlap=settings.newsletter_chunk_overlap,
        )

    async def extract(self, source_id: str, **kwargs) -> list[ContentChunk]:
        """
        Extract and chunk a newsletter from MongoDB.

        Args:
            source_id: Newsletter ID (newsletter_id field in MongoDB)
            **kwargs: Not used

        Returns:
            List of ContentChunk instances

        Raises:
            ValueError: If newsletter not found or has no markdown content
        """
        db = await get_database()
        repo = NewslettersRepository(db)

        newsletter = await repo.get_newsletter(source_id)
        if not newsletter:
            raise ValueError(f"Newsletter not found: {source_id}")

        # Select best available version and get markdown
        markdown_content, version_used = self._get_best_markdown(newsletter)
        if not markdown_content:
            raise ValueError(
                f"No markdown content available for newsletter {source_id}. "
                f"Checked versions: {[str(v) for v in _VERSION_PRIORITY]}"
            )

        # Build metadata
        data_source_name = newsletter.get(DbFieldKeys.DATA_SOURCE_NAME, "")
        start_date = newsletter.get(DbFieldKeys.START_DATE, "")
        end_date = newsletter.get(DbFieldKeys.END_DATE, "")
        chat_name = newsletter.get(DbFieldKeys.CHAT_NAME)
        desired_language = newsletter.get(DbFieldKeys.DESIRED_LANGUAGE, "")

        source_title = self._build_source_title(data_source_name, start_date, end_date, chat_name)

        chunk_metadata = {
            "newsletter_date_range": f"{start_date} to {end_date}",
            "data_source_name": data_source_name,
            "chat_names_covered": [chat_name] if chat_name else [],
            "language": desired_language,
            "version_used": str(version_used),
            "newsletter_type": newsletter.get(DbFieldKeys.NEWSLETTER_TYPE, ""),
        }

        chunks = self._chunker.chunk(
            content=markdown_content,
            source_id=source_id,
            source_title=source_title,
            metadata=chunk_metadata,
        )

        logger.info(
            f"Newsletter extraction complete: {source_id} -> {len(chunks)} chunks "
            f"(version={version_used})"
        )
        return chunks

    async def list_sources(self) -> list[dict]:
        """
        List all available newsletters with metadata.

        Returns:
            List of dicts with source_id, title, date range, data_source_name, language
        """
        db = await get_database()
        repo = NewslettersRepository(db)

        newsletters = await repo.get_recent_newsletters(
            limit=100,
            status=str(NewsletterStatus.COMPLETED),
        )

        sources = []
        for nl in newsletters:
            newsletter_id = nl.get(DbFieldKeys.NEWSLETTER_ID, "")
            data_source_name = nl.get(DbFieldKeys.DATA_SOURCE_NAME, "")
            start_date = nl.get(DbFieldKeys.START_DATE, "")
            end_date = nl.get(DbFieldKeys.END_DATE, "")
            chat_name = nl.get(DbFieldKeys.CHAT_NAME)

            sources.append({
                "source_id": newsletter_id,
                "title": self._build_source_title(data_source_name, start_date, end_date, chat_name),
                "data_source_name": data_source_name,
                "start_date": start_date,
                "end_date": end_date,
                "chat_name": chat_name,
                "newsletter_type": nl.get(DbFieldKeys.NEWSLETTER_TYPE, ""),
                "language": nl.get(DbFieldKeys.DESIRED_LANGUAGE, ""),
                "status": nl.get(DbFieldKeys.STATUS, ""),
            })

        return sources

    async def get_source_metadata(self, source_id: str) -> dict:
        """
        Get metadata for a specific newsletter.

        Args:
            source_id: Newsletter ID

        Returns:
            Newsletter metadata dict
        """
        db = await get_database()
        repo = NewslettersRepository(db)

        newsletter = await repo.get_newsletter(source_id)
        if not newsletter:
            return {}

        return {
            "source_id": source_id,
            "title": self._build_source_title(
                newsletter.get(DbFieldKeys.DATA_SOURCE_NAME, ""),
                newsletter.get(DbFieldKeys.START_DATE, ""),
                newsletter.get(DbFieldKeys.END_DATE, ""),
                newsletter.get(DbFieldKeys.CHAT_NAME),
            ),
            "data_source_name": newsletter.get(DbFieldKeys.DATA_SOURCE_NAME, ""),
            "start_date": newsletter.get(DbFieldKeys.START_DATE, ""),
            "end_date": newsletter.get(DbFieldKeys.END_DATE, ""),
            "chat_name": newsletter.get(DbFieldKeys.CHAT_NAME),
            "newsletter_type": newsletter.get(DbFieldKeys.NEWSLETTER_TYPE, ""),
            "language": newsletter.get(DbFieldKeys.DESIRED_LANGUAGE, ""),
            "status": newsletter.get(DbFieldKeys.STATUS, ""),
        }

    async def list_sources_filtered(
        self,
        data_source_name: str | None = None,
        limit: int = 10,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List newsletters with filtering for the ingestion endpoint.

        Args:
            data_source_name: Filter by community
            limit: Maximum newsletters to return
            start_date: Filter by start date (inclusive)
            end_date: Filter by end date (inclusive)

        Returns:
            List of newsletter metadata dicts with source_id
        """
        db = await get_database()
        repo = NewslettersRepository(db)

        newsletters = await repo.get_recent_newsletters(
            limit=limit,
            data_source_name=data_source_name,
            status=str(NewsletterStatus.COMPLETED),
        )

        # Apply date filtering if specified
        filtered = []
        for nl in newsletters:
            nl_start = nl.get(DbFieldKeys.START_DATE, "")
            nl_end = nl.get(DbFieldKeys.END_DATE, "")

            if start_date and nl_end < start_date:
                continue
            if end_date and nl_start > end_date:
                continue

            filtered.append({
                "source_id": nl.get(DbFieldKeys.NEWSLETTER_ID, ""),
                "data_source_name": nl.get(DbFieldKeys.DATA_SOURCE_NAME, ""),
                "start_date": nl_start,
                "end_date": nl_end,
                "newsletter_type": nl.get(DbFieldKeys.NEWSLETTER_TYPE, ""),
            })

        return filtered

    @staticmethod
    def _get_best_markdown(newsletter: dict) -> tuple[str | None, str]:
        """
        Get the best available markdown content from a newsletter document.

        Tries versions in priority order: translated > enriched > original.

        Returns:
            Tuple of (markdown_content, version_type_used)
        """
        versions = newsletter.get(DbFieldKeys.VERSIONS, {})

        for version_type in _VERSION_PRIORITY:
            version_data = versions.get(str(version_type))
            if not version_data:
                continue

            markdown = version_data.get(NewsletterStructureKeys.MARKDOWN_CONTENT)
            if markdown:
                return markdown, str(version_type)

        return None, ""

    @staticmethod
    def _build_source_title(
        data_source_name: str,
        start_date: str,
        end_date: str,
        chat_name: str | None,
    ) -> str:
        """Build a human-readable source title for a newsletter."""
        parts = [data_source_name.replace("_", " ").title(), "Newsletter"]
        if chat_name:
            parts.append(f"({chat_name})")
        if start_date and end_date:
            parts.append(f": {start_date} to {end_date}")
        return " ".join(parts)
