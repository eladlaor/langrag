"""
LangGraph Workflows for Newsletter Generation

This package contains the main graph implementations:
- single_chat_analyzer: Processes individual chats through the newsletter pipeline
- multi_chat_consolidator: Orchestrates parallel chat processing and cross-chat consolidation
- subgraphs: Reusable subgraph components (discussions_ranker, link_enricher)
"""

from graphs.single_chat_analyzer.graph import newsletter_generation_graph
from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph

__all__ = [
    "newsletter_generation_graph",
    "get_parallel_orchestrator_graph",
]
