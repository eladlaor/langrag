"""
Single Chat Analyzer Graph

Processes individual WhatsApp chats through the complete newsletter generation pipeline:
extract → preprocess → translate → separate → rank → generate → enrich → translate_final

This graph is invoked by the multi_chat_consolidator for each chat in parallel.
"""

from graphs.single_chat_analyzer.graph import newsletter_generation_graph
from graphs.single_chat_analyzer.state import SingleChatState

__all__ = [
    "newsletter_generation_graph",
    "SingleChatState",
]
