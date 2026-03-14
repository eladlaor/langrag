"""
Translation Prompts

Prompts for translating WhatsApp messages and newsletter content.
"""

from utils.llm.prompts.translation.translate_messages import TRANSLATE_MESSAGES_PROMPT
from utils.llm.prompts.translation.translate_newsletter import TRANSLATE_NEWSLETTER_PROMPT

__all__ = [
    "TRANSLATE_MESSAGES_PROMPT",
    "TRANSLATE_NEWSLETTER_PROMPT",
]
