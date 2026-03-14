"""
Newsletter Format Base Classes

Defines the protocol and abstract base class for newsletter format plugins.
Each format plugin must implement these interfaces to be auto-discovered.

Format Capabilities:
    Each format declares its behavioral capabilities via class attributes:
    - supports_hitl: Whether HITL (Human-in-the-Loop) selection is supported
    - handles_links_internally: If True, links are embedded during generation (skip link enrichment)

    This allows the orchestration layer to query format capabilities instead of
    maintaining hardcoded format-specific logic.
"""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable
from pydantic import BaseModel

from constants import DEFAULT_LANGUAGE, DEFAULT_HTML_LANGUAGE


@runtime_checkable
class NewsletterFormatProtocol(Protocol):
    """Protocol defining what a newsletter format must provide."""

    format_name: str  # e.g., "langtalks_format"
    format_display_name: str  # e.g., "LangTalks"
    language: str  # e.g., "hebrew"

    # Format capabilities
    supports_hitl: bool  # Whether HITL selection is supported
    handles_links_internally: bool  # If True, skip link enrichment stage

    def get_response_schema(self) -> type[BaseModel]:
        """Return the Pydantic model for LLM response."""
        ...

    def get_system_prompt(self, **kwargs) -> str:
        """Return formatted system prompt with any dynamic content."""
        ...

    def get_examples(self) -> list[str]:
        """Return list of example outputs for few-shot prompting."""
        ...

    def build_messages(self, discussions: list[dict], brief_mention_items: list | None = None, desired_language: str = DEFAULT_LANGUAGE, **kwargs) -> list[dict]:
        """Build complete message list for LLM call."""
        ...

    def render_markdown(self, response: dict) -> str:
        """Convert LLM response to markdown format."""
        ...

    def render_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Convert LLM response to HTML format."""
        ...

    def render_substack_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Render clean HTML for Substack (no CSS, no JS)."""
        ...

    def get_empty_response(self) -> dict:
        """Return a valid empty response for when there are no discussions."""
        ...


class NewsletterFormatBase(ABC):
    """
    Base class for newsletter formats with common functionality.

    To create a new newsletter format:
    1. Create a new directory under src/custom_types/newsletter_formats/<format_name>/
    2. Implement a class inheriting from NewsletterFormatBase
    3. Export it as FORMAT_CLASS in the __init__.py
    4. Set capability attributes (supports_hitl, handles_links_internally)

    The format will be auto-discovered and registered at import time.

    Capabilities:
        supports_hitl: Set to True if format supports Human-in-the-Loop selection.
            When True, the workflow may pause for user discussion selection.
            Default: True

        handles_links_internally: Set to True if format embeds links during
            content generation (e.g., in the LLM prompt). When True, the
            link enrichment stage will be skipped.
            Default: False
    """

    format_name: str
    format_display_name: str
    language: str = DEFAULT_HTML_LANGUAGE

    # Format capabilities (can be overridden by subclasses)
    supports_hitl: bool = True
    handles_links_internally: bool = False

    @abstractmethod
    def get_response_schema(self) -> type[BaseModel]:
        """
        Return the Pydantic model for LLM response.

        This schema defines the structure of the newsletter content
        that the LLM should generate.
        """
        pass

    @abstractmethod
    def get_system_prompt(self, **kwargs) -> str:
        """
        Return formatted system prompt with any dynamic content.

        Args:
            **kwargs: Dynamic content to inject into the prompt
                     (e.g., brief_mention_items for worth_mentioning section)

        Returns:
            Complete system prompt string
        """
        pass

    @abstractmethod
    def get_examples(self) -> list[str]:
        """
        Return list of example outputs for few-shot prompting.

        Returns:
            List of example newsletter outputs as strings
        """
        pass

    @abstractmethod
    def build_messages(self, discussions: list[dict], brief_mention_items: list | None = None, desired_language: str = DEFAULT_LANGUAGE, **kwargs) -> list[dict]:
        """
        Build the complete message list for LLM call.

        Format owns prompt assembly - returns list of messages in OpenAI format:
        [{"role": "system", "content": ...}, {"role": "assistant", "content": ...}, ...]

        Args:
            discussions: List of discussion dictionaries to summarize
            brief_mention_items: Optional list of items for worth_mentioning section
            desired_language: Target language for newsletter output (default: DEFAULT_LANGUAGE)
            **kwargs: Additional parameters (e.g., group_name)

        Returns:
            List of message dictionaries ready for LLM API call
        """
        pass

    @abstractmethod
    def render_markdown(self, response: dict) -> str:
        """
        Convert LLM response to markdown format.

        Args:
            response: Parsed LLM response dictionary

        Returns:
            Markdown-formatted newsletter string
        """
        pass

    def render_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Convert LLM response to HTML format.

        Optional - defaults to basic HTML wrapper around markdown.
        Override in subclass for custom HTML formatting.

        Args:
            response: Parsed LLM response dictionary
            desired_language: Target language for HTML attributes (default: DEFAULT_HTML_LANGUAGE)

        Returns:
            HTML-formatted newsletter string
        """
        md = self.render_markdown(response)
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{self.format_display_name} Newsletter</title>
</head>
<body>
<pre>{md}</pre>
</body>
</html>"""

    def render_substack_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Render clean HTML for Substack (no CSS, no JS).

        Defaults to render_html. Override in subclass for Substack-specific output.

        Args:
            response: Parsed LLM response dictionary
            desired_language: Target language for HTML attributes

        Returns:
            Clean HTML string suitable for Substack
        """
        return self.render_html(response, desired_language)

    @abstractmethod
    def get_empty_response(self) -> dict:
        """
        Return a valid empty response for when there are no discussions.

        This response should match the structure expected by get_response_schema()
        but with placeholder content indicating no activity.

        Returns:
            Dictionary matching the response schema structure
        """
        pass
