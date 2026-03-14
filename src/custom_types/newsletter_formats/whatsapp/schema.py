"""
WhatsApp Newsletter Response Schema

Re-exports the LangTalks schema — the content structure is identical,
only the rendering differs (WhatsApp plain text vs HTML).
"""

from custom_types.newsletter_formats.langtalks.schema import (
    LlmResponseLangTalksNewsletterContent as LlmResponseWhatsAppNewsletterContent,
)

__all__ = ["LlmResponseWhatsAppNewsletterContent"]
