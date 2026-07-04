"""Unit tests for LocalTranscriptsProvider (pre-computed transcript ingestion)."""

import json

import pytest

from rag.transcription.local_transcripts import LocalTranscriptsProvider, _dominant_speaker


def _write_episode(tmp_path, stem, segments, turns=None):
    d = tmp_path / stem
    d.mkdir()
    (d / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
    if turns is not None:
        (d / "turns.json").write_text(json.dumps(turns), encoding="utf-8")
    return d


async def test_loads_segments_with_speakers(tmp_path):
    _write_episode(
        tmp_path,
        "ep",
        segments=[
            {"start": 0.0, "end": 5.0, "text": "שלום לכולם"},
            {"start": 5.0, "end": 10.0, "text": "תודה שהזמנתם אותי"},
        ],
        turns=[
            {"start": 0.0, "end": 4.8, "speaker": "SPEAKER_00"},
            {"start": 4.8, "end": 10.0, "speaker": "SPEAKER_01"},
        ],
    )
    provider = LocalTranscriptsProvider(transcripts_dir=str(tmp_path))
    result = await provider.transcribe("/anywhere/ep.mp3")

    assert len(result.segments) == 2
    assert result.segments[0].speaker == "SPEAKER_00"
    assert result.segments[1].speaker == "SPEAKER_01"
    assert result.duration_seconds == 10.0
    assert "שלום" in result.text


async def test_missing_transcript_fails_fast(tmp_path):
    provider = LocalTranscriptsProvider(transcripts_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError, match="no pre-computed transcript"):
        await provider.transcribe("/anywhere/nonexistent.mp3")


async def test_empty_segments_fails_fast(tmp_path):
    _write_episode(tmp_path, "ep", segments=[])
    provider = LocalTranscriptsProvider(transcripts_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="contains no segments"):
        await provider.transcribe("/anywhere/ep.mp3")


async def test_no_turns_file_yields_unlabeled_segments(tmp_path):
    _write_episode(tmp_path, "ep", segments=[{"start": 0.0, "end": 3.0, "text": "hi"}])
    provider = LocalTranscriptsProvider(transcripts_dir=str(tmp_path))
    result = await provider.transcribe("/anywhere/ep.mp3")
    assert result.segments[0].speaker is None


def test_dominant_speaker_picks_max_overlap():
    turns = [
        {"start": 0.0, "end": 2.0, "speaker": "A"},
        {"start": 2.0, "end": 10.0, "speaker": "B"},
    ]
    assert _dominant_speaker(1.0, 6.0, turns) == "B"
    assert _dominant_speaker(0.0, 2.5, turns) == "A"
    assert _dominant_speaker(50.0, 60.0, turns) is None
