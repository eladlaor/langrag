"""PodcastSource stamps podcast_slug on every chunk.

Default is the LangTalks slug; an explicit kwarg overrides. The transcription
provider and chunker are stubbed so no audio / API is needed.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from constants import PODCAST_SLUG_LANGTALKS
from rag.sources.base import ContentChunk
from rag.sources.podcast_source import PodcastSource


def _chunk(i: int) -> ContentChunk:
    d = datetime(2026, 3, 1, tzinfo=UTC)
    return ContentChunk(
        chunk_id=f"c{i}",
        content="text",
        content_source="podcast",
        source_id="ep1",
        source_title="Ep 1",
        chunk_index=i,
        source_date_start=d,
        source_date_end=d,
    )


@pytest.fixture
def source(monkeypatch):
    # Bypass __init__'s factory wiring; inject stubs directly.
    src = PodcastSource.__new__(PodcastSource)

    class _Chunker:
        def chunk_segments(self, **kwargs):
            return [_chunk(0), _chunk(1)]

    class _Transcriber:
        async def transcribe(self, path):
            return SimpleNamespace(duration_seconds=1.0, language="en", segments=[SimpleNamespace()])

    src._chunker = _Chunker()
    src._transcription_provider = _Transcriber()

    monkeypatch.setattr(PodcastSource, "_resolve_audio_path", staticmethod(lambda sid: __import__("pathlib").Path("2026-03-01-ep.mp3")))
    monkeypatch.setattr(PodcastSource, "_load_manifest_entry", staticmethod(lambda p: {}))
    return src


async def test_defaults_to_langtalks_slug(source):
    chunks = await source.extract("2026-03-01-ep.mp3")
    assert chunks
    assert all(c.podcast_slug == PODCAST_SLUG_LANGTALKS for c in chunks)


async def test_explicit_slug_overrides(source):
    chunks = await source.extract("2026-03-01-ep.mp3", podcast_slug="other-show")
    assert all(c.podcast_slug == "other-show" for c in chunks)
