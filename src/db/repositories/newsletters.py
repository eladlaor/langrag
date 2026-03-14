"""
Newsletters Repository

Manages persisted newsletter records for future use as examples.
Stores all versions (original, enriched, translated) with metadata.
"""

import json
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_NEWSLETTERS, FileFormat, NewsletterStatus, NewsletterVersionType, FILE_EXT_JSON, FILE_EXT_MD, FILE_EXT_HTML
from custom_types.field_keys import DbFieldKeys, NewsletterStructureKeys, ContentResultKeys

logger = logging.getLogger(__name__)

# Type aliases for clarity
VersionType = NewsletterVersionType
FormatType = FileFormat


class NewslettersRepository(BaseRepository):
    """
    Repository for newsletter storage and retrieval.

    Stores:
    - All newsletter versions (original, enriched, translated)
    - Newsletter metadata (format, language, date range)
    - Statistics (discussion counts, word counts)
    - File path references
    - Quality scores
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, COLLECTION_NEWSLETTERS)

    async def create_newsletter(
        self,
        newsletter_id: str,
        run_id: str,
        newsletter_type: str,
        data_source_name: str,
        start_date: str,
        end_date: str,
        summary_format: str,
        desired_language: str,
        original_json: dict,
        original_markdown: str,
        original_html: str | None = None,
        file_paths: dict | None = None,
        chat_name: str | None = None,
        stats: dict | None = None,
        featured_discussion_ids: list[str] | None = None,
    ) -> str:
        """
        Create a new newsletter record with original version.

        Args:
            newsletter_id: Unique identifier (format: {run_id}_nl_{chat_slug})
            run_id: Associated pipeline run ID
            newsletter_type: "per_chat" or "consolidated"
            data_source_name: Data source (e.g., "langtalks")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            summary_format: Newsletter format identifier
            desired_language: Target language
            original_json: Structured newsletter content
            original_markdown: Rendered markdown
            original_html: Rendered HTML (optional)
            file_paths: Dictionary of file paths
            chat_name: Source chat name (None for consolidated)
            stats: Statistics dictionary
            featured_discussion_ids: List of featured discussion IDs

        Returns:
            Inserted document ID
        """
        try:
            now = datetime.now(UTC)

            document = {
                DbFieldKeys.NEWSLETTER_ID: newsletter_id,
                DbFieldKeys.RUN_ID: run_id,
                DbFieldKeys.NEWSLETTER_TYPE: newsletter_type,
                DbFieldKeys.DATA_SOURCE_NAME: data_source_name,
                DbFieldKeys.CHAT_NAME: chat_name,
                DbFieldKeys.START_DATE: start_date,
                DbFieldKeys.END_DATE: end_date,
                DbFieldKeys.SUMMARY_FORMAT: summary_format,
                DbFieldKeys.DESIRED_LANGUAGE: desired_language,
                DbFieldKeys.VERSIONS: {NewsletterVersionType.ORIGINAL: {DbFieldKeys.JSON_CONTENT: original_json, NewsletterStructureKeys.MARKDOWN_CONTENT: original_markdown, DbFieldKeys.HTML_CONTENT: original_html, DbFieldKeys.CREATED_AT: now, DbFieldKeys.FILE_PATHS: file_paths or {}}, NewsletterVersionType.ENRICHED: None, NewsletterVersionType.TRANSLATED: None},
                DbFieldKeys.STATS: stats or {},
                DbFieldKeys.FEATURED_DISCUSSION_IDS: featured_discussion_ids or [],
                DbFieldKeys.BRIEF_MENTION_DISCUSSION_IDS: [],
                DbFieldKeys.QUALITY_SCORES: None,
                DbFieldKeys.CREATED_AT: now,
                DbFieldKeys.UPDATED_AT: now,
                DbFieldKeys.COMPLETED_AT: None,
                DbFieldKeys.STATUS: NewsletterStatus.DRAFT,
            }

            result_id = await self.create(document)
            logger.info(f"Created newsletter: {newsletter_id} (type={newsletter_type})")
            return result_id

        except Exception as e:
            logger.error(f"Failed to create newsletter {newsletter_id}: {e}")
            raise

    async def add_enriched_version(self, newsletter_id: str, enriched_json: dict, enriched_markdown: str, enriched_html: str | None = None, file_paths: dict | None = None, links_added: int = 0) -> bool:
        """
        Add enriched version to existing newsletter.

        Args:
            newsletter_id: Newsletter identifier
            enriched_json: Enriched JSON content
            enriched_markdown: Enriched markdown
            enriched_html: Enriched HTML (optional)
            file_paths: File path references
            links_added: Number of links added during enrichment

        Returns:
            True if updated successfully
        """
        try:
            now = datetime.now(UTC)

            enriched_version = {
                DbFieldKeys.JSON_CONTENT: enriched_json,
                NewsletterStructureKeys.MARKDOWN_CONTENT: enriched_markdown,
                DbFieldKeys.HTML_CONTENT: enriched_html,
                DbFieldKeys.CREATED_AT: now,
                ContentResultKeys.LINKS_ADDED: links_added,
                DbFieldKeys.FILE_PATHS: file_paths or {},
            }
            update_result = await self.update_one(
                {DbFieldKeys.NEWSLETTER_ID: newsletter_id},
                {"$set": {f"{DbFieldKeys.VERSIONS}.{NewsletterVersionType.ENRICHED}": enriched_version, DbFieldKeys.UPDATED_AT: now, DbFieldKeys.STATUS: NewsletterStatus.ENRICHED}},
            )

            if update_result:
                logger.info(f"Added enriched version to newsletter: {newsletter_id}")
            return update_result

        except Exception as e:
            logger.error(f"Failed to add enriched version to {newsletter_id}: {e}")
            raise

    async def add_translated_version(self, newsletter_id: str, translated_markdown: str, target_language: str, file_paths: dict | None = None) -> bool:
        """
        Add translated version to existing newsletter.

        Args:
            newsletter_id: Newsletter identifier
            translated_markdown: Translated markdown content
            target_language: Target language
            file_paths: File path references

        Returns:
            True if updated successfully
        """
        try:
            now = datetime.now(UTC)

            update_result = await self.update_one({DbFieldKeys.NEWSLETTER_ID: newsletter_id}, {"$set": {f"{DbFieldKeys.VERSIONS}.{NewsletterVersionType.TRANSLATED}": {NewsletterStructureKeys.MARKDOWN_CONTENT: translated_markdown, DbFieldKeys.CREATED_AT: now, DbFieldKeys.TARGET_LANGUAGE: target_language, DbFieldKeys.FILE_PATHS: file_paths or {}}, DbFieldKeys.UPDATED_AT: now, DbFieldKeys.COMPLETED_AT: now, DbFieldKeys.STATUS: NewsletterStatus.COMPLETED}})

            if update_result:
                logger.info(f"Added translated version to newsletter: {newsletter_id}")
            return update_result

        except Exception as e:
            logger.error(f"Failed to add translated version to {newsletter_id}: {e}")
            raise

    async def mark_completed(self, newsletter_id: str) -> bool:
        """Mark newsletter as completed (all versions finalized)."""
        try:
            return await self.update_one({DbFieldKeys.NEWSLETTER_ID: newsletter_id}, {"$set": {DbFieldKeys.COMPLETED_AT: datetime.now(UTC), DbFieldKeys.STATUS: NewsletterStatus.COMPLETED}})
        except Exception as e:
            logger.error(f"Failed to mark newsletter {newsletter_id} as completed: {e}")
            raise

    async def get_newsletter(self, newsletter_id: str) -> dict[str, Any] | None:
        """Get a newsletter by its ID."""
        try:
            return await self.find_by_id(DbFieldKeys.NEWSLETTER_ID, newsletter_id)
        except Exception as e:
            logger.error(f"Failed to get newsletter {newsletter_id}: {e}")
            raise

    async def get_newsletters_by_run(self, run_id: str, newsletter_type: str | None = None) -> list[dict[str, Any]]:
        """
        Get all newsletters for a specific run.

        Args:
            run_id: Run identifier
            newsletter_type: Filter by type ("per_chat" | "consolidated")

        Returns:
            List of newsletter documents
        """
        try:
            query = {DbFieldKeys.RUN_ID: run_id}
            if newsletter_type:
                query[DbFieldKeys.NEWSLETTER_TYPE] = newsletter_type

            return await self.find_many(query, sort=[("created_at", -1)])
        except Exception as e:
            logger.error(f"Failed to get newsletters for run {run_id}: {e}")
            raise

    async def get_recent_newsletters(self, limit: int = 10, data_source_name: str | None = None, summary_format: str | None = None, newsletter_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """
        Get recent newsletters with optional filtering.

        Args:
            limit: Maximum newsletters to return
            data_source_name: Filter by data source
            summary_format: Filter by format
            newsletter_type: Filter by type
            status: Filter by status

        Returns:
            List of newsletter documents (newest first)
        """
        try:
            query = {}
            if data_source_name:
                query[DbFieldKeys.DATA_SOURCE_NAME] = data_source_name
            if summary_format:
                query[DbFieldKeys.SUMMARY_FORMAT] = summary_format
            if newsletter_type:
                query[DbFieldKeys.NEWSLETTER_TYPE] = newsletter_type
            if status:
                query[DbFieldKeys.STATUS] = status

            return await self.find_many(query, sort=[("created_at", -1)], limit=limit)
        except Exception as e:
            logger.error(f"Failed to get recent newsletters: {e}")
            raise

    async def search_similar_newsletters(self, data_source_name: str, summary_format: str, start_date: str, end_date: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Find similar newsletters by data source, format, and date range.

        Useful for finding examples for LLM context.

        Args:
            data_source_name: Data source to match
            summary_format: Format to match
            start_date: Start date to search around
            end_date: End date to search around
            limit: Maximum results

        Returns:
            List of similar newsletters (most recent first)
        """
        try:
            query = {DbFieldKeys.DATA_SOURCE_NAME: data_source_name, DbFieldKeys.SUMMARY_FORMAT: summary_format, DbFieldKeys.STATUS: NewsletterStatus.COMPLETED}

            return await self.find_many(query, sort=[("created_at", -1)], limit=limit)
        except Exception as e:
            logger.error(f"Failed to search similar newsletters: {e}")
            raise

    async def update_quality_scores(self, newsletter_id: str, scores: dict) -> bool:
        """
        Update quality evaluation scores.

        Args:
            newsletter_id: Newsletter identifier
            scores: Dictionary of score values

        Returns:
            True if updated successfully
        """
        try:
            return await self.update_one({DbFieldKeys.NEWSLETTER_ID: newsletter_id}, {"$set": {DbFieldKeys.QUALITY_SCORES: {**scores, "evaluated_at": datetime.now(UTC)}, DbFieldKeys.UPDATED_AT: datetime.now(UTC)}})
        except Exception as e:
            logger.error(f"Failed to update quality scores for {newsletter_id}: {e}")
            raise

    async def get_newsletter_content(self, newsletter_id: str, version: VersionType = "original", format: FormatType = "markdown") -> Any | None:
        """
        Retrieve newsletter content from MongoDB by version and format.

        This is the primary method for retrieving newsletter content,
        replacing file-based retrieval.

        Args:
            newsletter_id: Newsletter identifier
            version: Version to retrieve ("original", "enriched", "translated")
            format: Format to retrieve ("json", "markdown", "html")

        Returns:
            Content in requested format, or None if not found

        Examples:
            # Get original markdown
            content = await repo.get_newsletter_content("nl_123", "original", "markdown")

            # Get enriched JSON
            content = await repo.get_newsletter_content("nl_123", "enriched", "json")

            # Get translated markdown
            content = await repo.get_newsletter_content("nl_123", "translated", "markdown")
        """
        try:
            newsletter = await self.get_newsletter(newsletter_id)
            if not newsletter:
                logger.warning(f"Newsletter not found: {newsletter_id}")
                return None

            # Navigate to the requested version
            versions = newsletter.get(DbFieldKeys.VERSIONS, {})
            version_data = versions.get(version)

            if not version_data:
                logger.warning(f"Version '{version}' not found for newsletter {newsletter_id}")
                return None

            # Map format to field name
            format_field_map = {FileFormat.JSON: DbFieldKeys.JSON_CONTENT, FileFormat.MARKDOWN: NewsletterStructureKeys.MARKDOWN_CONTENT, FileFormat.HTML: DbFieldKeys.HTML_CONTENT}

            field_name = format_field_map.get(format)
            if not field_name:
                logger.error(f"Invalid format requested: {format}")
                return None

            content = version_data.get(field_name)

            if content is None:
                logger.warning(f"Content not found for newsletter {newsletter_id}, " f"version={version}, format={format}")
                return None

            logger.debug(f"Retrieved {format} content for newsletter {newsletter_id} " f"(version={version})")
            return content

        except Exception as e:
            logger.error(f"Failed to get content for newsletter {newsletter_id} " f"(version={version}, format={format}): {e}")
            raise

    async def get_recent_newsletters_for_context(self, data_source_name: str, before_date: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get recent newsletters for anti-repetition context.

        This replaces file system scanning with MongoDB queries for the
        anti-repetition system. Returns newsletters ordered by end_date
        descending (most recent first).

        Args:
            data_source_name: Data source to match (e.g., "langtalks")
            before_date: Only return newsletters with end_date < before_date (YYYY-MM-DD)
            limit: Maximum newsletters to return (default: 10)

        Returns:
            List of newsletter documents with only json_content projected
            (not markdown/html for performance)

        Example:
            # Get last 5 newsletters for langtalks before 2025-01-15
            newsletters = await repo.get_recent_newsletters_for_context(
                data_source_name="langtalks",
                before_date="2025-01-15",
                limit=5
            )
            for nl in newsletters:
                topics = nl["versions"]["original"]["json_content"]
        """
        try:
            query = {DbFieldKeys.DATA_SOURCE_NAME: data_source_name, DbFieldKeys.END_DATE: {"$lt": before_date}, DbFieldKeys.STATUS: NewsletterStatus.COMPLETED}

            # Project only necessary fields for performance
            # We only need json_content for topic extraction, not markdown/html
            projection = {
                DbFieldKeys.NEWSLETTER_ID: 1,
                DbFieldKeys.START_DATE: 1,
                DbFieldKeys.END_DATE: 1,
                f"{DbFieldKeys.VERSIONS}.{NewsletterVersionType.ORIGINAL}.{DbFieldKeys.JSON_CONTENT}": 1,
                DbFieldKeys.CREATED_AT: 1,
                "_id": 0,  # Exclude MongoDB _id
            }

            newsletters = await self.find_many(
                query,
                sort=[("end_date", -1)],  # Most recent first
                limit=limit,
                projection=projection,
            )

            logger.info(f"Retrieved {len(newsletters)} newsletters for context " f"(data_source={data_source_name}, before={before_date}, limit={limit})")

            return newsletters

        except Exception as e:
            logger.error(f"Failed to get newsletters for context " f"(data_source={data_source_name}, before={before_date}): {e}")
            raise

    async def generate_file_on_demand(self, newsletter_id: str, version: VersionType = "original", format: FormatType = "markdown", output_path: str | None = None) -> str | None:
        """
        Generate a file from MongoDB content on-demand.

        This provides backward compatibility for workflows that expect files.
        Files are generated temporarily and should be cleaned up after use.

        Args:
            newsletter_id: Newsletter identifier
            version: Version to export ("original", "enriched", "translated")
            format: Format to export ("json", "markdown", "html")
            output_path: Where to write the file (auto-generated if None)

        Returns:
            Path to generated file, or None if failed

        Example:
            # Generate markdown file for download
            path = await repo.generate_file_on_demand(
                "nl_123",
                version="enriched",
                format="markdown",
                output_path="/tmp/newsletter.md"
            )
        """
        try:
            # Retrieve content from MongoDB
            content = await self.get_newsletter_content(newsletter_id, version, format)

            if content is None:
                logger.error(f"Cannot generate file: content not found for {newsletter_id} " f"(version={version}, format={format})")
                return None

            # Auto-generate output path if not provided
            if not output_path:
                import tempfile

                file_extension = {
                    FileFormat.JSON: FILE_EXT_JSON,
                    FileFormat.MARKDOWN: FILE_EXT_MD,
                    FileFormat.HTML: FILE_EXT_HTML,
                }[format]

                temp_dir = Path(tempfile.gettempdir()) / "langrag_newsletters"
                temp_dir.mkdir(parents=True, exist_ok=True)

                output_path = str(temp_dir / f"{newsletter_id}_{version}{file_extension}")

            # Ensure parent directory exists
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Write content to file
            if format == FileFormat.JSON:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(content, f, indent=2, ensure_ascii=False)
            else:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(content)

            logger.info(f"Generated file for newsletter {newsletter_id} " f"(version={version}, format={format}) at {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to generate file for newsletter {newsletter_id} " f"(version={version}, format={format}): {e}")
            raise
