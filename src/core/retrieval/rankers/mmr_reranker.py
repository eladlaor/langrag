"""
MMR (Maximal Marginal Relevance) Reranking

Balances quality and diversity when selecting top-K discussions.

Based on: Carbonell & Goldstein (1998)
"The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries"

This module implements the classic MMR algorithm to ensure newsletter discussions
are both high-quality AND diverse. Prevents "5 discussions about RAG" problem by
penalizing similar discussions during selection.

Algorithm Overview:
    1. Normalize quality scores to 0-1
    2. Select first item: highest quality (no diversity penalty)
    3. For each subsequent item:
        - Calculate MMR score = λ × quality - (1-λ) × max_similarity_to_selected
        - Select item with highest MMR score
    4. Repeat until K items selected

Performance:
    - Time Complexity: O(K × N × D) where K=top_k, N=total discussions, D=embedding dimension
    - Typical: ~10ms for 50 discussions with 1536-dim embeddings
    - Negligible overhead compared to LLM ranking
"""

import logging
import math
from typing import Any

from utils.embedding.factory import EmbeddingProviderFactory
from custom_types.field_keys import DiscussionKeys, MMRMetadataKeys

logger = logging.getLogger(__name__)


def rank_with_mmr(discussions: list[dict[str, Any]], quality_scores: list[float], top_k: int = 5, lambda_param: float = 0.7, use_embeddings: bool = True) -> list[dict[str, Any]]:
    """
    Rank discussions using MMR (Maximal Marginal Relevance).

    Balances quality and diversity:
    - lambda_param = 1.0: Pure quality ranking (no diversity)
    - lambda_param = 0.0: Pure diversity (ignore quality)
    - lambda_param = 0.7: Balanced (70% quality, 30% diversity) [RECOMMENDED]

    Args:
        discussions: List of discussion dictionaries (must have 'title' and 'nutshell')
        quality_scores: Quality scores from LLM ranking (same order as discussions)
        top_k: Number of discussions to select
        lambda_param: Quality vs diversity weight (0-1, default: 0.7)
        use_embeddings: If False, fall back to quality-only ranking

    Returns:
        List of top-K discussions ranked by MMR, with mmr_metadata added to each

    Raises:
        ValueError: If discussions and quality_scores have different lengths
        RuntimeError: If embedding generation fails (gracefully falls back to quality-only)

    Example:
        >>> discussions = [
        ...     {"id": "1", "title": "RAG Chunking", "nutshell": "...", "embedding": [...]},
        ...     {"id": "2", "title": "RAG Best Practices", "nutshell": "...", "embedding": [...]},
        ...     {"id": "3", "title": "LangGraph State", "nutshell": "...", "embedding": [...]}
        ... ]
        >>> quality_scores = [9.5, 9.3, 8.8]
        >>> ranked = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.7)
        >>> # Returns: [{"id": "1", ...}, {"id": "3", ...}]  # Promotes diversity
    """
    # Validate inputs (fail-fast for programming errors)
    if len(discussions) != len(quality_scores):
        raise ValueError(f"Discussions ({len(discussions)}) and quality_scores ({len(quality_scores)}) " f"must have the same length")

    try:
        if len(discussions) < 2 or not use_embeddings:
            logger.info("MMR disabled or <2 discussions - using quality-only ranking " f"(discussions={len(discussions)}, use_embeddings={use_embeddings})")
            return _quality_only_ranking(discussions, quality_scores, top_k)

        logger.info(f"MMR reranking: {len(discussions)} discussions, " f"top_k={top_k}, λ={lambda_param}")

        # Step 1: Get or generate embeddings for all discussions
        embeddings = _get_or_generate_embeddings(discussions)

        # Step 2: Normalize quality scores to 0-1
        max_score = max(quality_scores) if quality_scores else 1.0
        normalized_quality = [score / max_score if max_score > 0 else 0.0 for score in quality_scores]

        # Step 3: MMR selection algorithm
        selected_indices = []
        selected_embeddings = []
        remaining_indices = list(range(len(discussions)))

        while len(selected_indices) < top_k and remaining_indices:
            best_mmr_score = -float("inf")
            best_idx = None

            for idx in remaining_indices:
                # Quality component
                quality = normalized_quality[idx]

                # Diversity component
                if selected_embeddings and embeddings[idx]:
                    # Calculate max similarity to any already-selected item
                    similarities = [_compute_cosine_similarity(embeddings[idx], sel_emb) for sel_emb in selected_embeddings]
                    max_similarity = max(similarities) if similarities else 0.0
                else:
                    # First item or missing embedding - no diversity penalty
                    max_similarity = 0.0

                # MMR formula: λ × quality - (1-λ) × max_similarity
                mmr_score = lambda_param * quality - (1 - lambda_param) * max_similarity

                if mmr_score > best_mmr_score:
                    best_mmr_score = mmr_score
                    best_idx = idx

            if best_idx is not None:
                selected_indices.append(best_idx)
                if embeddings[best_idx]:
                    selected_embeddings.append(embeddings[best_idx])
                remaining_indices.remove(best_idx)
            else:
                # No more items to select
                break

        # Step 4: Build result with MMR metadata
        result = []
        for rank, idx in enumerate(selected_indices, 1):
            disc = discussions[idx].copy()

            # Calculate diversity score for this item
            if rank == 1:
                diversity_score = 1.0  # First item has max diversity by definition
            else:
                # Diversity = 1 - max_similarity to previously selected items
                similarities = [_compute_cosine_similarity(embeddings[idx], embeddings[selected_indices[j]]) for j in range(rank - 1) if embeddings[idx] and embeddings[selected_indices[j]]]
                diversity_score = 1 - max(similarities) if similarities else 1.0

            # Add MMR metadata for monitoring and debugging
            disc[MMRMetadataKeys.MMR_METADATA] = {MMRMetadataKeys.QUALITY_SCORE: quality_scores[idx], MMRMetadataKeys.DIVERSITY_SCORE: diversity_score, MMRMetadataKeys.MMR_RANK: rank, MMRMetadataKeys.LAMBDA: lambda_param}

            result.append(disc)

        # Log final diversity metrics
        avg_diversity = sum(d[MMRMetadataKeys.MMR_METADATA][MMRMetadataKeys.DIVERSITY_SCORE] for d in result) / len(result)
        logger.info(f"MMR selection complete: {len(result)} discussions, " f"avg_diversity={avg_diversity:.2f}")

        return result

    except Exception as e:
        logger.error(f"MMR reranking failed: {e}, falling back to quality-only ranking", exc_info=True)
        # Graceful fallback to quality ranking
        return _quality_only_ranking(discussions, quality_scores, top_k)


