"""
Transcript Chunker

Speaker-aware, timestamp-preserving chunking strategy for podcast transcripts.
Chunks by character count while respecting segment boundaries.
"""

import uuid
from datetime import datetime

from constants import ContentSourceType
from rag.chunking.base import ChunkingStrategyInterface
from rag.sources.base import ContentChunk
from rag.transcription.interface import TranscriptionSegment


class TranscriptChunker(ChunkingStrategyInterface):
    """
    Chunking strategy for audio transcripts.

    - Chunks by character count with configurable size and overlap
    - Never splits mid-segment (respects timestamp boundaries)
    - Preserves speaker attribution in chunk metadata
    - Each chunk includes timestamp_start, timestamp_end, speakers
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        """
        Args:
            chunk_size: Target chunk size in characters
            chunk_overlap: Overlap in characters between consecutive chunks
        """
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(
        self,
        content: str,
        source_id: str,
        source_title: str,
        source_date_start: datetime,
        source_date_end: datetime,
        metadata: dict | None = None,
    ) -> list[ContentChunk]:
        """
        Chunk plain text content (fallback when segments are not available).

        For segment-aware chunking, use chunk_segments() instead.
        """
        segments = [
            TranscriptionSegment(text=content, start=0.0, end=0.0, speaker=None)
        ]
        return self.chunk_segments(
            segments=segments,
            source_id=source_id,
            source_title=source_title,
            source_date_start=source_date_start,
            source_date_end=source_date_end,
            metadata=metadata,
        )

    def chunk_segments(
        self,
        segments: list[TranscriptionSegment],
        source_id: str,
        source_title: str,
        source_date_start: datetime,
        source_date_end: datetime,
        metadata: dict | None = None,
    ) -> list[ContentChunk]:
        """
        Chunk transcript segments while preserving timestamp boundaries.

        Groups consecutive segments until the character limit is reached,
        then starts a new chunk. Overlap is achieved by including trailing
        segments from the previous chunk in the next one.

        Args:
            segments: List of TranscriptionSegment instances
            source_id: Parent source identifier (e.g., episode ID)
            source_title: Human-readable source title
            metadata: Additional metadata to merge into each chunk

        Returns:
            List of ContentChunk instances
        """
        if not segments:
            return []

        base_metadata = metadata or {}
        chunks: list[ContentChunk] = []
        chunk_index = 0

        current_segments: list[TranscriptionSegment] = []
        current_char_count = 0

        for segment in segments:
            seg_len = len(segment.text)

            if current_char_count + seg_len > self._chunk_size and current_segments:
                chunks.append(
                    self._build_chunk(
                        current_segments, chunk_index, source_id, source_title,
                        source_date_start, source_date_end, base_metadata
                    )
                )
                chunk_index += 1

                overlap_segments: list[TranscriptionSegment] = []
                overlap_chars = 0
                for prev_seg in reversed(current_segments):
                    if overlap_chars + len(prev_seg.text) > self._chunk_overlap:
                        break
                    overlap_segments.insert(0, prev_seg)
                    overlap_chars += len(prev_seg.text)

                current_segments = overlap_segments
                current_char_count = overlap_chars

            current_segments.append(segment)
            current_char_count += seg_len

        if current_segments:
            chunks.append(
                self._build_chunk(
                    current_segments, chunk_index, source_id, source_title,
                    source_date_start, source_date_end, base_metadata
                )
            )

        return chunks

    def _build_chunk(
        self,
        segments: list[TranscriptionSegment],
        chunk_index: int,
        source_id: str,
        source_title: str,
        source_date_start: datetime,
        source_date_end: datetime,
        base_metadata: dict,
    ) -> ContentChunk:
        """Build a ContentChunk from a group of segments."""
        text = " ".join(seg.text for seg in segments)
        speakers = sorted({seg.speaker for seg in segments if seg.speaker})
        timestamp_start = segments[0].start
        timestamp_end = segments[-1].end

        chunk_metadata = {
            **base_metadata,
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "speakers": speakers,
        }

        return ContentChunk(
            chunk_id=str(uuid.uuid4()),
            content=text,
            content_source=ContentSourceType.PODCAST,
            source_id=source_id,
            source_title=source_title,
            chunk_index=chunk_index,
            source_date_start=source_date_start,
            source_date_end=source_date_end,
            metadata=chunk_metadata,
        )
