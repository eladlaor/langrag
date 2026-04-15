"""
RAG Chunk Reranker

MMR-based reranking for retrieved chunks to ensure diversity in the context window.
Uses embedding cosine similarity to penalize redundant chunks.
"""

import logging
import math
from typing import Any

from custom_types.field_keys import RAGChunkKeys as Keys
from constants import RAG_SEARCH_SCORE_FIELD

logger = logging.getLogger(__name__)


def rerank_chunks_mmr(
    chunks: list[dict[str, Any]],
    query_embedding: list[float],
    top_k: int = 5,
    lambda_param: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Rerank chunks using MMR (Maximal Marginal Relevance) for diversity.

    Selects top_k chunks that balance relevance to query with diversity
    among selected chunks.

    Args:
        chunks: List of chunk documents (must have 'search_score' and 'embedding')
        query_embedding: The query embedding vector
        top_k: Number of chunks to select after reranking
        lambda_param: Weight between relevance (1.0) and diversity (0.0). Default 0.7.

    Returns:
        List of top_k chunks ordered by MMR score
    """
    if len(chunks) <= top_k:
        return chunks

    # Extract embeddings from chunks
    chunk_embeddings: list[list[float] | None] = [
        chunk.get(Keys.EMBEDDING) for chunk in chunks
    ]
    has_embeddings = any(e is not None for e in chunk_embeddings)

    selected: list[dict[str, Any]] = []
    selected_indices: list[int] = []
    remaining = list(range(len(chunks)))

    for _ in range(min(top_k, len(chunks))):
        best_idx = -1
        best_score = -float("inf")

        for idx in remaining:
            relevance = chunks[idx].get(RAG_SEARCH_SCORE_FIELD, 0.0)

            # Diversity: max similarity to any already-selected chunk
            max_sim = 0.0
            if has_embeddings and selected_indices and chunk_embeddings[idx] is not None:
                for sel_idx in selected_indices:
                    sel_emb = chunk_embeddings[sel_idx]
                    if sel_emb is not None:
                        max_sim = max(max_sim, _cosine_similarity(chunk_embeddings[idx], sel_emb))

            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        if best_idx >= 0:
            selected.append(chunks[best_idx])
            selected_indices.append(best_idx)
            remaining.remove(best_idx)

    return selected


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
