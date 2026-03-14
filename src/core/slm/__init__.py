"""
SLM (Small Language Model) Module

Provides local SLM inference via Ollama for message pre-filtering
and classification tasks. Reduces expensive LLM API calls by filtering
low-quality messages before they reach the main pipeline.
"""

from core.slm.provider import OllamaProvider, get_slm_provider
from core.slm.classifier import MessageClassifier

__all__ = [
    "OllamaProvider",
    "get_slm_provider",
    "MessageClassifier",
]
