from abc import ABC, abstractmethod
from typing import Any


class ContentGeneratorInterface(ABC):
    """Abstract interface for content generators."""

    @abstractmethod
    async def generate_content(self, operation: str, **kwargs) -> Any:
        """
        Generate content based on preprocessed data.

        Args:
            operation: The type of content generation operation
            **kwargs: Various arguments needed for content generation

        Returns:
            Generated content in the appropriate format
        """
        pass
