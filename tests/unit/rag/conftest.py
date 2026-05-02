"""
Shared fixtures for RAG unit tests.

Auto-injects default source_date_start / source_date_end into chunker calls so
existing tests don't have to repeat the date arguments. Real production code
must always pass them explicitly; the fixtures here only cover unit tests where
the date values are not under test.
"""

from datetime import UTC, datetime

import pytest


DEFAULT_TEST_SOURCE_DATE_START = datetime(2026, 3, 1, tzinfo=UTC)
DEFAULT_TEST_SOURCE_DATE_END = datetime(2026, 3, 14, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _inject_default_chunker_dates(monkeypatch):
    """Inject default test dates into MarkdownChunker.chunk and TranscriptChunker.chunk_segments
    when the caller omits them. Production code must always pass dates explicitly; this
    keeps the unit tests focused on chunking behaviour rather than date plumbing.
    """
    from rag.chunking import markdown_chunker as md_mod
    from rag.chunking import transcript_chunker as tx_mod

    original_md_chunk = md_mod.MarkdownChunker.chunk
    original_tx_chunk_segments = tx_mod.TranscriptChunker.chunk_segments
    original_tx_chunk = tx_mod.TranscriptChunker.chunk

    def md_chunk_with_default_dates(self, content, source_id, source_title,
                                    source_date_start=None, source_date_end=None,
                                    metadata=None):
        return original_md_chunk(
            self,
            content=content,
            source_id=source_id,
            source_title=source_title,
            source_date_start=source_date_start or DEFAULT_TEST_SOURCE_DATE_START,
            source_date_end=source_date_end or DEFAULT_TEST_SOURCE_DATE_END,
            metadata=metadata,
        )

    def tx_chunk_segments_with_default_dates(self, segments, source_id, source_title,
                                             source_date_start=None, source_date_end=None,
                                             metadata=None):
        return original_tx_chunk_segments(
            self,
            segments=segments,
            source_id=source_id,
            source_title=source_title,
            source_date_start=source_date_start or DEFAULT_TEST_SOURCE_DATE_START,
            source_date_end=source_date_end or DEFAULT_TEST_SOURCE_DATE_END,
            metadata=metadata,
        )

    def tx_chunk_with_default_dates(self, content, source_id, source_title,
                                    source_date_start=None, source_date_end=None,
                                    metadata=None):
        return original_tx_chunk(
            self,
            content=content,
            source_id=source_id,
            source_title=source_title,
            source_date_start=source_date_start or DEFAULT_TEST_SOURCE_DATE_START,
            source_date_end=source_date_end or DEFAULT_TEST_SOURCE_DATE_END,
            metadata=metadata,
        )

    monkeypatch.setattr(md_mod.MarkdownChunker, "chunk", md_chunk_with_default_dates)
    monkeypatch.setattr(tx_mod.TranscriptChunker, "chunk_segments", tx_chunk_segments_with_default_dates)
    monkeypatch.setattr(tx_mod.TranscriptChunker, "chunk", tx_chunk_with_default_dates)
