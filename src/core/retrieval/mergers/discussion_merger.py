"""
Discussion Merger

Core business logic for merging semantically similar discussions from multiple
sources into enriched "super discussions".

This module provides:
1. identify_merge_groups() - Use LLM to find which discussions should merge
2. merge_discussions() - Execute the merge and create super discussions
3. DiscussionMerger class - Orchestrates the full merge pipeline
"""

import json
import logging
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal

from config import get_settings
from utils.llm import get_llm_caller
from utils.llm.prompts.merging import (
    IDENTIFY_MERGE_GROUPS_PROMPT,
    VALIDATE_MERGE_CANDIDATES_PROMPT,
    GENERATE_MERGED_TITLE_PROMPT,
    SYNTHESIZE_MERGED_NUTSHELL_PROMPT,
)
from constants import LlmInputPurposes, SimilarityThreshold
from custom_types.field_keys import DiscussionKeys, MergeGroupKeys

logger = logging.getLogger(__name__)

# Get defaults from config
_settings = get_settings()
DEFAULT_SIMILARITY_THRESHOLD = _settings.ranking.default_similarity_threshold
MAX_DISCUSSIONS_PER_MERGE = _settings.ranking.max_discussions_per_merge

# Cosine similarity thresholds for embedding-based pre-filtering
EMBEDDING_THRESHOLDS = {
    SimilarityThreshold.STRICT: 0.92,  # Near-identical topics only
    SimilarityThreshold.MODERATE: 0.82,  # Same topic + subtopics (lowered from 0.85 to catch vocabulary variations)
    SimilarityThreshold.AGGRESSIVE: 0.75,  # All related topics
}


@dataclass
class MergeGroup:
    """Represents a group of discussions identified for merging."""

    suggested_title: str
    discussion_ids: list[str]
    source_groups: list[str]
    merge_confidence: Literal["high", "medium"]
    reasoning: str
    metadata: dict[str, Any] | None = None  # For embedding similarities, etc.


@dataclass
class MergedDiscussion:
    """
    A merged "super discussion" combining multiple source discussions.

    Contains all messages from all sources, with attribution preserved.
    """

    id: str
    is_merged: bool
    title: str
    source_discussions: list[dict[str, str]]  # [{id, group, original_title}]
    messages: list[dict[str, Any]]
    nutshell: str
    num_messages: int
    num_unique_participants: int
    first_message_timestamp: int
    merge_reasoning: str | None = None
    # Original fields preserved for non-merged discussions
    group_name: str | None = None


@dataclass
class MergeResult:
    """Result of the discussion merging operation."""

    discussions: list[dict[str, Any]]
    original_count: int
    merged_count: int
    merge_operations: int
    merge_groups: list["MergeGroup"]


def _format_discussions_for_prompt(discussions: list[dict[str, Any]]) -> str:
    """Format discussions for the LLM prompt."""
    lines = []
    for i, disc in enumerate(discussions, 1):
        disc_id = disc.get(DiscussionKeys.ID, f"discussion_{i}")
        title = disc.get(DiscussionKeys.TITLE, "Untitled")
        group = disc.get(DiscussionKeys.GROUP_NAME, "Unknown Group")
        nutshell = disc.get(DiscussionKeys.NUTSHELL, "")[:200]  # Truncate for prompt size
        num_messages = disc.get(DiscussionKeys.NUM_MESSAGES, len(disc.get(DiscussionKeys.MESSAGES, [])))

        lines.append(f"{i}. [ID: {disc_id}] [Group: {group}]")
        lines.append(f"   Title: {title}")
        lines.append(f"   Summary: {nutshell}")
        lines.append(f"   Messages: {num_messages}")
        lines.append("")

    return "\n".join(lines)


def _format_sources_for_synthesis(source_discussions: list[dict[str, Any]]) -> str:
    """Format source discussions for nutshell synthesis prompt."""
    lines = []
    for i, disc in enumerate(source_discussions, 1):
        group = disc.get(DiscussionKeys.GROUP_NAME, "Unknown Group")
        title = disc.get(DiscussionKeys.TITLE, "Untitled")
        nutshell = disc.get(DiscussionKeys.NUTSHELL, "No summary available")

        lines.append(f"**Discussion {i} (from {group}):**")
        lines.append(f"- Title: {title}")
        lines.append(f"- Original Summary: {nutshell}")
        lines.append("")

    return "\n".join(lines)


