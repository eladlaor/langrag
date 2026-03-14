"""
Hybrid Anti-Repetition System

Combines embedding-based similarity search with LLM semantic validation
to efficiently detect repetition with previous newsletters.

Approach:
1. Pre-compute embeddings for all historical discussions (one-time, cached in MongoDB)
2. Runtime: Embed current discussion, find top-3 most similar via cosine similarity
3. LLM validates only top-3 matches (not all 50-200 historical discussions)

Cost optimization:
- Prompt size: 3KB (top-3 matches) vs 15KB (all historical)
- 80% reduction in prompt size
- Same or better accuracy (focused validation)
"""

import logging
from datetime import datetime, UTC
from typing import Any

from config import get_settings
from utils.llm import get_llm_caller
from utils.llm.prompts.ranking.rank_discussions import VALIDATE_REPETITION_PROMPT
from constants import LlmInputPurposes, RepetitionScore
from custom_types.field_keys import DiscussionKeys, RankingResultKeys, DbFieldKeys, MergeGroupKeys

logger = logging.getLogger(__name__)

# Get defaults from config
_settings = get_settings()
DEFAULT_SIMILARITY_THRESHOLD = 0.80  # Cosine similarity threshold
DEFAULT_TOP_K_MATCHES = 3  # Number of top similar discussions to validate with LLM


def _format_repetition_validation_prompt(current_discussion: dict[str, Any], top_matches: list[dict[str, Any]]) -> str:
    """
    Format prompt for LLM validation of repetition.

    Args:
        current_discussion: Current discussion to check
        top_matches: Top-K most similar historical discussions (with similarity scores)

    Returns:
        Formatted prompt string
    """
    # Format current discussion
    current_text = f"""**Current Discussion:**
Title: {current_discussion.get(DiscussionKeys.TITLE, 'Untitled')}
Summary: {current_discussion.get(DiscussionKeys.NUTSHELL, 'No summary')}
Chat: {current_discussion.get(DbFieldKeys.CHAT_NAME, 'Unknown')}
Messages: {current_discussion.get('num_messages', 0)}"""

    # Format top matches
    matches_text = []
    for i, match in enumerate(top_matches, 1):
        similarity = match.get("similarity", 0.0)
        newsletter_date = match.get("newsletter_date", "unknown")

        matches_text.append(f"""**Similar Discussion {i}** (Similarity: {similarity:.3f}, From: {newsletter_date})
Title: {match.get(DiscussionKeys.TITLE, 'Untitled')}
Summary: {match.get(DiscussionKeys.NUTSHELL, 'No summary')}
Chat: {match.get(DbFieldKeys.CHAT_NAME, 'Unknown')}""")

    return f"""{current_text}

**Top Similar Discussions from Previous Newsletters:**
{chr(10).join(matches_text)}

Analyze if the current discussion is substantially repetitive with any of these previous discussions."""


