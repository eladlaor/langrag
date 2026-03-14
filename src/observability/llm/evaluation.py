"""
Structural evaluation utilities for newsletter quality assessment.

This module provides automated (non-LLM) scoring for newsletter structure.
Manual quality scoring is done via Langfuse UI.

Scoring Types:
1. Structural Completeness - checks for required newsletter sections
2. Ranking Coverage - measures discussion representation
3. Content Quality Indicators - basic heuristics (word count, section balance)

All scores are in the range 0.0 to 1.0.

Usage:
    from observability.llm import (
        score_newsletter_structure,
        ScoringConfig,
    )

    # Use default weights
    result = score_newsletter_structure(trace_id, None, newsletter_result)

    # Use custom weights
    config = ScoringConfig(primary_weight=0.5, secondary_weight=0.3)
    result = score_newsletter_structure(trace_id, None, newsletter_result, config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from custom_types.field_keys import NewsletterStructureKeys
from observability.llm.langfuse_client import get_langfuse_client, is_langfuse_enabled

logger = logging.getLogger(__name__)


# ============================================================================
# SCORING CONFIGURATION
# ============================================================================


@dataclass
class ScoringConfig:
    """
    Configuration for newsletter structural scoring weights.

    All weights should sum to 1.0 for the completeness score.
    Adjust these to prioritize different aspects of newsletter quality.

    Attributes:
        primary_weight: Weight for having a primary discussion (default: 0.4)
        secondary_full_weight: Weight for having 2+ secondary discussions (default: 0.3)
        secondary_partial_weight: Weight for having exactly 1 secondary (default: 0.15)
        mentions_weight: Weight for having worth_mentioning items (default: 0.2)
        secondary_bonus_weight: Weight bonus for 3+ secondary discussions (default: 0.1)
    """

    primary_weight: float = 0.4
    secondary_full_weight: float = 0.3
    secondary_partial_weight: float = 0.15
    mentions_weight: float = 0.2
    secondary_bonus_weight: float = 0.1

    def validate(self) -> bool:
        """Check that weights are reasonable (non-negative, sum ~1.0)."""
        total = self.primary_weight + self.secondary_full_weight + self.mentions_weight + self.secondary_bonus_weight
        return (
            all(
                w >= 0
                for w in [
                    self.primary_weight,
                    self.secondary_full_weight,
                    self.secondary_partial_weight,
                    self.mentions_weight,
                    self.secondary_bonus_weight,
                ]
            )
            and 0.9 <= total <= 1.1
        )


@dataclass
class ContentBalanceConfig:
    """Configuration for content balance scoring."""

    target_primary_ratio: float = 0.4
    deviation_penalty: float = 2.0  # Multiplier for deviation from target


# Default configurations
DEFAULT_SCORING_CONFIG = ScoringConfig()
DEFAULT_BALANCE_CONFIG = ContentBalanceConfig()


# ============================================================================
# RESULT TYPES
# ============================================================================


@dataclass
class ScoringResult:
    """Result from a scoring operation."""

    score: float
    details: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"score": self.score, **self.details}
        if self.skipped:
            result["skipped"] = True
            result["reason"] = self.skip_reason
        if self.error:
            result["error"] = self.error
        return result


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _check_langfuse_available() -> tuple[bool, str | None, Any | None]:
    """
    Check if Langfuse is available for scoring.

    Returns:
        Tuple of (is_available, skip_reason, langfuse_client)
    """
    if not is_langfuse_enabled():
        return False, "Langfuse disabled", None

    langfuse = get_langfuse_client()
    if not langfuse:
        return False, "Langfuse client not available", None

    return True, None, langfuse


def _submit_score(
    langfuse,
    trace_id: str,
    observation_id: str | None,
    name: str,
    value: float,
    comment: str,
) -> None:
    """
    Submit a score to Langfuse.

    Args:
        langfuse: Langfuse client instance
        trace_id: Trace ID to attach score to
        observation_id: Optional observation ID for span-level scoring
        name: Score name
        value: Score value (0.0-1.0)
        comment: Descriptive comment
    """
    score_params = {
        "trace_id": trace_id,
        "name": name,
        "value": value,
        "comment": comment,
    }
    if observation_id:
        score_params["observation_id"] = observation_id

    langfuse.score(**score_params)


# ============================================================================
# SCORING FUNCTIONS
# ============================================================================


def score_newsletter_structure(
    trace_id: str,
    observation_id: str | None,
    result: dict[str, Any],
    config: ScoringConfig | None = None,
) -> ScoringResult:
    """
    Score newsletter structural completeness (automated - no LLM cost).

    Checks:
    - Has primary discussion (configurable weight)
    - Has 2+ secondary discussions (configurable weight)
    - Has worth_mentioning items (configurable weight)
    - Has 3+ secondary discussions (bonus weight)

    Args:
        trace_id: Langfuse trace ID to attach score
        observation_id: Optional observation ID for span-level scoring
        result: Newsletter result dict with primary_discussion, secondary_discussions, worth_mentioning
        config: Optional scoring configuration (uses defaults if not provided)

    Returns:
        ScoringResult with completeness score and breakdown
    """
    available, skip_reason, langfuse = _check_langfuse_available()
    if not available:
        return ScoringResult(score=0.0, skipped=True, skip_reason=skip_reason)

    cfg = config or DEFAULT_SCORING_CONFIG

    try:
        # Extract newsletter sections
        has_primary = bool(result.get(NewsletterStructureKeys.PRIMARY_DISCUSSION))
        secondary_discussions = result.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, [])
        secondary_count = len(secondary_discussions) if secondary_discussions else 0
        worth_mentioning = result.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
        mentions_count = len(worth_mentioning) if worth_mentioning else 0
        has_mentions = mentions_count > 0

        # Calculate weighted completeness score (0-1)
        completeness = 0.0
        if has_primary:
            completeness += cfg.primary_weight
        if secondary_count >= 2:
            completeness += cfg.secondary_full_weight
        elif secondary_count == 1:
            completeness += cfg.secondary_partial_weight
        if has_mentions:
            completeness += cfg.mentions_weight
        if secondary_count >= 3:
            completeness += cfg.secondary_bonus_weight

        # Cap at 1.0
        completeness = min(completeness, 1.0)

        # Build comment for context
        comment = f"primary={has_primary}, secondary={secondary_count}, mentions={mentions_count}"

        # Submit to Langfuse
        _submit_score(langfuse, trace_id, observation_id, "structural_completeness", completeness, comment)

        logger.info(f"Scored newsletter structure: {completeness:.2f} ({comment})")

        return ScoringResult(
            score=completeness,
            details={
                "has_primary": has_primary,
                "secondary_count": secondary_count,
                "mentions_count": mentions_count,
                "has_mentions": has_mentions,
                "comment": comment,
            },
        )

    except Exception as e:
        logger.warning(f"Failed to score newsletter structure: {e}")
        return ScoringResult(score=0.0, error=str(e))


def score_ranking_coverage(
    trace_id: str,
    observation_id: str | None,
    total_discussions: int,
    featured_count: int,
    brief_mention_count: int,
) -> ScoringResult:
    """
    Score ranking output coverage (automated - no LLM cost).

    Measures what percentage of discussions are represented in the newsletter.

    Args:
        trace_id: Langfuse trace ID
        observation_id: Optional observation ID for span-level scoring
        total_discussions: Total number of discussions available
        featured_count: Number of featured discussions
        brief_mention_count: Number of brief mention items

    Returns:
        ScoringResult with coverage score and details
    """
    available, skip_reason, langfuse = _check_langfuse_available()
    if not available:
        return ScoringResult(score=0.0, skipped=True, skip_reason=skip_reason)

    if total_discussions == 0:
        return ScoringResult(score=0.0, skipped=True, skip_reason="No discussions to score")

    try:
        coverage = (featured_count + brief_mention_count) / total_discussions
        coverage = min(coverage, 1.0)  # Cap at 1.0

        comment = f"featured={featured_count}, brief={brief_mention_count}, total={total_discussions}"

        _submit_score(langfuse, trace_id, observation_id, "ranking_coverage", coverage, comment)

        logger.info(f"Scored ranking coverage: {coverage:.2f} ({comment})")

        return ScoringResult(
            score=coverage,
            details={
                "featured_count": featured_count,
                "brief_mention_count": brief_mention_count,
                "total_discussions": total_discussions,
            },
        )

    except Exception as e:
        logger.warning(f"Failed to score ranking coverage: {e}")
        return ScoringResult(score=0.0, error=str(e))


def score_content_balance(
    trace_id: str,
    observation_id: str | None,
    primary_word_count: int,
    secondary_word_counts: list[int],
    config: ContentBalanceConfig | None = None,
) -> ScoringResult:
    """
    Score content balance between sections (automated heuristic).

    Ideal balance: primary ~40% of total content, secondaries ~60% distributed.

    Args:
        trace_id: Langfuse trace ID
        observation_id: Optional observation ID
        primary_word_count: Word count of primary discussion section
        secondary_word_counts: List of word counts for each secondary discussion
        config: Optional balance configuration

    Returns:
        ScoringResult with balance score and details
    """
    available, skip_reason, langfuse = _check_langfuse_available()
    if not available:
        return ScoringResult(score=0.0, skipped=True, skip_reason=skip_reason)

    cfg = config or DEFAULT_BALANCE_CONFIG

    try:
        total_secondary = sum(secondary_word_counts) if secondary_word_counts else 0
        total_words = primary_word_count + total_secondary

        if total_words == 0:
            return ScoringResult(score=0.0, skipped=True, skip_reason="No content to score")

        actual_primary_ratio = primary_word_count / total_words

        # Score based on deviation from target ratio (0-1)
        deviation = abs(actual_primary_ratio - cfg.target_primary_ratio)
        balance_score = max(0, 1 - (deviation * cfg.deviation_penalty))

        comment = f"primary_ratio={actual_primary_ratio:.2f}, target={cfg.target_primary_ratio}, total_words={total_words}"

        _submit_score(langfuse, trace_id, observation_id, "content_balance", balance_score, comment)

        logger.info(f"Scored content balance: {balance_score:.2f} ({comment})")

        return ScoringResult(
            score=balance_score,
            details={
                "actual_primary_ratio": actual_primary_ratio,
                "target_primary_ratio": cfg.target_primary_ratio,
                "total_words": total_words,
                "primary_word_count": primary_word_count,
                "secondary_word_counts": secondary_word_counts,
            },
        )

    except Exception as e:
        logger.warning(f"Failed to score content balance: {e}")
        return ScoringResult(score=0.0, error=str(e))


def score_newsletter_generation(
    trace_id: str,
    observation_id: str | None,
    newsletter_result: dict[str, Any],
    total_discussions: int = 0,
    featured_count: int = 0,
    brief_mention_count: int = 0,
    scoring_config: ScoringConfig | None = None,
) -> dict[str, ScoringResult]:
    """
    Comprehensive scoring for newsletter generation.

    Runs all available structural scores and returns combined results.
    This is a convenience function that calls individual scoring functions.

    Args:
        trace_id: Langfuse trace ID
        observation_id: Optional observation ID
        newsletter_result: Full newsletter result dict
        total_discussions: Total discussions available (for coverage)
        featured_count: Featured discussions count
        brief_mention_count: Brief mention count
        scoring_config: Optional custom scoring configuration

    Returns:
        Dict mapping score name to ScoringResult
    """
    results: dict[str, ScoringResult] = {}

    # Score structure
    results["structure"] = score_newsletter_structure(
        trace_id=trace_id,
        observation_id=observation_id,
        result=newsletter_result,
        config=scoring_config,
    )

    # Score coverage (if ranking data provided)
    if total_discussions > 0:
        results["coverage"] = score_ranking_coverage(
            trace_id=trace_id,
            observation_id=observation_id,
            total_discussions=total_discussions,
            featured_count=featured_count,
            brief_mention_count=brief_mention_count,
        )

    return results
