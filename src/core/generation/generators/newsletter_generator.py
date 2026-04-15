"""
Generic Newsletter Content Generator

Uses NewsletterFormat plugins to generate newsletters.
All format-specific logic lives in the format plugins - this generator
provides the common workflow for any newsletter format.
"""

import json
import logging
import os
from typing import Any

from custom_types.newsletter_formats import get_format, NewsletterFormatBase
from core.generation.generators.base import ContentGeneratorInterface
from constants import (
    ContentGenerationOperations,
    DataSources,
    DEFAULT_LANGUAGE,
    NewsletterType,
    RepetitionScore,
    OUTPUT_FILENAME_NEWSLETTER_JSON,
    OUTPUT_FILENAME_NEWSLETTER_MD,
    OUTPUT_FILENAME_NEWSLETTER_HTML,
    RESULT_KEY_NEWSLETTER_SUMMARY_PATH,
    RESULT_KEY_MARKDOWN_PATH,
    RESULT_KEY_HTML_PATH,
)
from utils.llm import get_llm_caller
from custom_types.common import LlmResponseTranslateSummary
from custom_types.field_keys import NewsletterStructureKeys, ContentResultKeys, RankingResultKeys, DiscussionKeys, LlmInputKeys
from config import get_settings
from db.repositories.newsletters import NewslettersRepository

logger = logging.getLogger(__name__)


