"""
Transcription Provider Interface

Defines the abstract interface for audio transcription providers (Strategy pattern).
Follows the same pattern as src/utils/embedding/interface.py.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class TranscriptionSegment(BaseModel):
    """A single segment of transcribed audio with timing information."""

    text: str = Field(description="Transcribed text for this segment")
    start: float = Field(description="Start time in seconds")
    end: float = Field(description="End time in seconds")
    speaker: str | None = Field(default=None, description="Speaker identifier (if diarization available)")


class TranscriptionResult(BaseModel):
    """Complete transcription result from an audio file."""

    text: str = Field(description="Full transcribed text")
    segments: list[TranscriptionSegment] = Field(description="Time-aligned segments")
    duration_seconds: float = Field(description="Total audio duration in seconds")
    language: str = Field(default="unknown", description="Detected language code")


class TranscriptionProviderInterface(ABC):
    """
    Abstract interface for transcription providers.

    Implementations wrap specific transcription services (OpenAI Whisper API,
    local Whisper Docker, etc.).
    """

    @abstractmethod
    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file on disk

        Returns:
            TranscriptionResult with text, segments, and metadata

        Raises:
            FileNotFoundError: If audio_path does not exist
            RuntimeError: If transcription fails
        """
        raise NotImplementedError
