"""
Retrieval Module

Contains business logic for ranking and filtering discussions.
This includes:
- Discussion ranking algorithms (LLM-based and rule-based)
- Scoring and categorization logic
- Top-K selection strategies

Note: LangGraph subgraph wrappers are in graphs/subgraphs/.
This module contains the pure business logic that those graphs invoke.
"""

from core.retrieval.rankers import (
    DiscussionRanker,
    rank_discussions,
)

__all__ = [
    "DiscussionRanker",
    "rank_discussions",
]
