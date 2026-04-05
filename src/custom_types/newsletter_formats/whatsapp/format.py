"""
WhatsApp Newsletter Format

Complete format definition for WhatsApp community newsletters.
Same content structure as LangTalks (primary + secondary + worth_mentioning),
rendered as WhatsApp-native plain text instead of HTML.
"""

import json
import logging

from pydantic import BaseModel

from custom_types.newsletter_formats.base import NewsletterFormatBase
from custom_types.newsletter_formats.image_context import build_image_context_text
from custom_types.field_keys import NewsletterStructureKeys, DiscussionKeys, LlmInputKeys
from constants import DEFAULT_LANGUAGE, DEFAULT_HTML_LANGUAGE, MessageRole, SummaryFormats, WHATSAPP_DISPLAY_NAME
from .schema import LlmResponseWhatsAppNewsletterContent
from .prompt import WHATSAPP_NEWSLETTER_PROMPT
from custom_types.newsletter_formats.langtalks.prompt import (
    WORTH_MENTIONING_WITH_CANDIDATES,
    WORTH_MENTIONING_FROM_RAW_DISCUSSIONS,
    WORTH_MENTIONING_WITHOUT_CANDIDATES,
)
from .renderer import WhatsAppRenderer

logger = logging.getLogger(__name__)


