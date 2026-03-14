"""
Newsletter History Module

Provides utilities for loading and parsing previous newsletters
to support anti-repetition features in newsletter generation.
"""

from core.retrieval.history.newsletter_history_loader import (
    PreviousNewsletterContext,
    PreviousNewslettersContext,
    load_previous_newsletters,
)

__all__ = [
    "PreviousNewsletterContext",
    "PreviousNewslettersContext",
    "load_previous_newsletters",
]
