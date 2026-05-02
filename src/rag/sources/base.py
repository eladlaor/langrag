"""
Content Source Interface and Base Models

Defines the abstract interface for RAG content sources (Strategy pattern).
Follows the same pattern as src/utils/embedding/interface.py.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from constants import ContentSourceType


class ContentChunk(BaseModel):
    """A single chunk of content from any source, ready for embedding and storage.

    source_date_start and source_date_end are required: every chunk MUST be tagged
    with the date(s) of the underlying source content so retrieval can be scoped
    by date range and answers can cite source freshness.
    """

    chunk_id: str = Field(description="Unique identifier for this chunk (UUID)")
    content: str = Field(description="The text content of this chunk")
    content_source: ContentSourceType = Field(description="Source type (podcast, newsletter, etc.)")
    source_id: str = Field(description="Identifier of the parent source (episode_id, newsletter_id, etc.)")
    source_title: str = Field(description="Human-readable title of the parent source")
    chunk_index: int = Field(description="Position of this chunk within the parent source")
    source_date_start: datetime = Field(description="Earliest date the source content covers (UTC)")
    source_date_end: datetime = Field(description="Latest date the source content covers (UTC); equals source_date_start for point-in-time sources")
    metadata: dict = Field(default_factory=dict, description="Source-specific metadata (timestamps, speakers, etc.)")

    @model_validator(mode="after")
    def _validate_date_ordering(self) -> "ContentChunk":
        if self.source_date_end < self.source_date_start:
            raise ValueError(
                f"source_date_end ({self.source_date_end.isoformat()}) precedes "
                f"source_date_start ({self.source_date_start.isoformat()}) for chunk {self.chunk_id}"
            )
        return self


class ContentSourceInterface(ABC):
    """
    Abstract interface for RAG content sources.

    Each content source type (podcast, newsletter, chat) implements this interface
    to provide content extraction in a uniform format that the ingestion pipeline consumes.
    """

    source_type: ContentSourceType

    @abstractmethod
    async def extract(self, source_id: str, **kwargs) -> list[ContentChunk]:
        """
        Extract and chunk content from a specific source.

        Args:
            source_id: Identifier for the source (e.g., audio file path, newsletter_id)
            **kwargs: Source-specific parameters

        Returns:
            List of ContentChunk instances ready for embedding
        """
        raise NotImplementedError

    @abstractmethod
    async def list_sources(self) -> list[dict]:
        """
        List all available sources for this content type.

        Returns:
            List of source metadata dicts with at least 'source_id' and 'title'
        """
        raise NotImplementedError

    @abstractmethod
    async def get_source_metadata(self, source_id: str) -> dict:
        """
        Get metadata for a specific source.

        Args:
            source_id: Identifier for the source

        Returns:
            Source metadata dict
        """
        raise NotImplementedError
