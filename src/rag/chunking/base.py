"""
Chunking Strategy Interface

Defines the abstract interface for content chunking strategies.
Each content type (transcript, markdown, messages) implements its own chunker.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from rag.sources.base import ContentChunk


class ChunkingStrategyInterface(ABC):
    """
    Abstract interface for chunking strategies.

    Implementations decide how to split content into chunks based on
    content-specific heuristics (e.g., speaker boundaries for transcripts,
    section headers for markdown).
    """

    @abstractmethod
    def chunk(
        self,
        content: str,
        source_id: str,
        source_title: str,
        source_date_start: datetime,
        source_date_end: datetime,
        metadata: dict | None = None,
    ) -> list[ContentChunk]:
        """
        Split content into chunks.

        Args:
            content: Raw text content to chunk
            source_id: Parent source identifier
            source_title: Human-readable source title
            source_date_start: Earliest date the source covers (UTC)
            source_date_end: Latest date the source covers (UTC); equals start
                for point-in-time sources like a single podcast episode
            metadata: Additional metadata to attach to each chunk

        Returns:
            List of ContentChunk instances
        """
        raise NotImplementedError
