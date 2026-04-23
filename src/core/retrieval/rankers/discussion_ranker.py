"""
Discussion Ranker - Business Logic

This module contains the core ranking logic for discussions.
It analyzes discussions and produces insights about which should be featured
in which newsletter sections and why.

The ranker considers multiple factors:
- Discussion relevance and importance (50%)
- Technical depth and quality (30%)
- Community engagement - number of messages (10%)
- Number of unique participants (10% - LOW weight)
- Topical diversity for the newsletter
- Recency and timeliness
- Repetition with previous newsletters (anti-repetition feature)

Note: The LangGraph subgraph wrapper is in graphs/subgraphs/discussions_ranker.py.
This module provides the pure business logic that the subgraph invokes.

Instrumented with Langfuse for tracing and cost tracking.
"""

import os
import logging
import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from utils.llm.chat_model_factory import create_chat_model
from utils.llm.json_parser import parse_json_response

from config import get_settings
from constants import DiscussionCategory, MessageRole
from observability.llm import get_langfuse_callback_handler, is_langfuse_enabled
from utils.llm.prompts.ranking.rank_discussions import (
    RANK_DISCUSSIONS_PROMPT,
    REPETITION_ANALYSIS_SECTION,
    NO_PREVIOUS_NEWSLETTERS_SECTION,
    SLM_ENRICHMENT_SECTION,
    NO_SLM_ENRICHMENT_SECTION,
)
from core.retrieval.history.newsletter_history_loader import (
    PreviousNewslettersContext,
    format_previous_context_for_prompt,
)
from core.retrieval.rankers.mmr_reranker import rank_with_mmr
from custom_types.field_keys import DiscussionKeys, RankingResultKeys


logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS (defaults can be overridden via config)
# ============================================================================



# Build LangChain ChatPromptTemplate from the prompt string
DISCUSSION_RANKING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (MessageRole.SYSTEM, RANK_DISCUSSIONS_PROMPT),
        (
            MessageRole.USER,
            """Analyze these discussions and provide ranking recommendations:

{discussions_json}

Remember to output valid JSON only, no additional text.""",
        ),
    ]
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def load_discussions(discussions_file: str) -> list[dict[str, Any]]:
    """
    Load and parse discussions from JSON file.

    Args:
        discussions_file: Path to the discussions JSON file

    Returns:
        List of discussion dictionaries

    Raises:
        FileNotFoundError: If file doesn't exist
        RuntimeError: If file can't be parsed
    """
    if not os.path.exists(discussions_file):
        raise FileNotFoundError(f"Discussions file not found: {discussions_file}")

    try:
        with open(discussions_file, encoding="utf-8") as f:
            discussions_data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse discussions JSON: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to read discussions file: {e}")

    return discussions_data.get(DiscussionKeys.DISCUSSIONS, [])


def count_unique_participants(discussion: dict[str, Any]) -> int:
    """
    Count the number of unique participants in a discussion.

    Args:
        discussion: Discussion object containing messages

    Returns:
        Number of unique sender_ids in the discussion
    """
    try:
        sender_ids = set()
        for msg in discussion.get(DiscussionKeys.MESSAGES, []):
            sender_id = msg.get("sender_id")
            if sender_id:
                sender_ids.add(sender_id)
        return len(sender_ids)
    except Exception as e:
        logger.error(f"Unexpected error counting unique participants: {e}, discussion_id={discussion.get(DiscussionKeys.ID)}")
        raise RuntimeError(f"Failed to count unique participants: {e}") from e


