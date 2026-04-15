"""
Podcast Content Source

Implements ContentSourceInterface for podcast audio files.
Handles transcription, chunking, and metadata extraction.
"""

import logging
import uuid
from pathlib import Path

from config import get_settings
from constants import ContentSourceType, DIR_NAME_PODCASTS
from rag.chunking.transcript_chunker import TranscriptChunker
from rag.sources.base import ContentChunk, ContentSourceInterface
from rag.transcription.factory import TranscriptionProviderFactory

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
PODCAST_DATA_DIR = Path("data") / DIR_NAME_PODCASTS


class PodcastSource(ContentSourceInterface):
    """
    Content source for podcast audio files.

    Flow:
    1. Takes audio file path
    2. Transcribes via TranscriptionProviderFactory
    3. Chunks transcript via TranscriptChunker (speaker-aware, timestamp-preserving)
    4. Returns ContentChunk list for the ingestion pipeline
    """

    source_type = ContentSourceType.PODCAST

    def __init__(self) -> None:
        settings = get_settings().rag
        self._chunker = TranscriptChunker(
            chunk_size=settings.podcast_chunk_size,
            chunk_overlap=settings.podcast_chunk_overlap,
        )
        self._transcription_provider = TranscriptionProviderFactory.create()

    async def extract(self, source_id: str, **kwargs) -> list[ContentChunk]:
        """
        Transcribe and chunk a podcast audio file.

        Args:
            source_id: Path to the audio file (absolute or relative to data/podcasts/)
            **kwargs:
                title: Optional episode title (defaults to filename stem)

        Returns:
            List of ContentChunk instances

        Raises:
            FileNotFoundError: If the audio file does not exist
            RuntimeError: If transcription fails
        """
        audio_path = self._resolve_audio_path(source_id)
        title = kwargs.get("title", audio_path.stem)

        logger.info(f"Extracting podcast source: {audio_path.name}, title={title}")

        # Transcribe
        transcription = await self._transcription_provider.transcribe(str(audio_path))

        # Generate a stable source ID from the file path
        episode_id = kwargs.get("episode_id", str(uuid.uuid5(uuid.NAMESPACE_URL, str(audio_path))))

        # Build episode-level metadata
        episode_metadata = {
            "episode_title": title,
            "audio_file": audio_path.name,
            "duration_seconds": transcription.duration_seconds,
            "language": transcription.language,
            "total_segments": len(transcription.segments),
        }

        # Chunk with segment awareness
        chunks = self._chunker.chunk_segments(
            segments=transcription.segments,
            source_id=episode_id,
            source_title=title,
            metadata=episode_metadata,
        )

        logger.info(f"Podcast extraction complete: {audio_path.name} -> {len(chunks)} chunks")
        return chunks

    async def list_sources(self) -> list[dict]:
        """
        List audio files in the data/podcasts/ directory.

        Returns:
            List of dicts with source_id (file path), title (stem), and file metadata
        """
        sources = []
        podcast_dir = PODCAST_DATA_DIR

        if not podcast_dir.exists():
            logger.warning(f"Podcast directory does not exist: {podcast_dir}")
            return sources

        for audio_file in sorted(podcast_dir.iterdir()):
            if audio_file.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                sources.append({
                    "source_id": str(audio_file),
                    "title": audio_file.stem,
                    "filename": audio_file.name,
                    "size_bytes": audio_file.stat().st_size,
                })

        return sources

    async def get_source_metadata(self, source_id: str) -> dict:
        """
        Get metadata for a specific audio file.

        Args:
            source_id: Path to the audio file

        Returns:
            File metadata dict
        """
        audio_path = self._resolve_audio_path(source_id)
        stat = audio_path.stat()
        return {
            "source_id": source_id,
            "title": audio_path.stem,
            "filename": audio_path.name,
            "size_bytes": stat.st_size,
            "extension": audio_path.suffix,
        }

    @staticmethod
    def _resolve_audio_path(source_id: str) -> Path:
        """Resolve source_id to an absolute Path, checking existence."""
        path = Path(source_id)
        if path.is_absolute() and path.exists():
            return path

        # Try relative to podcast data dir
        relative_path = PODCAST_DATA_DIR / source_id
        if relative_path.exists():
            return relative_path

        # Try as-is (relative to cwd)
        if path.exists():
            return path

        raise FileNotFoundError(
            f"Audio file not found: '{source_id}'. "
            f"Searched: {source_id}, {relative_path}"
        )
