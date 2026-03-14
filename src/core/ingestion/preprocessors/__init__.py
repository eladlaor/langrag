"""
Data Preprocessors

Contains preprocessors for cleaning and transforming raw data:
- base: Base class defining the preprocessor interface
- whatsapp: WhatsApp message preprocessing (parsing, translation, discussion separation)
- factory: Factory for creating appropriate preprocessor instances
"""

from core.ingestion.preprocessors.base import DataPreprocessorInterface
from core.ingestion.preprocessors.whatsapp import (
    WhatsAppPreprocessor,
    DataPreprocessorWhatsappChatsBase,
    CommunityLangTalksDataPreprocessor,  # Backward compatibility alias
    CommunityMcpDataPreprocessor,  # Backward compatibility alias
)
from core.ingestion.preprocessors.factory import DataProcessorFactory

__all__ = [
    "DataPreprocessorInterface",
    "WhatsAppPreprocessor",
    "DataPreprocessorWhatsappChatsBase",
    "CommunityLangTalksDataPreprocessor",
    "CommunityMcpDataPreprocessor",
    "DataProcessorFactory",
]
