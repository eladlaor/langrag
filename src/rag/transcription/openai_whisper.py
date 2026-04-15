"""
OpenAI Whisper Transcription Provider

Uses the OpenAI Whisper API for audio transcription with timestamp segments.
"""

import asyncio
import logging
from io import BytesIO
from pathlib import Path

from openai import AsyncOpenAI

from config import get_settings
from rag.transcription.interface import (
    TranscriptionProviderInterface,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)


class OpenAIWhisperProvider(TranscriptionProviderInterface):
    """Transcription provider using OpenAI's Whisper API."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI()
        self._model = get_settings().rag.whisper_model

    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        """
        Transcribe audio using OpenAI Whisper API.

        Args:
            audio_path: Path to the audio file

        Returns:
            TranscriptionResult with verbose JSON segments

        Raises:
            FileNotFoundError: If audio file does not exist
            RuntimeError: If the API call fails
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Transcribing audio file: {path.name} with model={self._model}")

        try:
            file_bytes = await asyncio.to_thread(Path(audio_path).read_bytes)
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=(path.name, BytesIO(file_bytes)),
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        except Exception as e:
            logger.error(f"OpenAI Whisper transcription failed for {path.name}: {e}")
            raise RuntimeError(f"Transcription failed for {path.name}: {e}") from e

        segments = []
        for seg in response.segments or []:
            segments.append(
                TranscriptionSegment(
                    text=seg.text.strip(),
                    start=seg.start,
                    end=seg.end,
                    speaker=None,
                )
            )

        duration = segments[-1].end if segments else 0.0

        logger.info(f"Transcription complete: {path.name}, {len(segments)} segments, {duration:.1f}s")

        return TranscriptionResult(
            text=response.text,
            segments=segments,
            duration_seconds=duration,
            language=response.language or "unknown",
        )
