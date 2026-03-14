"""
Discussion Merging Prompts

Prompts for identifying similar discussions and merging them into comprehensive super-discussions.
"""

from utils.llm.prompts.merging.merge_discussions import (
    IDENTIFY_MERGE_GROUPS_PROMPT,
    GENERATE_MERGED_TITLE_PROMPT,
    SYNTHESIZE_MERGED_NUTSHELL_PROMPT,
    VALIDATE_MERGE_CANDIDATES_PROMPT,
)

__all__ = [
    "IDENTIFY_MERGE_GROUPS_PROMPT",
    "GENERATE_MERGED_TITLE_PROMPT",
    "SYNTHESIZE_MERGED_NUTSHELL_PROMPT",
    "VALIDATE_MERGE_CANDIDATES_PROMPT",
]
