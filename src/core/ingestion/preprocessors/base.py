from abc import ABC, abstractmethod
from typing import Any

from custom_types.common import CustomBaseModel


class DataPreprocessorInterface(ABC, CustomBaseModel):
    @abstractmethod
    async def preprocess_data(self, data_source_type: str, data_eventual_purpose: str, **kwargs) -> Any:
        """Preprocess the data."""
        raise NotImplementedError("This method should be implemented by the subclass.")
