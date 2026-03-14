"""
MCP Israel Newsletter Format

Complete format definition for MCP Israel community newsletters.
Combines schema, prompts, and renderers into a single cohesive format plugin.
"""

import json
import logging

from pydantic import BaseModel

from custom_types.newsletter_formats.base import NewsletterFormatBase
from custom_types.field_keys import NewsletterStructureKeys
from constants import DEFAULT_LANGUAGE, DEFAULT_HTML_LANGUAGE, MessageRole, SummaryFormats, MCP_ISRAEL_GROUP_NAME_DEFAULT, MCP_ISRAEL_DISPLAY_NAME
from .schema import LlmResponseMcpIsraelNewsletterContent
from .prompt import MCP_NEWSLETTER_PROMPT, ADDITIONAL_TOPICS_GUIDANCE
from .renderer import McpIsraelRenderer

logger = logging.getLogger(__name__)


class McpIsraelFormat(NewsletterFormatBase):
    """
    MCP Israel newsletter format for technical communities.

    Features:
    - Categorical section structure (Tools, Practices, Issues, etc.)
    - Comprehensive markdown content with structured JSON
    - RTL Hebrew support with professional styling

    Capabilities:
    - supports_hitl: True - Supports human selection of discussions
    - handles_links_internally: True - Links embedded during content generation
    """

    format_name = SummaryFormats.MCP_ISRAEL_FORMAT
    format_display_name = MCP_ISRAEL_DISPLAY_NAME
    language = DEFAULT_HTML_LANGUAGE

    # Format capabilities
    supports_hitl = True  # Supports Human-in-the-Loop discussion selection
    handles_links_internally = True  # Links embedded during content generation (skip link enrichment)

    def __init__(self):
        self._renderer = McpIsraelRenderer()

    def get_response_schema(self) -> type[BaseModel]:
        """Return the Pydantic model for LLM response."""
        return LlmResponseMcpIsraelNewsletterContent

    def get_system_prompt(self, group_name: str = MCP_ISRAEL_GROUP_NAME_DEFAULT, brief_mention_items: list | None = None, desired_language: str = DEFAULT_LANGUAGE, **kwargs) -> str:
        """
        Build system prompt with group name and additional topics.

        Args:
            group_name: Name of the WhatsApp group
            brief_mention_items: Optional list of candidate items for additional topics
            desired_language: Target language for newsletter output (default: DEFAULT_LANGUAGE)

        Returns:
            Complete system prompt string
        """
        if brief_mention_items:
            additional_topics_guidance = ADDITIONAL_TOPICS_GUIDANCE.format(brief_mention_items=json.dumps(brief_mention_items, indent=2, ensure_ascii=False))
        else:
            additional_topics_guidance = ""

        return MCP_NEWSLETTER_PROMPT.format(
            group_name=group_name,
            desired_language=desired_language,
            additional_topics_guidance=additional_topics_guidance,
        )

    def get_examples(self) -> list[str]:
        """
        Return list of example newsletter outputs.

        Note: MCP Israel format doesn't use few-shot examples like LangTalks.
        Returns empty list - the detailed prompt is sufficient.
        """
        return []

    def build_messages(self, discussions: list[dict], brief_mention_items: list | None = None, group_name: str = MCP_ISRAEL_GROUP_NAME_DEFAULT, desired_language: str = DEFAULT_LANGUAGE, **kwargs) -> list[dict]:
        """
        Build complete message list for LLM call.

        Args:
            discussions: List of discussion dictionaries to summarize
            brief_mention_items: Optional list of items for additional topics
            group_name: Name of the WhatsApp group
            desired_language: Target language for newsletter output (default: DEFAULT_LANGUAGE)
            **kwargs: Additional parameters

        Returns:
            List of message dictionaries ready for OpenAI API
        """
        messages = [
            {
                "role": MessageRole.SYSTEM,
                "content": self.get_system_prompt(group_name=group_name, brief_mention_items=brief_mention_items, desired_language=desired_language),
            }
        ]

        # Language instruction is now in system prompt, but we keep this as reinforcement
        language_instruction = f"\n\nIMPORTANT: Generate the entire newsletter in {desired_language.upper()}. All sections, titles, and content must be in {desired_language}."

        # User message with discussions to summarize
        messages.append(
            {
                "role": MessageRole.USER,
                "content": (f"Here are the translated WhatsApp discussions from the {group_name} group. " "Please create a comprehensive technical newsletter summary according to the requested format:\n\n" f"{json.dumps(discussions, indent=2, ensure_ascii=False)}" f"{language_instruction}"),
            }
        )

        return messages

    def render_markdown(self, response: dict) -> str:
        """Convert LLM response to markdown format."""
        return self._renderer.render_markdown(response)

    def render_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Convert LLM response to HTML format with appropriate language styling.

        Args:
            response: Newsletter JSON with markdown_content and individual sections
            desired_language: Target language for HTML attributes (default: DEFAULT_HTML_LANGUAGE)

        Returns:
            HTML string with complete document structure
        """
        return self._renderer.render_html(response, desired_language=desired_language)

    def get_empty_response(self) -> dict:
        """Return empty newsletter response structure for when there are no discussions."""
        empty_message = "No discussions were found for this time period. The group was quiet during this time."
        return {
            NewsletterStructureKeys.MARKDOWN_CONTENT: f"# MCP Israel Group - Technical Summary\n\n{empty_message}\n\n## Summary\n- No messages to summarize\n- No discussions to report\n- Group activity: None",
            NewsletterStructureKeys.INDUSTRY_UPDATES: "No updates available",
            NewsletterStructureKeys.TOOLS_MENTIONED: "No tools mentioned",
            NewsletterStructureKeys.WORK_PRACTICES: "No work practices discussed",
            NewsletterStructureKeys.SECURITY_RISKS: "No security risks discussed",
            NewsletterStructureKeys.VALUABLE_POSTS: "No valuable posts found",
            NewsletterStructureKeys.OPEN_QUESTIONS: "No open questions found",
            NewsletterStructureKeys.CONCEPTUAL_DISCUSSIONS: "No conceptual discussions found",
            NewsletterStructureKeys.ISSUES_CHALLENGES: "No issues or challenges discussed",
        }