def _get_or_generate_embeddings(discussions: list[dict[str, Any]]) -> list[list[float] | None]:
    """
    Get embeddings from discussions or generate them if missing.

    Checks if discussions already have embeddings (from MongoDB).
    If not, generates them on-the-fly using the configured embedding provider.

    Args:
        discussions: List of discussion dictionaries

    Returns:
        List of embedding vectors (None for discussions without text)

    Raises:
        RuntimeError: If embedding provider initialization fails
    """
    try:
        embeddings = []
        needs_generation = []
        needs_generation_indices = []

        # First pass: Check for existing embeddings
        for i, disc in enumerate(discussions):
            if DiscussionKeys.EMBEDDING in disc and disc[DiscussionKeys.EMBEDDING]:
                embeddings.append(disc[DiscussionKeys.EMBEDDING])
            else:
                embeddings.append(None)
                needs_generation_indices.append(i)
                # Combine title and nutshell for embedding
                text = f"{disc.get(DiscussionKeys.TITLE, '')}. {disc.get(DiscussionKeys.NUTSHELL, '')}"
                needs_generation.append(text.strip())

        # Second pass: Generate missing embeddings
        if needs_generation:
            logger.debug(f"Generating embeddings for {len(needs_generation)} discussions " f"without stored embeddings")
            embedder = EmbeddingProviderFactory.create()
            generated = embedder.embed_texts_batch(needs_generation)

            # Fill in generated embeddings
            for idx, emb in zip(needs_generation_indices, generated):
                embeddings[idx] = emb

        return embeddings

    except Exception as e:
        logger.error(f"Failed to get/generate embeddings: {e}", exc_info=True)
        raise RuntimeError(f"Embedding generation failed: {e}") from e


def _compute_cosine_similarity(emb1: list[float], emb2: list[float]) -> float:
    """
    Compute cosine similarity: dot(A, B) / (||A|| × ||B||)

    Args:
        emb1: First embedding vector
        emb2: Second embedding vector

    Returns:
        Cosine similarity (0-1, where 1 = identical, 0 = orthogonal)
    """
    if not emb1 or not emb2 or len(emb1) != len(emb2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(emb1, emb2))
    norm1 = math.sqrt(sum(a * a for a in emb1))
    norm2 = math.sqrt(sum(b * b for b in emb2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def _quality_only_ranking(discussions: list[dict[str, Any]], quality_scores: list[float], top_k: int) -> list[dict[str, Any]]:
    """
    Fallback ranking based purely on quality scores.

    Used when:
    - MMR is disabled (use_embeddings=False)
    - Fewer than 2 discussions (diversity not applicable)
    - Embedding generation fails

    Args:
        discussions: List of discussion dictionaries
        quality_scores: Quality scores from LLM ranking
        top_k: Number of discussions to select

    Returns:
        Top-K discussions sorted by quality (highest first)
    """
    sorted_indices = sorted(range(len(discussions)), key=lambda i: quality_scores[i], reverse=True)

    result = []
    for rank, idx in enumerate(sorted_indices[:top_k], 1):
        disc = discussions[idx].copy()
        # Add metadata indicating quality-only ranking
        disc[MMRMetadataKeys.MMR_METADATA] = {
            MMRMetadataKeys.QUALITY_SCORE: quality_scores[idx],
            MMRMetadataKeys.DIVERSITY_SCORE: None,  # Not calculated in quality-only mode
            MMRMetadataKeys.MMR_RANK: rank,
            MMRMetadataKeys.LAMBDA: None,  # MMR not applied
            MMRMetadataKeys.RANKING_MODE: "quality_only",
        }
        result.append(disc)

    return result