async def check_repetition_hybrid(current_discussion: dict[str, Any], run_ids_to_check: list[str], similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD, top_k_matches: int = DEFAULT_TOP_K_MATCHES) -> dict[str, Any]:
    """
    Hybrid anti-repetition: Embedding pre-filter + LLM validation.

    Steps:
    1. Load historical discussion embeddings from MongoDB (pre-computed)
    2. Embed current discussion
    3. Find top-K most similar historical discussions (cosine similarity)
    4. Send only top-K to LLM for semantic validation

    Args:
        current_discussion: Current discussion to check
        run_ids_to_check: List of previous run_ids to check against
        similarity_threshold: Minimum cosine similarity to consider (default: 0.80)
        top_k_matches: Number of top similar discussions to validate (default: 3)

    Returns:
        {
            "repetition_score": "none" | "low" | "medium" | "high",
            "reasoning": str,
            "similar_historical": [list of top matches with similarity scores],
            "penalty_applied": float  # 0.0 to -5.0
        }

    Example:
        >>> result = await check_repetition_hybrid(
        ...     current_discussion={"title": "RAG for Books", "nutshell": "..."},
        ...     run_ids_to_check=["run_1", "run_2", "run_3"]
        ... )
        >>> print(result['repetition_score'])  # "medium"
        >>> print(result['penalty_applied'])   # -3.0
    """
    logger.info(f"Hybrid repetition check: {current_discussion.get('title', 'Untitled')}, " f"against {len(run_ids_to_check)} previous runs")

    try:
        from utils.embedding import EmbeddingProviderFactory
        from db.repositories.discussions import DiscussionsRepository
        from db.connection import get_database

        embedder = EmbeddingProviderFactory.create()

        # Step 1: Embed current discussion
        current_text = f"{current_discussion[DiscussionKeys.TITLE]}. {current_discussion[DiscussionKeys.NUTSHELL]}"
        current_embedding = embedder.embed_text(current_text)

        if not current_embedding:
            raise ValueError("Failed to generate embedding for current discussion")

        # Step 2: Load historical embeddings from MongoDB
        db = await get_database()
        repo = DiscussionsRepository(db)

        historical_discussions = await repo.get_discussions_with_embeddings(
            run_ids=run_ids_to_check,
            limit=1000,  # Should cover all historical discussions
        )

        if not historical_discussions:
            logger.info("No historical discussions with embeddings found")
            return {RankingResultKeys.REPETITION_SCORE: RepetitionScore.NONE, MergeGroupKeys.REASONING: "No historical discussions available for comparison", "similar_historical": [], "penalty_applied": 0.0}

        # Step 3: Compute similarities and find top-K matches
        similar_historical = []

        for hist_disc in historical_discussions:
            if DiscussionKeys.EMBEDDING not in hist_disc:
                logger.warning(f"Missing embedding for discussion {hist_disc[DbFieldKeys.DISCUSSION_ID]}")
                continue

            similarity = embedder.compute_similarity(current_embedding, hist_disc[DiscussionKeys.EMBEDDING])

            if similarity >= similarity_threshold:
                similar_historical.append({DbFieldKeys.DISCUSSION_ID: hist_disc[DbFieldKeys.DISCUSSION_ID], DiscussionKeys.TITLE: hist_disc[DiscussionKeys.TITLE], DiscussionKeys.NUTSHELL: hist_disc[DiscussionKeys.NUTSHELL], DbFieldKeys.CHAT_NAME: hist_disc.get(DbFieldKeys.CHAT_NAME, "Unknown"), "newsletter_date": hist_disc.get("created_at", datetime.now(UTC)).strftime("%Y-%m-%d"), "similarity": similarity})

        # Sort by similarity and take top-K
        top_matches = sorted(similar_historical, key=lambda x: x["similarity"], reverse=True)[:top_k_matches]

        logger.info(f"Found {len(top_matches)} similar historical discussions " f"(threshold: {similarity_threshold:.2f})")

        # Step 4: If no matches, no repetition
        if not top_matches:
            return {RankingResultKeys.REPETITION_SCORE: RepetitionScore.NONE, MergeGroupKeys.REASONING: "No similar historical discussions found", "similar_historical": [], "penalty_applied": 0.0}

        # Step 5: LLM validates semantic overlap (only top-K, not all 200 historical)
        prompt = _format_repetition_validation_prompt(current_discussion, top_matches)

        llm_caller = get_llm_caller()
        settings = get_settings()

        response = await llm_caller.call_with_json_output(purpose=LlmInputPurposes.CHECK_REPETITION, prompt=VALIDATE_REPETITION_PROMPT.format(formatted_comparison=prompt), model=settings.llm.ranking_model)

        # Calculate penalty based on repetition score
        penalty_map = {RepetitionScore.HIGH: -5.0, RepetitionScore.MEDIUM: -3.0, RepetitionScore.LOW: -1.0, RepetitionScore.NONE: 0.0}

        repetition_score = response.get(RankingResultKeys.REPETITION_SCORE, RepetitionScore.NONE)

        result = {RankingResultKeys.REPETITION_SCORE: repetition_score, MergeGroupKeys.REASONING: response.get(MergeGroupKeys.REASONING, ""), "similar_historical": top_matches, "penalty_applied": penalty_map.get(repetition_score, 0.0)}

        logger.info(f"Repetition check complete: {result[RankingResultKeys.REPETITION_SCORE]}, " f"penalty={result['penalty_applied']}, " f"top_similarity={top_matches[0]['similarity']:.2f}")

        return result

    except Exception as e:
        logger.error(f"Hybrid repetition check failed: {e}, returning no repetition", exc_info=True)
        # Fail-soft: assume no repetition on error
        return {RankingResultKeys.REPETITION_SCORE: RepetitionScore.NONE, MergeGroupKeys.REASONING: f"Repetition check failed: {str(e)}", "similar_historical": [], "penalty_applied": 0.0}
