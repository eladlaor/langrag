"""
Discussion Mergers Module

Provides functionality for merging semantically similar discussions
from multiple sources into enriched "super discussions".
"""

from core.retrieval.mergers.discussion_merger import (
    MergeGroup,
    MergedDiscussion,
    DiscussionMerger,
    identify_merge_groups,
    merge_discussions,
    DEFAULT_SIMILARITY_THRESHOLD,
)

__all__ = [
    "MergeGroup",
    "MergedDiscussion",
    "DiscussionMerger",
    "identify_merge_groups",
    "merge_discussions",
    "DEFAULT_SIMILARITY_THRESHOLD",
]
