"""
Embedding Provider Interface

Defines the abstract interface for embedding providers using the Strategy pattern.
Allows swapping embedding providers (OpenAI, Cohere, local models) without changing client code.
"""

from abc import ABC, abstractmethod

from custom_types.common import CustomBaseModel


class EmbeddingProviderInterface(ABC, CustomBaseModel):
    """
    Abstract interface for embedding providers.

    All embedding provider implementations must follow this contract.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension for this provider."""
        raise NotImplementedError("Subclasses must implement dimension property")

    @abstractmethod
    def embed_text(self, text: str) -> list[float] | None:
        """
        Generate embedding vector for a single text.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector, or None if failed
        """
        raise NotImplementedError("Subclasses must implement embed_text()")

    @abstractmethod
    def embed_texts_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float] | None]:
        """
        Generate embeddings for multiple texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts to process per API call

        Returns:
            List of embedding vectors (None for failed texts)
        """
        raise NotImplementedError("Subclasses must implement embed_texts_batch()")

    @abstractmethod
    def compute_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Similarity score between 0 and 1
        """
        raise NotImplementedError("Subclasses must implement compute_similarity()")
