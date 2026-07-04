"""
Local Pre-computed Transcript Provider

Implements TranscriptionProviderInterface by reading transcripts produced
offline by the local ASR + diarization pipeline (faster-whisper large-v3 +
pyannote via the audio-transcribe tool) instead of calling a paid API.

Expected layout, produced per episode by the /extract-podcasts skill:

    data/podcasts/transcripts/<audio-stem>/
        segments.json   # [{"start": s, "end": s, "text": "...", ...}, ...]
        turns.json      # [{"start": s, "end": s, "speaker": "SPEAKER_00"}, ...]

Speakers are assigned to each segment by maximal temporal overlap with the
diarization turns; turns.json is optional (segments then carry no speaker).

Fail-fast: a missing transcript directory or empty segments file raises — this
provider never silently falls back to an API call. Ingest the transcript first
(or switch RAG_TRANSCRIPTION_PROVIDER back to 'openai').
"""

import json
import logging
from pathlib import Path

from config import get_settings
from rag.transcription.interface import (
    TranscriptionProviderInterface,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)

SEGMENTS_FILENAME = "segments.json"
TURNS_FILENAME = "turns.json"


class LocalTranscriptsProvider(TranscriptionProviderInterface):
    """Reads pre-computed, speaker-diarized transcripts from local disk."""

    def __init__(self, transcripts_dir: str | None = None) -> None:
        configured = transcripts_dir or get_settings().rag.local_transcripts_dir
        self._transcripts_dir = Path(configured)

    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        stem = Path(audio_path).stem
        episode_dir = self._transcripts_dir / stem
        segments_path = episode_dir / SEGMENTS_FILENAME

        if not segments_path.is_file():
            raise FileNotFoundError(
                f"LocalTranscriptsProvider: no pre-computed transcript for '{stem}' "
                f"(expected {segments_path}). Run the extract-podcasts transcription "
                f"pipeline first, or set RAG_TRANSCRIPTION_PROVIDER=openai."
            )

        try:
            raw_segments = json.loads(segments_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"LocalTranscriptsProvider: unreadable {segments_path}: {e}") from e
        if isinstance(raw_segments, dict):
            raw_segments = raw_segments.get("segments", [])
        if not raw_segments:
            raise RuntimeError(f"LocalTranscriptsProvider: {segments_path} contains no segments")

        turns = self._load_turns(episode_dir / TURNS_FILENAME)

        segments: list[TranscriptionSegment] = []
        for raw in raw_segments:
            start = float(raw["start"])
            end = float(raw["end"])
            segments.append(
                TranscriptionSegment(
                    text=str(raw["text"]).strip(),
                    start=start,
                    end=end,
                    speaker=_dominant_speaker(start, end, turns),
                )
            )

        duration = max(s.end for s in segments)
        logger.info(
            f"Local transcript loaded: {stem} -> {len(segments)} segments, "
            f"{duration:.0f}s, diarized={bool(turns)}"
        )
        return TranscriptionResult(
            text=" ".join(s.text for s in segments),
            segments=segments,
            duration_seconds=duration,
            language=get_settings().rag.local_transcripts_language,
        )

    @staticmethod
    def _load_turns(turns_path: Path) -> list[dict]:
        if not turns_path.is_file():
            logger.warning(f"LocalTranscriptsProvider: no {turns_path.name}; segments will carry no speaker labels")
            return []
        try:
            raw = json.loads(turns_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"LocalTranscriptsProvider: unreadable {turns_path}: {e}") from e
        return raw.get("turns", raw) if isinstance(raw, dict) else raw


def _dominant_speaker(start: float, end: float, turns: list[dict]) -> str | None:
    """Return the speaker whose diarization turns overlap this segment the most."""
    if not turns:
        return None
    overlap_by_speaker: dict[str, float] = {}
    for turn in turns:
        overlap = min(end, float(turn["end"])) - max(start, float(turn["start"]))
        if overlap > 0:
            speaker = str(turn["speaker"])
            overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0.0) + overlap
    if not overlap_by_speaker:
        return None
    return max(overlap_by_speaker, key=overlap_by_speaker.get)
