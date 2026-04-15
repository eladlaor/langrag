"""
Transcription Provider Factory

Factory for creating transcription provider instances based on configuration.
"""

import logging

from config import get_settings
from constants import TranscriptionProvider
from rag.transcription.interface import TranscriptionProviderInterface

logger = logging.getLogger(__name__)


class TranscriptionProviderFactory:
    """Factory for creating transcription provider instances."""

    @staticmethod
    def create(provider_name: str | None = None) -> TranscriptionProviderInterface:
        """
        Create a transcription provider instance.

        Args:
            provider_name: Provider name override. If None, uses RAG_TRANSCRIPTION_PROVIDER config.

        Returns:
            TranscriptionProviderInterface instance

        Raises:
            ValueError: If the provider name is not recognized
        """
        name = provider_name or get_settings().rag.transcription_provider

        if name == TranscriptionProvider.OPENAI:
            from rag.transcription.openai_whisper import OpenAIWhisperProvider

            return OpenAIWhisperProvider()

        if name == TranscriptionProvider.LOCAL:
            raise NotImplementedError(
                "Local Whisper provider is not yet implemented. "
                "Use 'openai' provider or contribute a local_whisper.py implementation."
            )

        raise ValueError(
            f"Unknown transcription provider '{name}'. "
            f"Available: {[p.value for p in TranscriptionProvider]}"
        )
