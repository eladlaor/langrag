"""
Multi-Chat Consolidator Graph

Orchestrates parallel processing of multiple WhatsApp chats and consolidates
results into a single unified newsletter.

Flow:
START → ensure_valid_session → dispatch_chats → [chat_worker*] → aggregate_results
      → [consolidation flow] → output_handler → END
"""

from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph
from graphs.multi_chat_consolidator.state import ParallelOrchestratorState

__all__ = [
    "get_parallel_orchestrator_graph",
    "ParallelOrchestratorState",
]