def prepare_discussions_for_llm(discussions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Prepare discussions for LLM analysis by extracting key fields.

    This reduces token usage by removing full message content and keeping
    only essential metadata and sample messages.

    For merged discussions, includes source_discussions metadata to enable
    multi-group attribution in the final newsletter.

    Args:
        discussions: List of full discussion objects

    Returns:
        List of summarized discussion objects suitable for LLM input
    """
    try:
        discussions_summary = []
        for disc in discussions:
            summary = {
                DiscussionKeys.ID: disc.get(DiscussionKeys.ID),
                DiscussionKeys.TITLE: disc.get(DiscussionKeys.TITLE),
                DiscussionKeys.NUTSHELL: disc.get(DiscussionKeys.NUTSHELL),
                DiscussionKeys.NUM_MESSAGES: disc.get(DiscussionKeys.NUM_MESSAGES),
                DiscussionKeys.NUM_UNIQUE_PARTICIPANTS: count_unique_participants(disc),
                DiscussionKeys.FIRST_MESSAGE_TIMESTAMP: disc.get(DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP),
                # Include first and last message content for context
                DiscussionKeys.SAMPLE_MESSAGES: [disc[DiscussionKeys.MESSAGES][0].get("content", "") if disc.get(DiscussionKeys.MESSAGES) else "", disc[DiscussionKeys.MESSAGES][-1].get("content", "") if disc.get(DiscussionKeys.MESSAGES) and len(disc[DiscussionKeys.MESSAGES]) > 1 else ""],
            }

            # Add merged discussion metadata if present
            if disc.get(DiscussionKeys.IS_MERGED, False):
                summary[DiscussionKeys.IS_MERGED] = True
                summary[DiscussionKeys.SOURCE_DISCUSSIONS] = disc.get(DiscussionKeys.SOURCE_DISCUSSIONS, [])
                summary[DiscussionKeys.SOURCE_GROUPS] = disc.get(DiscussionKeys.SOURCE_GROUPS, [])
                summary[DiscussionKeys.MERGE_REASONING] = disc.get(DiscussionKeys.MERGE_REASONING, "")

            discussions_summary.append(summary)

        return discussions_summary
    except Exception as e:
        logger.error(f"Unexpected error preparing discussions for LLM: {e}, num_discussions={len(discussions)}")
        raise RuntimeError(f"Failed to prepare discussions for LLM: {e}") from e


def _build_repetition_analysis_section(previous_context: PreviousNewslettersContext | None) -> str:
    """
    Build the repetition analysis section for the ranking prompt.

    Args:
        previous_context: Context from previous newsletters

    Returns:
        Formatted repetition analysis section for prompt injection
    """
    try:
        if not previous_context or not previous_context.newsletters:
            return NO_PREVIOUS_NEWSLETTERS_SECTION

        formatted_topics = format_previous_context_for_prompt(previous_context)
        return REPETITION_ANALYSIS_SECTION.format(num_previous_newsletters=len(previous_context.newsletters), formatted_previous_topics=formatted_topics)
    except Exception as e:
        logger.error(f"Unexpected error building repetition analysis section: {e}")
        raise RuntimeError(f"Failed to build repetition analysis section: {e}") from e


async def rank_with_llm(
    discussions_summary: list[dict[str, Any]],
    summary_format: str,
    previous_newsletter_context: PreviousNewslettersContext | None = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Use LLM to rank and categorize discussions.

    This function is the core LLM interaction. Can be modified or replaced
    with alternative ranking strategies (e.g., rule-based, ML model).

    Args:
        discussions_summary: Prepared discussion summaries
        summary_format: Newsletter format for context
        previous_newsletter_context: Context from previous newsletters for anti-repetition
        trace_id: Langfuse trace ID for hierarchical tracing
        session_id: Langfuse session ID for grouping traces
        user_id: User identifier (e.g., data_source_name)

    Returns:
        Ranking result dictionary with ranked_discussions, editorial_notes, etc.

    Raises:
        RuntimeError: If LLM initialization or invocation fails
    """
    discussions_json = json.dumps(discussions_summary, indent=2)

    # Build SLM enrichment section (detect if messages have slm_active_labels)
    has_enrichment = any(
        msg.get("slm_active_labels")
        for disc in discussions_summary
        for msg in disc.get("messages", [])
    )
    enrichment_section = SLM_ENRICHMENT_SECTION if has_enrichment else NO_SLM_ENRICHMENT_SECTION
    if has_enrichment:
        logger.info("SLM enrichment labels detected on messages, including in ranking prompt")

    # Build repetition analysis section
    repetition_section = _build_repetition_analysis_section(previous_newsletter_context)

    # Log anti-repetition status
    if previous_newsletter_context and previous_newsletter_context.newsletters:
        logger.info(f"Anti-repetition enabled: {len(previous_newsletter_context.newsletters)} " f"previous newsletters loaded")
    else:
        logger.info("Anti-repetition disabled or no previous newsletters found")

    # Initialize LLM
    try:
        settings = get_settings()
        llm = create_chat_model(model=settings.llm.ranking_model, temperature=settings.llm.temperature_ranking, model_kwargs={"response_format": {"type": "json_object"}})
    except Exception as e:
        raise RuntimeError(f"Failed to initialize LLM client: {e}")

    # Create prompt chain
    chain = DISCUSSION_RANKING_PROMPT | llm

    # Setup Langfuse callback for tracing
    callbacks = []
    if is_langfuse_enabled() and trace_id:
        callback = get_langfuse_callback_handler(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            tags=["ranking", "discussion_analysis"],
            metadata={
                "num_discussions": len(discussions_summary),
                "summary_format": summary_format,
                "has_repetition_context": bool(previous_newsletter_context and previous_newsletter_context.newsletters),
            },
        )
        if callback:
            callbacks.append(callback)

    # Invoke LLM
    logger.info(f"Analyzing {len(discussions_summary)} discussions with LLM...")
    try:
        invoke_config = {"callbacks": callbacks} if callbacks else {}
        response = await chain.ainvoke({"discussions_json": discussions_json, "summary_format": summary_format, "repetition_analysis_section": repetition_section, "slm_enrichment_section": enrichment_section}, config=invoke_config)

        # Parse LLM response (handles markdown fences, preamble text from non-OpenAI providers)
        ranking_result = parse_json_response(response.content)

        # Validate response structure
        if RankingResultKeys.RANKED_DISCUSSIONS not in ranking_result:
            raise ValueError(f"LLM response missing '{RankingResultKeys.RANKED_DISCUSSIONS}' field")

        logger.info(f"Successfully ranked {len(ranking_result[RankingResultKeys.RANKED_DISCUSSIONS])} discussions")

        # Log repetition detections
        repetition_counts = {"high": 0, "medium": 0, "low": 0}
        for disc in ranking_result.get(RankingResultKeys.RANKED_DISCUSSIONS, []):
            rep_score = disc.get(RankingResultKeys.REPETITION_SCORE)
            if rep_score in repetition_counts:
                repetition_counts[rep_score] += 1

        if any(repetition_counts.values()):
            logger.info(f"Repetition detected: {repetition_counts['high']} high, " f"{repetition_counts['medium']} medium, {repetition_counts['low']} low")

        return ranking_result

    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse LLM response as JSON: {e}")
    except Exception as e:
        raise RuntimeError(f"LLM analysis failed: {e}")


def enrich_ranking_with_metadata(ranking_result: dict[str, Any], original_discussions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Enrich ranked discussions with metadata from original discussions.

    This ensures critical fields like num_messages, num_unique_participants,
    and first_message_timestamp are always present, even if the LLM doesn't include them.

    Args:
        ranking_result: LLM ranking output
        original_discussions: Original discussion data for metadata lookup

    Returns:
        Enriched ranking result
    """
    try:
        # Create a lookup dict for easy access to original discussion data
        discussions_lookup = {disc.get(DiscussionKeys.ID): disc for disc in original_discussions}

        for ranked_disc in ranking_result.get(RankingResultKeys.RANKED_DISCUSSIONS, []):
            disc_id = ranked_disc.get(RankingResultKeys.DISCUSSION_ID)
            if disc_id in discussions_lookup:
                original_disc = discussions_lookup[disc_id]
                # If num_messages is missing, add it from original data
                if DiscussionKeys.NUM_MESSAGES not in ranked_disc:
                    ranked_disc[DiscussionKeys.NUM_MESSAGES] = original_disc.get(DiscussionKeys.NUM_MESSAGES, 0)
                # If num_unique_participants is missing, calculate it from original data
                if DiscussionKeys.NUM_UNIQUE_PARTICIPANTS not in ranked_disc:
                    ranked_disc[DiscussionKeys.NUM_UNIQUE_PARTICIPANTS] = count_unique_participants(original_disc)
                # If first_message_timestamp is missing, add it from original data
                if DiscussionKeys.FIRST_MESSAGE_TIMESTAMP not in ranked_disc:
                    ranked_disc[DiscussionKeys.FIRST_MESSAGE_TIMESTAMP] = original_disc.get(DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP)

        return ranking_result
    except Exception as e:
        logger.error(f"Unexpected error enriching ranking with metadata: {e}")
        raise RuntimeError(f"Failed to enrich ranking with metadata: {e}") from e


def apply_mmr_reranking(ranking_result: dict[str, Any], original_discussions: list[dict[str, Any]], enable_mmr: bool = True, mmr_lambda: float = 0.7) -> dict[str, Any]:
    """
    Apply MMR diversity reranking to LLM-ranked discussions.

    Args:
        ranking_result: LLM ranking output with ranked_discussions
        original_discussions: Original discussions (with embeddings if available)
        enable_mmr: Enable MMR reranking (default: True)
        mmr_lambda: MMR balance (0-1, default: 0.7 = 70% quality, 30% diversity)

    Returns:
        Updated ranking_result with MMR-reranked discussions
    """
    try:
        if not enable_mmr:
            return ranking_result

        ranked_discussions = ranking_result.get(RankingResultKeys.RANKED_DISCUSSIONS, [])
        if len(ranked_discussions) < 2:
            return ranking_result

        # Extract quality scores and prepare discussions with embeddings
        quality_scores = [disc.get(RankingResultKeys.RANKING_SCORE, 0.0) for disc in ranked_discussions]
        discussions_lookup = {disc.get(DiscussionKeys.ID): disc for disc in original_discussions}

        discussions_with_embeddings = []
        for ranked_disc in ranked_discussions:
            disc_copy = ranked_disc.copy()
            disc_id = ranked_disc.get(RankingResultKeys.DISCUSSION_ID)
            if disc_id in discussions_lookup and DiscussionKeys.EMBEDDING in discussions_lookup[disc_id]:
                disc_copy[DiscussionKeys.EMBEDDING] = discussions_lookup[disc_id][DiscussionKeys.EMBEDDING]
            discussions_with_embeddings.append(disc_copy)

        # Apply MMR
        mmr_ranked = rank_with_mmr(discussions=discussions_with_embeddings, quality_scores=quality_scores, top_k=len(discussions_with_embeddings), lambda_param=mmr_lambda, use_embeddings=True)

        ranking_result[RankingResultKeys.RANKED_DISCUSSIONS] = mmr_ranked
        return ranking_result

    except Exception as e:
        logger.error(f"MMR reranking failed: {e}, continuing with quality-only", exc_info=True)
        return ranking_result


def apply_top_k_categorization(ranking_result: dict[str, Any], top_k: int, original_discussions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Apply top-k categorization to ranked discussions and create convenience lists.

    This post-processes the LLM ranking output to:
    1. Categorize discussions as 'featured' (rank <= top_k) or 'brief_mention' (rank > top_k)
    2. Exclude skipped discussions from brief_mention
    3. Create convenience lists: featured_discussion_ids, brief_mention_items

    Args:
        ranking_result: LLM ranking output with ranked_discussions
        top_k: Number of discussions to feature (the rest become brief_mention)
        original_discussions: Original discussion data for metadata lookup

    Returns:
        Enhanced ranking result with categorization and convenience lists
    """
    try:
        ranked_discussions = ranking_result.get(RankingResultKeys.RANKED_DISCUSSIONS, [])

        # Create lookup for original discussion data (for title fallback)
        discussions_lookup = {disc.get(DiscussionKeys.ID): disc for disc in original_discussions}

        featured_discussion_ids = []
        brief_mention_items = []

        for disc in ranked_discussions:
            rank = disc.get(RankingResultKeys.RANK, 999)
            disc_id = disc.get(RankingResultKeys.DISCUSSION_ID)
            skip_reason = disc.get(RankingResultKeys.SKIP_REASON)

            # Get title from ranking result or fall back to original
            title = disc.get(DiscussionKeys.TITLE)
            if not title and disc_id in discussions_lookup:
                title = discussions_lookup[disc_id].get(DiscussionKeys.TITLE, "Unknown")

            # Apply categorization based on rank and skip status
            if skip_reason:
                disc[RankingResultKeys.CATEGORY] = DiscussionCategory.SKIP
            elif rank <= top_k:
                disc[RankingResultKeys.CATEGORY] = DiscussionCategory.FEATURED
                featured_discussion_ids.append(disc_id)
            else:
                disc[RankingResultKeys.CATEGORY] = DiscussionCategory.BRIEF_MENTION
                # Add to brief_mention_items for content generator
                one_liner = disc.get(RankingResultKeys.ONE_LINER_SUMMARY, "")
                importance = disc.get(RankingResultKeys.IMPORTANCE_SCORE, 0)
                if one_liner and importance >= 5:  # Only include quality brief mentions
                    brief_mention_items.append(
                        {
                            RankingResultKeys.DISCUSSION_ID: disc_id,
                            DiscussionKeys.TITLE: title,
                            "one_liner": one_liner,
                            # Include repetition data for filtering in content generator
                            RankingResultKeys.REPETITION_SCORE: disc.get(RankingResultKeys.REPETITION_SCORE),
                            RankingResultKeys.REPETITION_IDENTIFICATION_REASONING: disc.get(RankingResultKeys.REPETITION_IDENTIFICATION_REASONING),
                        }
                    )

        # Add convenience lists to result
        ranking_result[RankingResultKeys.FEATURED_DISCUSSION_IDS] = featured_discussion_ids
        ranking_result[RankingResultKeys.BRIEF_MENTION_ITEMS] = brief_mention_items
        ranking_result[RankingResultKeys.TOP_K_APPLIED] = top_k

        logger.info(f"Applied top-k={top_k} categorization: " f"{len(featured_discussion_ids)} featured, " f"{len(brief_mention_items)} brief_mention, " f"{len([d for d in ranked_discussions if d.get(RankingResultKeys.CATEGORY) == DiscussionCategory.SKIP])} skipped")

        return ranking_result
    except Exception as e:
        logger.error(f"Unexpected error applying top-k categorization: {e}, top_k={top_k}")
        raise RuntimeError(f"Failed to apply top-k categorization: {e}") from e


def save_ranking_result(ranking_result: dict[str, Any], output_file: str) -> None:
    """
    Save ranking result to JSON file.

    Args:
        ranking_result: Ranking data to save
        output_file: Path to output file

    Raises:
        RuntimeError: If file write fails
    """
    try:
        output_dir = os.path.dirname(output_file)
        os.makedirs(output_dir, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(ranking_result, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully saved discussion rankings to: {output_file}")
    except Exception as e:
        logger.error(f"Failed to save ranking result: {e}, output_file={output_file}")
        raise RuntimeError(f"Failed to write ranking results to {output_file}: {e}") from e


# ============================================================================
# HIGH-LEVEL API
# ============================================================================


