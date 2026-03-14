from abc import ABC, abstractmethod
from typing import Any

from custom_types.common import CustomBaseModel


class RawDataExtractorInterface(ABC, CustomBaseModel):
    @abstractmethod
    def extract_messages(self, **kwargs) -> list[Any]:
        """Extract messages from the input."""
        raise NotImplementedError("This method should be implemented by the subclass.")