class NewsletterContentGenerator(ContentGeneratorInterface):
    """
    Generic newsletter generator that uses format plugins.

    This generator handles the common workflow:
    1. Validates inputs
    2. Delegates prompt building to the format
    3. Calls LLM with format's schema
    4. Uses format's renderers for output

    All format-specific logic (prompts, schemas, rendering) is in format plugins.
    """

    def __init__(self, format_name: str, newsletters_repo: NewslettersRepository | None = None, **kwargs):
        """
        Initialize generator with a specific format.

        Args:
            format_name: The format identifier (e.g., "langtalks_format")
            newsletters_repo: Optional MongoDB repository for newsletter persistence
            **kwargs: Extra kwargs from factory (ignored — kept for forward compatibility)
        """
        super().__init__()
        self._format: NewsletterFormatBase = get_format(format_name)
        self._newsletters_repo = newsletters_repo
        self._settings = get_settings()
        self.OPERATIONS_MAP = {
            DataSources.WHATSAPP_GROUP_CHAT_MESSAGES: {
                ContentGenerationOperations.GENERATE_NEWSLETTER_SUMMARY: self._generate_newsletter,
                ContentGenerationOperations.TRANSLATE_SUMMARY: self._translate_summary,
            }
        }
        logger.debug(f"Initialized NewsletterContentGenerator with format: {format_name}, " f"mongodb_enabled={newsletters_repo is not None}, " f"file_outputs_enabled={self._settings.database.enable_file_outputs}")

    async def generate_content(self, operation: str, **kwargs) -> Any:
        """
        Generate content based on the specified operation.

        Args:
            operation: The type of content generation operation
            **kwargs: Arguments needed for content generation

        Returns:
            Generated content in the appropriate format

        Raises:
            ValueError: If required arguments are missing or operation not found
        """
        try:
            data_source_type = kwargs.get("data_source_type")
            if not data_source_type:
                raise ValueError("data_source_type is required")

            data_source_path = kwargs.get("data_source_path")
            if not data_source_path:
                raise ValueError("data_source_path is required")

            operation_fn = self.OPERATIONS_MAP.get(data_source_type, {}).get(operation)
            if not operation_fn:
                raise ValueError(f"Operation {operation} not found for data source type {data_source_type}")

            return await operation_fn(**kwargs)

        except Exception as e:
            error_message = f"Error generating content: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    async def _generate_newsletter(self, **kwargs) -> dict:
        """
        Generate newsletter using the format plugin.

        Args:
            **kwargs: Must include:
                - featured_discussions: List of discussions to summarize
                - output_dir: Directory to save outputs
                - desired_language_for_summary: Target language for output
                - brief_mention_items (optional): Items for worth_mentioning
                - group_name (optional): Name of the chat group
                - model (optional): LLM model to use

        Returns:
            Dictionary with paths to generated files
        """
        try:
            # Validate required inputs
            featured_discussions = kwargs.get("featured_discussions")
            if featured_discussions is None:
                raise ValueError("featured_discussions is required but was not provided. " "The content generator expects pre-filtered discussions from the ranking stage.")

            output_dir = kwargs.get("output_dir")
            if not output_dir:
                raise ValueError("output_dir is required")

            desired_language = kwargs.get("desired_language_for_summary", DEFAULT_LANGUAGE)

            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"Generating {self._format.format_name} newsletter with " f"{len(featured_discussions)} discussions in {desired_language}")

            # Handle empty discussions
            if len(featured_discussions) == 0:
                logger.warning("No discussions found. Creating empty newsletter.")
                return await self._generate_empty_newsletter(output_dir)

            # Filter out high/medium-repetition brief mentions and cap at 10
            brief_mention_items = kwargs.get(RankingResultKeys.BRIEF_MENTION_ITEMS, [])
            if brief_mention_items:
                original_count = len(brief_mention_items)
                brief_mention_items = [item for item in brief_mention_items if item.get(RankingResultKeys.REPETITION_SCORE) not in (RepetitionScore.HIGH, RepetitionScore.MEDIUM)]
                filtered_count = original_count - len(brief_mention_items)
                if filtered_count > 0:
                    logger.info(f"Anti-repetition: filtered {filtered_count} high/medium-repetition brief mentions " f"({original_count} -> {len(brief_mention_items)})")
                # Cap at 10 candidates to keep worth_mentioning focused
                brief_mention_items = brief_mention_items[:10]

            # Extract non-featured discussions for worth_mentioning fallback
            non_featured_discussions = kwargs.get("non_featured_discussions", [])

            # Format builds the complete message list (owns prompt assembly)
            image_discussion_map = kwargs.get(LlmInputKeys.IMAGE_DISCUSSION_MAP)
            messages = self._format.build_messages(
                discussions=featured_discussions,
                brief_mention_items=brief_mention_items,
                non_featured_discussions=non_featured_discussions,
                group_name=kwargs.get(DiscussionKeys.GROUP_NAME, self._format.format_display_name),
                desired_language=desired_language,
                image_discussion_map=image_discussion_map,
            )

            response_schema = self._format.get_response_schema()

            # Call LLM with generic method
            client = get_llm_caller()
            response = await client.call_with_structured_output_generic(
                messages=messages,
                response_schema=response_schema,
                purpose=f"newsletter_generation:{self._format.format_name}",
                model=kwargs.get("model"),
            )

            # Save outputs with MongoDB metadata
            return await self._save_outputs(
                response=response,
                output_dir=output_dir,
                newsletter_id=kwargs.get(ContentResultKeys.NEWSLETTER_ID),
                run_id=kwargs.get("run_id"),
                newsletter_type=kwargs.get("newsletter_type", NewsletterType.PER_CHAT),
                data_source_name=kwargs.get("data_source_name"),
                start_date=kwargs.get("start_date"),
                end_date=kwargs.get("end_date"),
                summary_format=kwargs.get("summary_format"),
                desired_language=desired_language,
                chat_name=kwargs.get(NewsletterStructureKeys.CHAT_NAME),
                featured_discussion_ids=kwargs.get(RankingResultKeys.FEATURED_DISCUSSION_IDS),
            )

        except Exception as e:
            error_message = f"Error generating newsletter: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    async def _generate_empty_newsletter(self, output_dir: str, **metadata) -> dict:
        """
        Generate and save an empty newsletter when there are no discussions.

        Args:
            output_dir: Directory for file outputs (if enabled)
            **metadata: Newsletter metadata (newsletter_id, run_id, etc.)
        """
        response = self._format.get_empty_response()
        return await self._save_outputs(response, output_dir, **metadata)

    async def _save_outputs(
        self,
        response: dict,
        output_dir: str,
        newsletter_id: str | None = None,
        run_id: str | None = None,
        newsletter_type: str = NewsletterType.PER_CHAT,
        data_source_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        summary_format: str | None = None,
        desired_language: str | None = None,
        chat_name: str | None = None,
        featured_discussion_ids: list | None = None,
    ) -> dict:
        """
        Save newsletter outputs to MongoDB and optionally to files.

        This method implements MongoDB-first persistence with optional file generation
        for backward compatibility.

        Args:
            response: LLM response dictionary (newsletter content)
            output_dir: Directory to save files (if file outputs enabled)
            newsletter_id: Unique newsletter identifier for MongoDB
            run_id: Associated pipeline run ID
            newsletter_type: "per_chat" or "consolidated"
            data_source_name: Data source (e.g., "langtalks")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            summary_format: Newsletter format identifier
            desired_language: Target language
            chat_name: Source chat name (None for consolidated)
            featured_discussion_ids: List of featured discussion IDs

        Returns:
            Dictionary with newsletter_id and optionally file paths
        """
        try:
            # Render content in all formats
            md_content = self._format.render_markdown(response, desired_language=desired_language)
            html_content = self._format.render_html(response, desired_language=desired_language)

            # MongoDB-first persistence
            mongodb_id = None
            if self._newsletters_repo and newsletter_id:
                logger.info(f"Saving newsletter to MongoDB: {newsletter_id}")

                # Calculate stats
                stats = {
                    "word_count": len(md_content.split()),
                    "discussion_count": len(featured_discussion_ids or []),
                    "primary_discussion_count": 1 if response.get(NewsletterStructureKeys.PRIMARY_DISCUSSION) else 0,
                    "secondary_discussion_count": len(response.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, [])),
                    "worth_mentioning_count": len(response.get(NewsletterStructureKeys.WORTH_MENTIONING, [])),
                }

                # Await async MongoDB operation
                mongodb_id = await self._newsletters_repo.create_newsletter(
                    newsletter_id=newsletter_id,
                    run_id=run_id,
                    newsletter_type=newsletter_type,
                    data_source_name=data_source_name,
                    start_date=start_date,
                    end_date=end_date,
                    summary_format=summary_format or self._format.format_name,
                    desired_language=desired_language,
                    original_json=response,
                    original_markdown=md_content,
                    original_html=html_content,
                    file_paths={},  # Deprecated
                    chat_name=chat_name,
                    stats=stats,
                    featured_discussion_ids=featured_discussion_ids or [],
                )

                logger.info(f"Newsletter saved to MongoDB: {newsletter_id} " f"(db_id={mongodb_id}, word_count={stats['word_count']})")

            # Optional file generation (backward compatibility)
            file_paths = {}
            if self._settings.database.enable_file_outputs:
                logger.info(f"File outputs enabled - generating files in: {output_dir}")
                os.makedirs(output_dir, exist_ok=True)

                json_path = os.path.join(output_dir, OUTPUT_FILENAME_NEWSLETTER_JSON)
                md_path = os.path.join(output_dir, OUTPUT_FILENAME_NEWSLETTER_MD)
                html_path = os.path.join(output_dir, OUTPUT_FILENAME_NEWSLETTER_HTML)

                # Save JSON
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(response, f, indent=2, ensure_ascii=False)

                # Save Markdown
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)

                # Save HTML
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

                file_paths = {
                    RESULT_KEY_NEWSLETTER_SUMMARY_PATH: json_path,
                    RESULT_KEY_MARKDOWN_PATH: md_path,
                    RESULT_KEY_HTML_PATH: html_path,
                }

                logger.info(f"Newsletter files saved to: {json_path}, {md_path}, and {html_path}")
            else:
                logger.debug("File outputs disabled (MONGODB_ENABLE_FILE_OUTPUTS=false) - " "newsletter stored in MongoDB only")

            # Return response based on what was saved
            result = {ContentResultKeys.NEWSLETTER_ID: newsletter_id} if newsletter_id else {}

            if file_paths:
                result.update(file_paths)

            return result

        except Exception as e:
            logger.error(f"Failed to save newsletter outputs: {e}")
            raise

    async def _translate_summary(self, **kwargs) -> dict:
        """
        Translate newsletter summary to another language.

        Args:
            **kwargs: Must include:
                - data_source_path: Path to markdown file to translate
                - group_name: Name of the group
                - desired_language_for_summary: Target language
                - expected_final_translated_file_path: Output path

        Returns:
            Dictionary with path to translated file
        """
        try:
            data_source_path = kwargs.get("data_source_path")
            if not os.path.exists(data_source_path):
                raise ValueError(f"Data source path does not exist: {data_source_path}")

            group_name = kwargs.get("group_name")
            if not group_name:
                raise ValueError("Group name is required")

            desired_language_for_summary = kwargs.get("desired_language_for_summary")
            if not desired_language_for_summary:
                raise ValueError("Desired language for summary is required")

            expected_final_translated_file_path = kwargs.get("expected_final_translated_file_path")
            if not expected_final_translated_file_path:
                raise ValueError("Expected final translated file path is required")

            # Read markdown content
            with open(data_source_path, encoding="utf-8") as file:
                markdown_content = file.read()
                if not markdown_content.strip():
                    raise ValueError(f"File is empty: {data_source_path}")

            # Translate using LLM
            from constants import LlmInputPurposes

            client = get_llm_caller()
            response = await client.call_with_structured_output(
                purpose=LlmInputPurposes.TRANSLATE_SUMMARY,
                response_schema=LlmResponseTranslateSummary,
                input_to_translate=markdown_content,
                group_name=group_name,
                desired_language_for_summary=desired_language_for_summary,
            )

            translated_markdown = response.get("summary")
            if not translated_markdown:
                raise ValueError(f"Unexpected response from LLM: missing 'summary' field. response: {response}")

            # Save translated content
            with open(expected_final_translated_file_path, "w", encoding="utf-8") as f:
                f.write(translated_markdown)

            logger.info(f"Translated summary saved to: {expected_final_translated_file_path}")

            return {"final_translated_file_path": expected_final_translated_file_path}

        except Exception as e:
            error_message = f"Error translating summary: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e
