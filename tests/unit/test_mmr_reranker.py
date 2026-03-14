"""
Unit tests for MMR (Maximal Marginal Relevance) reranking.

Tests verify that MMR correctly balances quality and diversity when selecting
top-K discussions for newsletters.
"""

import pytest
from core.retrieval.rankers.mmr_reranker import rank_with_mmr


def test_mmr_promotes_diversity():
    """Test that MMR promotes diverse discussions over similar ones."""
    discussions = [
        {
            "id": "disc_A",
            "title": "RAG Chunking Strategies",
            "nutshell": "Strategies for chunking in RAG",
            "embedding": [0.1, 0.9, 0.1]  # Similar to B
        },
        {
            "id": "disc_B",
            "title": "RAG Best Practices",
            "nutshell": "Best practices for RAG implementation",
            "embedding": [0.15, 0.88, 0.12]  # Similar to A
        },
        {
            "id": "disc_C",
            "title": "LangGraph State Management",
            "nutshell": "Managing state in LangGraph",
            "embedding": [0.7, 0.2, 0.1]  # Different topic
        },
    ]

    quality_scores = [9.5, 9.3, 8.8]  # B has higher quality than C

    # With MMR (λ=0.7), C should be selected over B for diversity
    result = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.7)

    assert len(result) == 2
    assert result[0]["id"] == "disc_A"  # Highest quality, selected first
    assert result[1]["id"] == "disc_C"  # Lower quality but diverse, beats B

    # Verify metadata
    assert "mmr_metadata" in result[0]
    assert result[0]["mmr_metadata"]["mmr_rank"] == 1
    assert result[0]["mmr_metadata"]["diversity_score"] == 1.0  # First item always 1.0

    assert "mmr_metadata" in result[1]
    assert result[1]["mmr_metadata"]["mmr_rank"] == 2
    assert result[1]["mmr_metadata"]["diversity_score"] > 0.5  # Reasonably diverse


def test_mmr_pure_quality_mode():
    """Test that λ=1.0 disables diversity (pure quality ranking)."""
    discussions = [
        {"id": "disc_A", "title": "A", "nutshell": "A", "embedding": [0.1, 0.9]},
        {"id": "disc_B", "title": "B", "nutshell": "B", "embedding": [0.15, 0.88]},
        {"id": "disc_C", "title": "C", "nutshell": "C", "embedding": [0.7, 0.2]},
    ]

    quality_scores = [9.5, 9.3, 8.8]

    # λ=1.0: Pure quality ranking (no diversity)
    result = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=1.0)

    assert result[0]["id"] == "disc_A"  # Highest quality
    assert result[1]["id"] == "disc_B"  # Second highest (diversity ignored)


def test_mmr_pure_diversity_mode():
    """Test that λ=0.0 maximizes diversity (ignores quality)."""
    discussions = [
        {
            "id": "disc_A",
            "title": "A",
            "nutshell": "A",
            "embedding": [0.1, 0.9, 0.1]
        },
        {
            "id": "disc_B",
            "title": "B",
            "nutshell": "B",
            "embedding": [0.15, 0.88, 0.12]  # Similar to A
        },
        {
            "id": "disc_C",
            "title": "C",
            "nutshell": "C",
            "embedding": [0.7, 0.2, 0.1]  # Different from A
        },
        {
            "id": "disc_D",
            "title": "D",
            "nutshell": "D",
            "embedding": [0.1, 0.1, 0.9]  # Different from A and C
        },
    ]

    quality_scores = [9.5, 9.3, 8.8, 8.5]

    # λ=0.0: Pure diversity (quality ignored)
    result = rank_with_mmr(discussions, quality_scores, top_k=3, lambda_param=0.0)

    # First is still highest quality
    assert result[0]["id"] == "disc_A"
    # Second should be most different from A (either C or D)
    assert result[1]["id"] in ["disc_C", "disc_D"]
    # Third should maximize diversity from first two
    # Should NOT be B since it's similar to A


def test_mmr_handles_missing_embeddings():
    """Test graceful fallback when embeddings unavailable."""
    discussions = [
        {"id": "disc_A", "title": "A", "nutshell": "A"},  # No embedding
        {"id": "disc_B", "title": "B", "nutshell": "B"},  # No embedding
    ]

    quality_scores = [9.5, 8.5]

    # Should fall back to quality-only ranking
    result = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.7)

    assert len(result) == 2
    assert result[0]["id"] == "disc_A"  # Quality order preserved
    assert result[1]["id"] == "disc_B"

    # Verify metadata exists and has standard MMR structure
    assert "mmr_metadata" in result[0]
    assert result[0]["mmr_metadata"]["quality_score"] == 9.5


def test_mmr_single_discussion():
    """Test that single discussion doesn't crash (trivial case)."""
    discussions = [
        {"id": "disc_A", "title": "A", "nutshell": "A", "embedding": [0.1, 0.9]}
    ]

    quality_scores = [9.5]

    result = rank_with_mmr(discussions, quality_scores, top_k=1, lambda_param=0.7)

    assert len(result) == 1
    assert result[0]["id"] == "disc_A"


def test_mmr_top_k_smaller_than_total():
    """Test that top_k limits results correctly."""
    discussions = [
        {"id": f"disc_{i}", "title": f"Title {i}", "nutshell": f"Nutshell {i}", "embedding": [i * 0.1, 1.0 - i * 0.1]}
        for i in range(10)
    ]

    quality_scores = [10.0 - i for i in range(10)]  # Descending quality

    result = rank_with_mmr(discussions, quality_scores, top_k=5, lambda_param=0.7)

    assert len(result) == 5
    # Verify all have mmr_metadata
    for disc in result:
        assert "mmr_metadata" in disc
        assert "mmr_rank" in disc["mmr_metadata"]


