"""
Content Generator Factory

Creates content generators using the newsletter format plugin registry.
Format-specific logic is encapsulated in format plugins - the factory
simply validates and instantiates the appropriate generator.
"""

import logging

from constants import DataSources
from custom_types.newsletter_formats import get_format, list_formats, is_valid_format
from core.generation.generators.newsletter_generator import NewsletterContentGenerator

logger = logging.getLogger(__name__)


class ContentGeneratorFactory:
    """
    Factory for creating content generators based on data source type and summary format.

    Uses the newsletter format registry for auto-discovered format plugins.
    Adding a new format only requires creating the format plugin - no changes
    to this factory are needed.
    """

    @classmethod
    def create(cls, data_source_type: str, summary_format: str, **kwargs):
        """
        Create a content generator for the given data source type and summary format.

        Args:
            data_source_type: Type of data source (e.g., "whatsapp_group_chat_messages")
            summary_format: Format for the generated summary (e.g., "langtalks_format")
            **kwargs: Additional arguments passed to the generator

        Returns:
            NewsletterContentGenerator instance configured for the specified format

        Raises:
            ValueError: If data source type or summary format is not supported
        """
        # Validate data source type
        if data_source_type != DataSources.WHATSAPP_GROUP_CHAT_MESSAGES:
            raise ValueError(f"Unsupported data source type: '{data_source_type}'. " f"Currently supported: {DataSources.WHATSAPP_GROUP_CHAT_MESSAGES}")

        # Validate format exists using registry
        if not is_valid_format(summary_format):
            available = list_formats()
            raise ValueError(f"Format '{summary_format}' not found. " f"Available formats: {available}")

        logger.debug(f"Creating NewsletterContentGenerator for format: {summary_format}")
        return NewsletterContentGenerator(format_name=summary_format, **kwargs)

    @classmethod
    def list_available_formats(cls) -> list[str]:
        """
        Return list of available newsletter formats.

        Returns:
            List of format name strings (e.g., ["langtalks_format", "mcp_israel_format"])
        """
        return list_formats()

    @classmethod
    def get_format_info(cls, format_name: str) -> dict:
        """
        Get information about a specific format.

        Args:
            format_name: The format identifier

        Returns:
            Dictionary with format metadata (name, display_name, language)

        Raises:
            KeyError: If format not found
        """
        format_instance = get_format(format_name)
        return {
            "format_name": format_instance.format_name,
            "display_name": format_instance.format_display_name,
            "language": format_instance.language,
        }
