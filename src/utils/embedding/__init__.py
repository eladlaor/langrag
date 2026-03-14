"""
Embedding utilities module.

Provides embedding generation using the Strategy pattern with pluggable providers.

Usage:
    from utils.embedding import EmbeddingProviderFactory

    # Create provider (default: OpenAI)
    embedder = EmbeddingProviderFactory.create()

    # Generate embedding
    embedding = embedder.embed_text("Some text to embed")

    # Batch embed
    embeddings = embedder.embed_texts_batch(["text1", "text2", "text3"])

    # Compute similarity
    similarity = embedder.compute_similarity(embedding1, embedding2)
"""

from utils.embedding.interface import EmbeddingProviderInterface
from utils.embedding.factory import EmbeddingProviderFactory

__all__ = [
    "EmbeddingProviderInterface",
    "EmbeddingProviderFactory",
]