class WhatsAppFormat(NewsletterFormatBase):
    """
    WhatsApp newsletter format for community newsletters shared via WhatsApp.

    Features:
    - Same content structure as LangTalks (primary + secondary + worth_mentioning)
    - WhatsApp-native plain text rendering (*bold*, bullet points, bare URLs)
    - HTML viewer with copy-to-clipboard for easy sharing
    - Hebrew content with English technical terms

    Capabilities:
    - supports_hitl: True - Supports human selection of discussions
    - handles_links_internally: False - Uses external link enrichment stage
    """

    format_name = SummaryFormats.WHATSAPP_FORMAT
    format_display_name = WHATSAPP_DISPLAY_NAME
    language = DEFAULT_HTML_LANGUAGE

    # Format capabilities
    supports_hitl = True
    handles_links_internally = False

    def __init__(self):
        self._renderer = WhatsAppRenderer()

    def get_response_schema(self) -> type[BaseModel]:
        """Return the Pydantic model for LLM response."""
        return LlmResponseWhatsAppNewsletterContent

    def get_system_prompt(self, brief_mention_items: list | None = None, non_featured_discussions: list | None = None, featured_discussions: list | None = None, **kwargs) -> str:
        """
        Build system prompt with worth_mentioning guidance.

        Uses 3-tier prompt routing (same as LangTalks):
        1. brief_mention_items exists -> use WORTH_MENTIONING_WITH_CANDIDATES
        2. non_featured_discussions exists -> use WORTH_MENTIONING_FROM_RAW_DISCUSSIONS
        3. Neither exists -> use WORTH_MENTIONING_WITHOUT_CANDIDATES

        Args:
            brief_mention_items: Optional list of candidate items for worth_mentioning
            non_featured_discussions: Optional list of non-featured discussions as fallback context
            featured_discussions: Optional list of featured discussion dicts for exclusion list

        Returns:
            Complete system prompt string
        """
        featured_topics_exclusion = self._build_featured_topics_exclusion(featured_discussions)

        if brief_mention_items:
            worth_mentioning_guidance = WORTH_MENTIONING_WITH_CANDIDATES.format(
                num_candidates=len(brief_mention_items),
                brief_mention_items=json.dumps(brief_mention_items, indent=2, ensure_ascii=False),
                featured_topics_exclusion=featured_topics_exclusion,
            )
        elif non_featured_discussions:
            worth_mentioning_guidance = WORTH_MENTIONING_FROM_RAW_DISCUSSIONS.format(
                num_discussions=len(non_featured_discussions),
                non_featured_discussions=json.dumps(non_featured_discussions, indent=2, ensure_ascii=False),
                featured_topics_exclusion=featured_topics_exclusion,
            )
        else:
            worth_mentioning_guidance = WORTH_MENTIONING_WITHOUT_CANDIDATES

        return WHATSAPP_NEWSLETTER_PROMPT.format(worth_mentioning_guidance=worth_mentioning_guidance)

    @staticmethod
    def _build_featured_topics_exclusion(featured_discussions: list | None) -> str:
        """Extract titles from featured discussions and format as a numbered exclusion list."""
        if not featured_discussions:
            return "(No featured discussions provided)"

        entries = []
        for disc in featured_discussions:
            title = disc.get(NewsletterStructureKeys.TITLE) or disc.get(DiscussionKeys.DISCUSSION_TITLE, "")
            if title:
                nutshell = disc.get(DiscussionKeys.NUTSHELL, "")
                entry = f"{title} — {nutshell}" if nutshell else title
                entries.append(entry)

        if not entries:
            return "(No featured discussion titles found)"

        return "\n".join(f"{i}. {entry}" for i, entry in enumerate(entries, 1))

    def get_examples(self) -> list[str]:
        """Return list of example newsletter outputs (none for WhatsApp format initially)."""
        return []

    def build_messages(self, discussions: list[dict], brief_mention_items: list | None = None, non_featured_discussions: list | None = None, desired_language: str = DEFAULT_LANGUAGE, **kwargs) -> list[dict]:
        """
        Build complete message list for LLM call.

        Args:
            discussions: List of discussion dictionaries to summarize
            brief_mention_items: Optional list of items for worth_mentioning section
            non_featured_discussions: Optional list of non-featured discussions as fallback for worth_mentioning
            desired_language: Target language for newsletter output
            **kwargs: Additional parameters

        Returns:
            List of message dictionaries ready for OpenAI API
        """
        messages = [{"role": MessageRole.SYSTEM, "content": self.get_system_prompt(brief_mention_items, non_featured_discussions=non_featured_discussions, featured_discussions=discussions)}]

        language_instruction = f"\n\nIMPORTANT: Generate the entire newsletter in {desired_language.upper()}. All titles, bullet points, and content must be in {desired_language}."

        # Build optional image context from associated image descriptions
        image_discussion_map = kwargs.get(LlmInputKeys.IMAGE_DISCUSSION_MAP)
        image_context = build_image_context_text(discussions, image_discussion_map) if image_discussion_map else ""

        messages.append(
            {
                "role": MessageRole.USER,
                "content": ("According to the requirements, " "generate the WhatsApp community newsletter summary for:\n\n" f"{json.dumps(discussions, indent=2, ensure_ascii=False)}" f"{image_context}" f"{language_instruction}"),
            }
        )

        return messages

    def render_markdown(self, response: dict) -> str:
        """Convert LLM response to WhatsApp-formatted plain text."""
        return self._renderer.render_whatsapp_text(response)

    def render_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Convert LLM response to HTML viewer with copy-to-clipboard.

        Args:
            response: Newsletter JSON with primary_discussion, secondary_discussions, worth_mentioning
            desired_language: Target language for HTML attributes

        Returns:
            HTML string with WhatsApp text preview and copy button
        """
        whatsapp_text = self._renderer.render_whatsapp_text(response)
        return self._renderer.render_html_viewer(response, whatsapp_text, desired_language=desired_language)

    def get_empty_response(self) -> dict:
        """Return empty newsletter response structure for when there are no discussions."""
        return {
            NewsletterStructureKeys.PRIMARY_DISCUSSION: {
                NewsletterStructureKeys.TITLE: "No Activity",
                NewsletterStructureKeys.BULLET_POINTS: [
                    {
                        NewsletterStructureKeys.LABEL: "Status",
                        NewsletterStructureKeys.CONTENT: "No discussions were found for this time period. The group was quiet during this time.",
                    }
                ],
                NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP: 0,
                NewsletterStructureKeys.LAST_MESSAGE_TIMESTAMP: 0,
                NewsletterStructureKeys.RANKING_OF_RELEVANCE: 1,
                NewsletterStructureKeys.NUMBER_OF_MESSAGES: 0,
                NewsletterStructureKeys.NUMBER_OF_UNIQUE_PARTICIPANTS: 0,
                NewsletterStructureKeys.CHAT_NAME: "",
            },
            NewsletterStructureKeys.SECONDARY_DISCUSSIONS: [],
            NewsletterStructureKeys.WORTH_MENTIONING: ["No activity to report for this period"],
        }
