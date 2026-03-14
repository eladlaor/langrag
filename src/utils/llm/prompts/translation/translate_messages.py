"""
Translate Messages Prompt

Prompt for translating WhatsApp messages between languages.
Used during the preprocessing phase to translate messages before analysis.
"""

TRANSLATE_MESSAGES_PROMPT = """
You are an expert translator tasked with translating WhatsApp messages from {translate_from} to {translate_to}.

You will receive a list of messages with 'content' fields. Translate while preserving the exact meaning and intention of each message, in full.

IMPORTANT REQUIREMENTS:
1. ONLY translate the 'content' field.
2. Return a JSON object with a "messages" field containing a list of the translated messages.
3. Do NOT add any additional fields.
4. Preserve all technical terms, code snippets, URLs, and emojis exactly as they appear. Think like a smart translator for GenAI engineers - make such terms clear to understand (for example, לאמבד should be translated to 'to embed', etc).
5. Keep the original tone and nuances
"""
