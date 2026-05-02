"""
Podcast Content Source

Implements ContentSourceInterface for podcast audio files.
Handles transcription, chunking, and metadata extraction.

Date metadata convention:
  - Filename MUST start with YYYY-MM-DD (e.g., 2026-03-15-episode-title.mp3)
  - OR data/podcasts/manifest.json provides {"<filename>": {"episode_date": "...", ...}}
  - Ingestion fails fast if neither source yields a valid episode date.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from config import get_settings
from constants import ContentSourceType, DIR_NAME_PODCASTS
from rag.chunking.transcript_chunker import TranscriptChunker
from rag.sources.base import ContentChunk, ContentSourceInterface
from rag.transcription.factory import TranscriptionProviderFactory

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
PODCAST_DATA_DIR = Path("data") / DIR_NAME_PODCASTS
PODCAST_MANIFEST_FILENAME = "manifest.json"
_FILENAME_DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})")


class PodcastSource(ContentSourceInterface):
    """
    Content source for podcast audio files.

    Flow:
    1. Takes audio file path
    2. Resolves episode date from filename (YYYY-MM-DD prefix) and/or manifest
    3. Transcribes via TranscriptionProviderFactory
    4. Chunks transcript via TranscriptChunker (speaker-aware, timestamp-preserving)
    5. Returns ContentChunk list, every chunk tagged with the episode's date
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
                episode_date: Optional ISO date string overriding filename/manifest

        Returns:
            List of ContentChunk instances

        Raises:
            FileNotFoundError: If the audio file does not exist
            ValueError: If no episode date can be derived (fail-fast on missing dates)
            RuntimeError: If transcription fails
        """
        audio_path = self._resolve_audio_path(source_id)
        manifest_entry = self._load_manifest_entry(audio_path)

        title = kwargs.get("title") or manifest_entry.get("title") or audio_path.stem
        explicit_episode_date = kwargs.get("episode_date") or manifest_entry.get("episode_date")
        episode_date = self._resolve_episode_date(audio_path, explicit_episode_date)

        logger.info(
            f"Extracting podcast source: {audio_path.name}, title={title}, "
            f"episode_date={episode_date.date().isoformat()}"
        )

        transcription = await self._transcription_provider.transcribe(str(audio_path))

        episode_id = kwargs.get("episode_id", str(uuid.uuid5(uuid.NAMESPACE_URL, str(audio_path))))

        episode_metadata = {
            "episode_title": title,
            "episode_date": episode_date.date().isoformat(),
            "audio_file": audio_path.name,
            "duration_seconds": transcription.duration_seconds,
            "language": transcription.language,
            "total_segments": len(transcription.segments),
        }
        if "guests" in manifest_entry:
            episode_metadata["guests"] = manifest_entry["guests"]

        chunks = self._chunker.chunk_segments(
            segments=transcription.segments,
            source_id=episode_id,
            source_title=title,
            source_date_start=episode_date,
            source_date_end=episode_date,
            metadata=episode_metadata,
        )

        logger.info(f"Podcast extraction complete: {audio_path.name} -> {len(chunks)} chunks")
        return chunks

    async def list_sources(self) -> list[dict]:
        """List audio files in the data/podcasts/ directory."""
        sources = []
        if not PODCAST_DATA_DIR.exists():
            logger.warning(f"Podcast directory does not exist: {PODCAST_DATA_DIR}")
            return sources

        for audio_file in sorted(PODCAST_DATA_DIR.iterdir()):
            if audio_file.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                sources.append({
                    "source_id": str(audio_file),
                    "title": audio_file.stem,
                    "filename": audio_file.name,
                    "size_bytes": audio_file.stat().st_size,
                })

        return sources

    async def get_source_metadata(self, source_id: str) -> dict:
        """Get metadata for a specific audio file."""
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

        relative_path = PODCAST_DATA_DIR / source_id
        if relative_path.exists():
            return relative_path

        if path.exists():
            return path

        raise FileNotFoundError(
            f"Audio file not found: '{source_id}'. "
            f"Searched: {source_id}, {relative_path}"
        )

    @staticmethod
    def _load_manifest_entry(audio_path: Path) -> dict:
        """Load this episode's entry from data/podcasts/manifest.json, if present."""
        manifest_path = PODCAST_DATA_DIR / PODCAST_MANIFEST_FILENAME
        if not manifest_path.exists():
            return {}

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(
                f"Podcast manifest at {manifest_path} is unreadable: {e}"
            ) from e

        return manifest.get(audio_path.name, {})

    @staticmethod
    def _resolve_episode_date(audio_path: Path, explicit_date: str | None) -> datetime:
        """Resolve an episode date from explicit override or filename prefix.

        Fail-fast: every podcast chunk MUST be tagged with the episode date so that
        date-scoped retrieval works correctly.
        """
        if explicit_date:
            try:
                parsed = datetime.fromisoformat(explicit_date)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError as e:
                raise ValueError(
                    f"Podcast {audio_path.name}: explicit episode_date '{explicit_date}' "
                    f"is not a valid ISO date"
                ) from e

        match = _FILENAME_DATE_PATTERN.match(audio_path.stem)
        if not match:
            raise ValueError(
                f"Podcast {audio_path.name}: cannot derive episode date. Either rename to "
                f"'YYYY-MM-DD-<title>{audio_path.suffix}' or add an entry to "
                f"{PODCAST_DATA_DIR / PODCAST_MANIFEST_FILENAME} with 'episode_date'."
            )

        try:
            parsed = datetime.fromisoformat(match.group(1))
        except ValueError as e:
            raise ValueError(
                f"Podcast {audio_path.name}: filename date '{match.group(1)}' is invalid"
            ) from e

        return parsed.replace(tzinfo=UTC)
