"""
Data Extractors

Contains extractors for pulling raw data from various sources:
- base: Base class defining the extractor interface
- beeper: Extract WhatsApp messages via Beeper/Matrix API
"""

from core.ingestion.extractors.base import RawDataExtractorInterface
from core.ingestion.extractors.beeper import RawDataExtractorBeeper

__all__ = [
    "RawDataExtractorInterface",
    "RawDataExtractorBeeper",
]