def test_mmr_balanced_lambda():
    """Test balanced λ=0.5 (equal quality and diversity)."""
    discussions = [
        {
            "id": "disc_A",
            "title": "A",
            "nutshell": "A",
            "embedding": [0.1, 0.9]
        },
        {
            "id": "disc_B",
            "title": "B",
            "nutshell": "B",
            "embedding": [0.12, 0.88]  # Very similar to A
        },
        {
            "id": "disc_C",
            "title": "C",
            "nutshell": "C",
            "embedding": [0.9, 0.1]  # Very different from A
        },
    ]

    quality_scores = [9.5, 9.4, 8.0]  # B slightly better than C

    # λ=0.5: Equal weight to quality and diversity
    result = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.5)

    assert result[0]["id"] == "disc_A"  # First is always highest quality
    # Second should be C (diversity outweighs small quality difference)
    assert result[1]["id"] == "disc_C"


def test_mmr_use_embeddings_false():
    """Test that use_embeddings=False falls back to quality ranking."""
    discussions = [
        {"id": "disc_A", "title": "A", "nutshell": "A", "embedding": [0.1, 0.9]},
        {"id": "disc_B", "title": "B", "nutshell": "B", "embedding": [0.15, 0.88]},
        {"id": "disc_C", "title": "C", "nutshell": "C", "embedding": [0.7, 0.2]},
    ]

    quality_scores = [9.5, 9.3, 8.8]

    # Explicitly disable embeddings
    result = rank_with_mmr(
        discussions, quality_scores, top_k=3, lambda_param=0.7, use_embeddings=False
    )

    # Should return quality order
    assert result[0]["id"] == "disc_A"
    assert result[1]["id"] == "disc_B"
    assert result[2]["id"] == "disc_C"

    # Verify quality-only mode
    assert result[0]["mmr_metadata"].get("ranking_mode") == "quality_only"


def test_mmr_metadata_structure():
    """Test that mmr_metadata has correct structure."""
    discussions = [
        {"id": "disc_A", "title": "A", "nutshell": "A", "embedding": [0.1, 0.9]},
        {"id": "disc_B", "title": "B", "nutshell": "B", "embedding": [0.7, 0.2]},
    ]

    quality_scores = [9.5, 8.8]

    result = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.7)

    # Check metadata structure
    metadata = result[0]["mmr_metadata"]
    assert "quality_score" in metadata
    assert "diversity_score" in metadata
    assert "mmr_rank" in metadata
    assert "lambda" in metadata

    assert metadata["quality_score"] == 9.5
    assert metadata["diversity_score"] == 1.0  # First item
    assert metadata["mmr_rank"] == 1
    assert metadata["lambda"] == 0.7


def test_mmr_mismatched_lengths():
    """Test that mismatched discussions and scores raises error."""
    discussions = [
        {"id": "disc_A", "title": "A", "nutshell": "A", "embedding": [0.1, 0.9]},
        {"id": "disc_B", "title": "B", "nutshell": "B", "embedding": [0.7, 0.2]},
    ]

    quality_scores = [9.5]  # Only 1 score for 2 discussions

    with pytest.raises(ValueError, match="must have the same length"):
        rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.7)


def test_mmr_diversity_increases_with_lower_lambda():
    """Test that lower lambda values increase diversity score."""
    discussions = [
        {
            "id": "disc_A",
            "title": "A",
            "nutshell": "A",
            "embedding": [0.1, 0.9]
        },
        {
            "id": "disc_B",
            "title": "B",
            "nutshell": "B",
            "embedding": [0.12, 0.88]  # Similar to A
        },
        {
            "id": "disc_C",
            "title": "C",
            "nutshell": "C",
            "embedding": [0.9, 0.1]  # Different from A
        },
    ]

    quality_scores = [9.5, 9.4, 8.5]

    # Test with high lambda (favor quality)
    result_high_lambda = rank_with_mmr(
        discussions, quality_scores, top_k=2, lambda_param=0.9
    )

    # Test with low lambda (favor diversity)
    result_low_lambda = rank_with_mmr(
        discussions, quality_scores, top_k=2, lambda_param=0.3
    )

    # With high lambda, might select B (high quality, similar to A)
    # With low lambda, should select C (diverse from A)
    # The second selection should differ based on lambda
    assert result_low_lambda[1]["id"] == "disc_C"  # Diversity wins


def test_mmr_preserves_original_discussion_data():
    """Test that MMR doesn't corrupt original discussion fields."""
    discussions = [
        {
            "id": "disc_A",
            "title": "Original Title A",
            "nutshell": "Original Nutshell A",
            "custom_field": "custom_value",
            "embedding": [0.1, 0.9]
        },
        {
            "id": "disc_B",
            "title": "Original Title B",
            "nutshell": "Original Nutshell B",
            "another_field": 42,
            "embedding": [0.7, 0.2]
        },
    ]

    quality_scores = [9.5, 8.8]

    result = rank_with_mmr(discussions, quality_scores, top_k=2, lambda_param=0.7)

    # Verify original fields are preserved
    assert result[0]["title"] == "Original Title A"
    assert result[0]["nutshell"] == "Original Nutshell A"
    assert result[0]["custom_field"] == "custom_value"

    assert result[1]["title"] == "Original Title B"
    assert result[1]["nutshell"] == "Original Nutshell B"
    assert result[1]["another_field"] == 42
