"""
OpenAI Embedding Provider

Implements the EmbeddingProviderInterface using OpenAI's embedding API.
"""

import logging
import math
import os

from openai import OpenAI
from pydantic import ConfigDict

from config import get_settings
from constants import EMBEDDING_MODEL_DIMENSIONS
from utils.embedding.interface import EmbeddingProviderInterface

logger = logging.getLogger(__name__)

# Get default model from config
_settings = get_settings()
DEFAULT_MODEL = _settings.embedding.default_model


class OpenAIEmbedder(EmbeddingProviderInterface):
    """
    OpenAI embedding provider implementation.

    Uses OpenAI's embedding API to generate vector embeddings for text.
    """

    model: str = DEFAULT_MODEL
    _client: OpenAI | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def model_post_init(self, __context) -> None:
        """Initialize the OpenAI client after model creation."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self._client = OpenAI(api_key=api_key)

    @property
    def dimension(self) -> int:
        """Return the embedding dimension for the configured model."""
        from constants import DEFAULT_EMBEDDING_DIMENSION

        return EMBEDDING_MODEL_DIMENSIONS.get(self.model, DEFAULT_EMBEDDING_DIMENSION)

    def embed_text(self, text: str) -> list[float] | None:
        """
        Generate embedding for a single text using OpenAI API.

        Args:
            text: Text to embed (max chars from config)

        Returns:
            Embedding vector or None if failed
        """
        if not text or not text.strip():
            return None

        try:
            settings = get_settings()
            response = self._client.embeddings.create(
                model=self.model,
                input=text.strip()[: settings.embedding.max_text_length],
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    def embed_texts_batch(self, texts: list[str], batch_size: int = None) -> list[list[float] | None]:
        """
        Generate embeddings for multiple texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per API call (default from config)

        Returns:
            List of embedding vectors (None for empty/failed texts)
        """
        if not texts:
            return []

        settings = get_settings()
        batch_size = batch_size or settings.embedding.batch_size

        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            cleaned_batch = [t.strip()[: settings.embedding.max_text_length] if t and t.strip() else "" for t in batch]

            try:
                response = self._client.embeddings.create(
                    model=self.model,
                    input=cleaned_batch,
                )
                batch_results = [None] * len(batch)
                for j, item in enumerate(response.data):
                    if cleaned_batch[j]:
                        batch_results[j] = item.embedding
                results.extend(batch_results)
            except Exception as e:
                logger.error(f"Failed to generate batch embeddings: {e}")
                results.extend([None] * len(batch))

        return results

    def compute_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Similarity score between 0 and 1
        """
        if not embedding1 or not embedding2:
            return 0.0

        if len(embedding1) != len(embedding2):
            raise ValueError("Embeddings must have same dimension")

        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        norm1 = math.sqrt(sum(a * a for a in embedding1))
        norm2 = math.sqrt(sum(b * b for b in embedding2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)
