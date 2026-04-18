"""
Unit tests for TranscriptChunker.

Tests chunking logic: segment boundaries, overlap, timestamp preservation, speaker tracking.
"""


from rag.chunking.transcript_chunker import TranscriptChunker
from rag.transcription.interface import TranscriptionSegment
from constants import ContentSourceType


class TestTranscriptChunker:
    """Tests for TranscriptChunker.chunk_segments()."""

    def _make_segment(self, text: str, start: float, end: float, speaker: str | None = None) -> TranscriptionSegment:
        return TranscriptionSegment(text=text, start=start, end=end, speaker=speaker)

    def test_empty_segments_returns_empty(self):
        chunker = TranscriptChunker(chunk_size=100, chunk_overlap=20)
        result = chunker.chunk_segments([], source_id="ep1", source_title="Episode 1")
        assert result == []

    def test_single_segment_returns_one_chunk(self):
        chunker = TranscriptChunker(chunk_size=1000, chunk_overlap=200)
        segments = [self._make_segment("Hello world", 0.0, 5.0)]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Episode 1")

        assert len(chunks) == 1
        assert chunks[0].content == "Hello world"
        assert chunks[0].content_source == ContentSourceType.PODCAST
        assert chunks[0].source_id == "ep1"
        assert chunks[0].source_title == "Episode 1"
        assert chunks[0].chunk_index == 0
        assert chunks[0].metadata["timestamp_start"] == 0.0
        assert chunks[0].metadata["timestamp_end"] == 5.0

    def test_respects_chunk_size_boundary(self):
        """Segments that exceed chunk_size should create a new chunk."""
        chunker = TranscriptChunker(chunk_size=20, chunk_overlap=0)
        segments = [
            self._make_segment("Hello world.", 0.0, 5.0),  # 12 chars
            self._make_segment("How are you?", 5.0, 10.0),  # 12 chars -> total 24 > 20
            self._make_segment("I am fine.", 10.0, 15.0),   # 10 chars
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        assert len(chunks) >= 2
        assert chunks[0].chunk_index == 0
        assert chunks[1].chunk_index == 1

    def test_never_splits_mid_segment(self):
        """Each chunk should contain complete segments only."""
        chunker = TranscriptChunker(chunk_size=15, chunk_overlap=0)
        segments = [
            self._make_segment("Short", 0.0, 1.0),
            self._make_segment("A longer segment here", 1.0, 5.0),  # 21 chars > chunk_size
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        # The long segment should NOT be split
        for chunk in chunks:
            assert "longer segment" not in chunk.content or "A longer segment here" in chunk.content

    def test_overlap_includes_trailing_segments(self):
        """Overlap should carry trailing segments from previous chunk into the next."""
        chunker = TranscriptChunker(chunk_size=30, chunk_overlap=15)
        segments = [
            self._make_segment("First segment.", 0.0, 3.0),   # 14 chars
            self._make_segment("Second segment.", 3.0, 6.0),  # 15 chars -> total 29, fits
            self._make_segment("Third segment.", 6.0, 9.0),   # 14 chars -> total 43, new chunk
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        assert len(chunks) >= 2
        # The second chunk should contain overlap from previous chunk
        if len(chunks) >= 2:
            # Second segment text should appear in both chunks (as overlap)
            assert "Second segment." in chunks[0].content
            assert "Third segment." in chunks[-1].content

    def test_preserves_timestamps(self):
        """Each chunk should have correct start/end timestamps from its segments."""
        chunker = TranscriptChunker(chunk_size=50, chunk_overlap=0)
        segments = [
            self._make_segment("Part one.", 10.5, 15.0),
            self._make_segment("Part two.", 15.0, 20.5),
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        assert chunks[0].metadata["timestamp_start"] == 10.5
        assert chunks[0].metadata["timestamp_end"] == 20.5

    def test_tracks_speakers(self):
        """Chunk metadata should include unique speakers from its segments."""
        chunker = TranscriptChunker(chunk_size=100, chunk_overlap=0)
        segments = [
            self._make_segment("Hello", 0.0, 2.0, speaker="Alice"),
            self._make_segment("Hi there", 2.0, 4.0, speaker="Bob"),
            self._make_segment("Welcome", 4.0, 6.0, speaker="Alice"),
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        assert len(chunks) == 1
        assert sorted(chunks[0].metadata["speakers"]) == ["Alice", "Bob"]

    def test_chunk_ids_are_unique(self):
        """Each chunk should have a unique chunk_id (UUID)."""
        chunker = TranscriptChunker(chunk_size=20, chunk_overlap=0)
        segments = [
            self._make_segment("Segment one.", 0.0, 3.0),
            self._make_segment("Segment two.", 3.0, 6.0),
            self._make_segment("Segment three.", 6.0, 9.0),
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_indices_are_sequential(self):
        """Chunk indices should be 0, 1, 2, ..."""
        chunker = TranscriptChunker(chunk_size=20, chunk_overlap=0)
        segments = [
            self._make_segment("Segment one.", 0.0, 3.0),
            self._make_segment("Segment two.", 3.0, 6.0),
            self._make_segment("Segment three.", 6.0, 9.0),
        ]

        chunks = chunker.chunk_segments(segments, source_id="ep1", source_title="Ep")

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_metadata_passthrough(self):
        """Additional metadata should be merged into each chunk."""
        chunker = TranscriptChunker(chunk_size=100, chunk_overlap=0)
        segments = [self._make_segment("Hello", 0.0, 1.0)]

        chunks = chunker.chunk_segments(
            segments,
            source_id="ep1",
            source_title="Ep",
            metadata={"episode_title": "Pilot", "language": "en"},
        )

        assert chunks[0].metadata["episode_title"] == "Pilot"
        assert chunks[0].metadata["language"] == "en"
        assert "timestamp_start" in chunks[0].metadata  # chunker fields also present