async def identify_merge_groups(
    discussions: list[dict[str, Any]],
    similarity_threshold: str = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[list[MergeGroup], list[str]]:
    """
    Use LLM to identify which discussions should be merged.

    Args:
        discussions: List of discussion dictionaries with id, title, nutshell, group_name
        similarity_threshold: "strict", "moderate", or "aggressive"

    Returns:
        Tuple of (merge_groups, standalone_ids)
    """
    if len(discussions) < 2:
        logger.info("Less than 2 discussions - nothing to merge")
        return [], [d.get(DiscussionKeys.ID) for d in discussions]

    # Get unique groups
    groups = set(d.get(DiscussionKeys.GROUP_NAME, "Unknown") for d in discussions)

    logger.info(f"Identifying merge groups for {len(discussions)} discussions " f"from {len(groups)} groups (threshold: {similarity_threshold})")

    # Format prompt
    formatted_discussions = _format_discussions_for_prompt(discussions)
    prompt = IDENTIFY_MERGE_GROUPS_PROMPT.format(
        num_discussions=len(discussions),
        num_groups=len(groups),
        similarity_threshold=similarity_threshold,
        formatted_discussions=formatted_discussions,
    )

    # Call LLM
    llm_caller = get_llm_caller()

    try:
        settings = get_settings()
        response = await llm_caller.call_with_json_output(
            purpose=LlmInputPurposes.MERGE_SIMILAR_DISCUSSIONS,
            prompt=prompt,
            model=settings.llm.merger_model,
        )

        # Parse response
        merge_groups_data = response.get(MergeGroupKeys.MERGE_GROUPS, [])
        standalone_ids = response.get(MergeGroupKeys.STANDALONE_IDS, [])

        # Convert to MergeGroup objects
        merge_groups = []
        for mg in merge_groups_data:
            merge_groups.append(
                MergeGroup(
                    suggested_title=mg.get(MergeGroupKeys.SUGGESTED_TITLE, "Merged Discussion"),
                    discussion_ids=mg.get(MergeGroupKeys.DISCUSSION_IDS, []),
                    source_groups=mg.get(DiscussionKeys.SOURCE_GROUPS, []),
                    merge_confidence=mg.get(DiscussionKeys.MERGE_CONFIDENCE, "medium"),
                    reasoning=mg.get(MergeGroupKeys.REASONING, ""),
                )
            )

        logger.info(f"LLM identified {len(merge_groups)} merge groups, " f"{len(standalone_ids)} standalone discussions")

        return merge_groups, standalone_ids

    except Exception as e:
        logger.error(f"Failed to identify merge groups: {e}", exc_info=True)
        raise


def _format_candidates_for_validation(candidates: list[dict[str, Any]], discussions: list[dict[str, Any]]) -> str:
    """Format embedding similarity candidates for LLM validation."""
    # Build discussion lookup
    disc_lookup = {d.get(DiscussionKeys.ID): d for d in discussions}

    lines = []
    for i, candidate in enumerate(candidates, 1):
        disc1_id = candidate["disc1_id"]
        disc2_id = candidate["disc2_id"]
        disc1 = disc_lookup.get(disc1_id, {})
        disc2 = disc_lookup.get(disc2_id, {})

        similarity = candidate["similarity"]

        lines.append(f"**Pair {i}** (Cosine similarity: {similarity:.3f})")
        lines.append(f"  Discussion A (from {disc1.get(DiscussionKeys.GROUP_NAME, 'Unknown')}):")
        lines.append(f"    ID: {disc1_id}")
        lines.append(f"    Title: {disc1.get(DiscussionKeys.TITLE, 'Untitled')}")
        lines.append(f"    Summary: {disc1.get(DiscussionKeys.NUTSHELL, '')[:150]}...")
        lines.append("")
        lines.append(f"  Discussion B (from {disc2.get(DiscussionKeys.GROUP_NAME, 'Unknown')}):")
        lines.append(f"    ID: {disc2_id}")
        lines.append(f"    Title: {disc2.get(DiscussionKeys.TITLE, 'Untitled')}")
        lines.append(f"    Summary: {disc2.get(DiscussionKeys.NUTSHELL, '')[:150]}...")
        lines.append("")

    return "\n".join(lines)


def _parse_llm_merge_response(response: dict[str, Any]) -> list[MergeGroup]:
    """Parse LLM response into MergeGroup objects."""
    merge_groups = []

    for mg in response.get(MergeGroupKeys.MERGE_GROUPS, []):
        merge_groups.append(
            MergeGroup(
                suggested_title=mg.get(MergeGroupKeys.SUGGESTED_TITLE, "Merged Discussion"),
                discussion_ids=mg.get(MergeGroupKeys.DISCUSSION_IDS, []),
                source_groups=mg.get(DiscussionKeys.SOURCE_GROUPS, []),
                merge_confidence=mg.get(DiscussionKeys.MERGE_CONFIDENCE, "medium"),
                reasoning=mg.get(MergeGroupKeys.REASONING, ""),
            )
        )

    return merge_groups


async def identify_merge_groups_hybrid(discussions: list[dict[str, Any]], similarity_threshold: str = DEFAULT_SIMILARITY_THRESHOLD, use_embeddings: bool = True) -> tuple[list[MergeGroup], list[str]]:
    """
    Hybrid approach: Embedding pre-filter + LLM validation.

    Steps:
    1. Generate embeddings for all discussions (title + nutshell)
    2. Compute pairwise cosine similarities
    3. Pre-filter: Only high-similarity pairs (>threshold) sent to LLM
    4. LLM validates semantic overlap and generates merge groups

    Args:
        discussions: List of discussion dicts with id, title, nutshell, group_name
        similarity_threshold: "strict" | "moderate" | "aggressive"
        use_embeddings: If False, fall back to LLM-only approach

    Returns:
        Tuple of (merge_groups, standalone_ids)

    Cost optimization:
        - Embeddings: ~$0.0001/discussion
        - LLM validation: Only for high-similarity pairs (90% reduction)
        - Total: $0.05/run vs $0.50/run (LLM-only)
    """
    if len(discussions) < 2:
        logger.info("Less than 2 discussions - nothing to merge")
        return [], [d.get(DiscussionKeys.ID) for d in discussions]

    if not use_embeddings:
        logger.info("Embeddings disabled - using LLM-only approach")
        return await identify_merge_groups(discussions, similarity_threshold)

    logger.info(f"Hybrid merging: {len(discussions)} discussions, " f"threshold={similarity_threshold}")

    try:
        from utils.embedding import EmbeddingProviderFactory

        embedder = EmbeddingProviderFactory.create()

        # Step 1: Generate embeddings (batch for efficiency)
        texts = [f"{d[DiscussionKeys.TITLE]}. {d[DiscussionKeys.NUTSHELL]}" for d in discussions]
        embeddings = embedder.embed_texts_batch(texts)

        if not embeddings or not any(embeddings):
            logger.warning("Embedding generation failed - falling back to LLM-only")
            return await identify_merge_groups(discussions, similarity_threshold)

        # Step 2: Find candidate pairs above threshold
        embedding_threshold = EMBEDDING_THRESHOLDS[similarity_threshold]
        candidates = []

        for i, j in combinations(range(len(discussions)), 2):
            # Only compare across different groups (no self-merging)
            if discussions[i][DiscussionKeys.GROUP_NAME] == discussions[j][DiscussionKeys.GROUP_NAME]:
                continue

            # Skip if either embedding failed
            if not embeddings[i] or not embeddings[j]:
                continue

            similarity = embedder.compute_similarity(embeddings[i], embeddings[j])

            if similarity >= embedding_threshold:
                candidates.append({"disc1_id": discussions[i][DiscussionKeys.ID], "disc2_id": discussions[j][DiscussionKeys.ID], "disc1_title": discussions[i][DiscussionKeys.TITLE], "disc2_title": discussions[j][DiscussionKeys.TITLE], "similarity": similarity, "groups": [discussions[i][DiscussionKeys.GROUP_NAME], discussions[j][DiscussionKeys.GROUP_NAME]]})

        logger.info(f"Embedding pre-filter: {len(candidates)} candidate pairs " f"(from {len(discussions)} discussions, threshold={embedding_threshold:.2f})")

        # Step 3: If no candidates, all are standalone
        if not candidates:
            logger.info("No similar pairs found - all discussions standalone")
            return [], [d[DiscussionKeys.ID] for d in discussions]

        # Step 4: Send only candidates to LLM for validation
        formatted_candidates = _format_candidates_for_validation(candidates, discussions)

        prompt = VALIDATE_MERGE_CANDIDATES_PROMPT.format(num_candidates=len(candidates), embedding_threshold=embedding_threshold, similarity_threshold=similarity_threshold, formatted_candidates=formatted_candidates)

        llm_caller = get_llm_caller()
        settings = get_settings()

        response = await llm_caller.call_with_json_output(
            purpose=LlmInputPurposes.MERGE_SIMILAR_DISCUSSIONS,
            prompt=prompt,
            model=settings.llm.merger_model,
        )

        # Parse LLM response
        merge_groups = _parse_llm_merge_response(response)

        # Get standalone IDs (discussions not in any merge group)
        merged_ids = set()
        for mg in merge_groups:
            merged_ids.update(mg.discussion_ids)
        standalone_ids = [d[DiscussionKeys.ID] for d in discussions if d[DiscussionKeys.ID] not in merged_ids]

        # Add similarity metadata to merge groups
        for mg in merge_groups:
            mg.metadata = {"embedding_similarities": [c["similarity"] for c in candidates if c["disc1_id"] in mg.discussion_ids or c["disc2_id"] in mg.discussion_ids]}

        logger.info(f"LLM validation: {len(merge_groups)} merge groups, " f"{len(standalone_ids)} standalone discussions. " f"Cost savings: {(1 - len(candidates) / len(discussions)**2) * 100:.1f}%")

        return merge_groups, standalone_ids

    except Exception as e:
        logger.error(f"Hybrid merging failed: {e}", exc_info=True)
        raise


async def _generate_merged_title(
    source_discussions: list[dict[str, Any]],
    suggested_title: str,
) -> str:
    """Generate a comprehensive title for merged discussions."""
    titles = [d.get(DiscussionKeys.TITLE, "Untitled") for d in source_discussions]

    # If suggested title is good, use it
    if suggested_title and len(suggested_title) > 5:
        return suggested_title

    # Otherwise, ask LLM
    prompt = GENERATE_MERGED_TITLE_PROMPT.format(titles=json.dumps(titles, ensure_ascii=False))

    llm_caller = get_llm_caller()

    try:
        settings = get_settings()
        response = await llm_caller.call_simple(
            purpose=LlmInputPurposes.GENERATE_MERGED_TITLE,
            prompt=prompt,
            model=settings.llm.merger_model_mini,
        )
        return response.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Failed to generate merged title: {e}")
        # Fallback: combine first two titles
        return f"{titles[0]} + {titles[1]}" if len(titles) > 1 else titles[0]


async def _synthesize_merged_nutshell(
    source_discussions: list[dict[str, Any]],
    merged_title: str,
) -> str:
    """Synthesize a comprehensive nutshell from multiple source discussions."""
    formatted_sources = _format_sources_for_synthesis(source_discussions)

    prompt = SYNTHESIZE_MERGED_NUTSHELL_PROMPT.format(
        merged_title=merged_title,
        formatted_sources=formatted_sources,
    )

    llm_caller = get_llm_caller()

    try:
        settings = get_settings()
        response = await llm_caller.call_simple(
            purpose=LlmInputPurposes.SYNTHESIZE_MERGED_NUTSHELL,
            prompt=prompt,
            model=settings.llm.merger_model,
        )
        return response.strip()
    except Exception as e:
        logger.warning(f"Failed to synthesize merged nutshell: {e}")
        # Fallback: concatenate original nutshells
        nutshells = [d.get(DiscussionKeys.NUTSHELL, "") for d in source_discussions]
        return " | ".join(filter(None, nutshells))


def _merge_messages(source_discussions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge messages from multiple discussions, preserving source attribution.

    Messages are sorted chronologically by timestamp.
    """
    all_messages = []

    for disc in source_discussions:
        group_name = disc.get(DiscussionKeys.GROUP_NAME, "Unknown")
        disc_id = disc.get(DiscussionKeys.ID, "unknown")

        for msg in disc.get(DiscussionKeys.MESSAGES, []):
            # Add source attribution to message
            enriched_msg = {**msg}
            enriched_msg["_source_group"] = group_name
            enriched_msg["_source_discussion_id"] = disc_id
            all_messages.append(enriched_msg)

    # Sort by timestamp
    all_messages.sort(key=lambda m: m.get("timestamp", 0))

    return all_messages


def _get_unique_participants(messages: list[dict[str, Any]]) -> int:
    """Count unique participants across all messages."""
    participants = set()
    for msg in messages:
        sender = msg.get("sender") or msg.get("sender_name") or msg.get("author")
        if sender:
            participants.add(sender)
    return len(participants)


async def merge_discussions(
    discussions: list[dict[str, Any]],
    merge_groups: list[MergeGroup],
    standalone_ids: list[str],
) -> MergeResult:
    """
    Execute the merge operation, creating super discussions.

    Args:
        discussions: All original discussions
        merge_groups: Groups identified for merging
        standalone_ids: IDs of discussions that stay standalone

    Returns:
        MergeResult with merged + standalone discussions
    """
    # Build lookup for quick access
    disc_by_id = {d.get(DiscussionKeys.ID): d for d in discussions}

    result_discussions = []
    merge_operations = 0

    # Process merge groups
    for i, mg in enumerate(merge_groups, 1):
        source_discs = [disc_by_id[did] for did in mg.discussion_ids if did in disc_by_id]

        if len(source_discs) < 2:
            logger.warning(f"Merge group {i} has <2 valid discussions, skipping")
            # Add as standalone
            for disc in source_discs:
                result_discussions.append(_to_standalone_dict(disc))
            continue

        logger.info(f"Merging {len(source_discs)} discussions: " f"{[d.get(DiscussionKeys.TITLE, 'Untitled')[:30] for d in source_discs]}")

        # Generate merged title
        merged_title = await _generate_merged_title(source_discs, mg.suggested_title)

        # Merge messages
        merged_messages = _merge_messages(source_discs)

        # Synthesize nutshell
        merged_nutshell = await _synthesize_merged_nutshell(source_discs, merged_title)

        # Build source_discussions metadata
        source_metadata = [
            {
                DiscussionKeys.ID: d.get(DiscussionKeys.ID),
                "group": d.get(DiscussionKeys.GROUP_NAME, "Unknown"),
                "original_title": d.get(DiscussionKeys.TITLE, "Untitled"),
                DiscussionKeys.FIRST_MESSAGE_TIMESTAMP: (d.get(DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP, 0) or d.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP, 0) or 0),
            }
            for d in source_discs
        ]

        # Get earliest timestamp
        first_timestamp = min(d.get(DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP, 0) or d.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP, 0) or 0 for d in source_discs)

        # Create merged discussion
        merged_disc = {
            DiscussionKeys.ID: f"merged_discussion_{i}",
            DiscussionKeys.IS_MERGED: True,
            DiscussionKeys.TITLE: merged_title,
            DiscussionKeys.SOURCE_DISCUSSIONS: source_metadata,
            DiscussionKeys.SOURCE_GROUPS: list(set(d.get(DiscussionKeys.GROUP_NAME) for d in source_discs)),
            DiscussionKeys.MESSAGES: merged_messages,
            DiscussionKeys.NUTSHELL: merged_nutshell,
            DiscussionKeys.NUM_MESSAGES: len(merged_messages),
            DiscussionKeys.NUM_UNIQUE_PARTICIPANTS: _get_unique_participants(merged_messages),
            DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP: first_timestamp,
            DiscussionKeys.FIRST_MESSAGE_TIMESTAMP: first_timestamp,
            DiscussionKeys.MERGE_REASONING: mg.reasoning,
            DiscussionKeys.MERGE_CONFIDENCE: mg.merge_confidence,
        }

        result_discussions.append(merged_disc)
        merge_operations += 1

    # Add standalone discussions
    for disc_id in standalone_ids:
        if disc_id in disc_by_id:
            result_discussions.append(_to_standalone_dict(disc_by_id[disc_id]))

    # Sort by first message timestamp
    result_discussions.sort(
        key=lambda d: d.get(DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP, 0) or d.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP, 0),
        reverse=True,  # Most recent first
    )

    return MergeResult(
        discussions=result_discussions,
        original_count=len(discussions),
        merged_count=len(result_discussions),
        merge_operations=merge_operations,
        merge_groups=merge_groups,
    )


def _to_standalone_dict(disc: dict[str, Any]) -> dict[str, Any]:
    """Convert a discussion to standalone format with is_merged=False."""
    return {
        **disc,
        DiscussionKeys.IS_MERGED: False,
        DiscussionKeys.SOURCE_DISCUSSIONS: None,
        DiscussionKeys.MERGE_REASONING: None,
    }


class DiscussionMerger:
    """
    Orchestrates the full discussion merging pipeline.

    Supports two modes:
    - Hybrid (default): Embedding pre-filter + LLM validation (90% cost savings)
    - LLM-only: Direct LLM analysis of all discussions

    Usage:
        # Hybrid mode (recommended)
        merger = DiscussionMerger(similarity_threshold="moderate", use_hybrid=True)
        result = merger.merge(discussions)

        # LLM-only mode (legacy)
        merger = DiscussionMerger(similarity_threshold="moderate", use_hybrid=False)
        result = merger.merge(discussions)
    """

    def __init__(
        self,
        similarity_threshold: str = DEFAULT_SIMILARITY_THRESHOLD,
        enabled: bool = True,
        use_hybrid: bool = True,
    ):
        """
        Initialize the discussion merger.

        Args:
            similarity_threshold: "strict" | "moderate" | "aggressive"
            enabled: If False, skip merging entirely
            use_hybrid: Use embedding pre-filter + LLM validation (default: True)
        """
        self.similarity_threshold = similarity_threshold
        self.enabled = enabled
        self.use_hybrid = use_hybrid

    async def merge(self, discussions: list[dict[str, Any]]) -> MergeResult:
        """
        Execute the full merge pipeline.

        Args:
            discussions: List of discussion dictionaries

        Returns:
            MergeResult with merged and standalone discussions
        """
        if not self.enabled:
            logger.info("Discussion merging disabled - passing through unchanged")
            return MergeResult(
                discussions=[_to_standalone_dict(d) for d in discussions],
                original_count=len(discussions),
                merged_count=len(discussions),
                merge_operations=0,
                merge_groups=[],
            )

        if len(discussions) < 2:
            logger.info("Less than 2 discussions - nothing to merge")
            return MergeResult(
                discussions=[_to_standalone_dict(d) for d in discussions],
                original_count=len(discussions),
                merged_count=len(discussions),
                merge_operations=0,
                merge_groups=[],
            )

        # Step 1: Identify merge groups (hybrid or LLM-only)
        if self.use_hybrid:
            merge_groups, standalone_ids = await identify_merge_groups_hybrid(discussions, self.similarity_threshold, use_embeddings=True)
        else:
            merge_groups, standalone_ids = await identify_merge_groups(
                discussions,
                self.similarity_threshold,
            )

        # Step 2: Execute merges
        result = await merge_discussions(discussions, merge_groups, standalone_ids)

        logger.info(f"Discussion merging complete: {result.original_count} → {result.merged_count} " f"({result.merge_operations} merge operations)")

        return result
