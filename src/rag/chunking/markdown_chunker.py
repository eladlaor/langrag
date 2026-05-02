"""
Markdown Chunker

Section-aware chunking strategy for newsletter markdown content.
Splits on markdown headers while preserving discussion boundaries.
Never splits mid-discussion if under the chunk size limit.
"""

import re
import uuid
from datetime import datetime

from constants import ContentSourceType
from rag.chunking.base import ChunkingStrategyInterface
from rag.sources.base import ContentChunk

# Section type detection patterns (ordered by specificity)
_SECTION_TYPE_PATTERNS = {
    "primary_discussion": re.compile(r"(primary|main|featured)\s+(discussion|topic)", re.IGNORECASE),
    "secondary_discussion": re.compile(r"(secondary|additional|other)\s+(discussion|topic)", re.IGNORECASE),
    "worth_mentioning": re.compile(r"(worth\s+mentioning|brief\s+mention|also\s+noted)", re.IGNORECASE),
    "intro": re.compile(r"(introduction|overview|welcome|hello|summary)", re.IGNORECASE),
    "outro": re.compile(r"(conclusion|closing|next\s+time|until\s+next|see\s+you)", re.IGNORECASE),
}

# Markdown header pattern: captures level (number of #) and title text
_HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


class MarkdownChunker(ChunkingStrategyInterface):
    """
    Section-aware chunking strategy for newsletter markdown content.

    - Splits on markdown headers (##, ###) to preserve discussion boundaries
    - Never splits mid-discussion if the section fits within chunk_size
    - Large sections are split at paragraph boundaries with overlap
    - Each chunk carries section_title and section_type metadata
    """

    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 300) -> None:
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
        Chunk markdown content into section-aware chunks.

        Args:
            content: Raw markdown text
            source_id: Parent newsletter identifier
            source_title: Human-readable newsletter title
            source_date_start: Earliest date the newsletter covers
            source_date_end: Latest date the newsletter covers
            metadata: Additional metadata (data_source_name, etc.)

        Returns:
            List of ContentChunk instances
        """
        if not content or not content.strip():
            return []

        base_metadata = metadata or {}
        sections = self._split_into_sections(content)

        chunks: list[ContentChunk] = []
        chunk_index = 0

        for section_title, section_body in sections:
            section_type = self._classify_section(section_title)
            section_metadata = {
                **base_metadata,
                "section_title": section_title,
                "section_type": section_type,
            }

            # If the section fits within chunk_size, keep it as one chunk
            section_text = f"## {section_title}\n\n{section_body}".strip() if section_title else section_body.strip()

            if len(section_text) <= self._chunk_size:
                if section_text:
                    chunks.append(self._build_chunk(
                        text=section_text,
                        chunk_index=chunk_index,
                        source_id=source_id,
                        source_title=source_title,
                        source_date_start=source_date_start,
                        source_date_end=source_date_end,
                        metadata=section_metadata,
                    ))
                    chunk_index += 1
            else:
                # Section is too large — split at paragraph boundaries
                sub_chunks = self._split_large_section(
                    section_text=section_text,
                    chunk_index=chunk_index,
                    source_id=source_id,
                    source_title=source_title,
                    source_date_start=source_date_start,
                    source_date_end=source_date_end,
                    metadata=section_metadata,
                )
                chunks.extend(sub_chunks)
                chunk_index += len(sub_chunks)

        return chunks

    def _split_into_sections(self, content: str) -> list[tuple[str, str]]:
        """
        Split markdown content into (title, body) pairs based on headers.

        Returns a list of (section_title, section_body) tuples.
        Content before the first header gets an empty title.
        """
        sections: list[tuple[str, str]] = []
        header_matches = list(_HEADER_PATTERN.finditer(content))

        if not header_matches:
            # No headers — treat entire content as one section
            return [("", content)]

        # Content before first header (if any)
        first_header_start = header_matches[0].start()
        if first_header_start > 0:
            preamble = content[:first_header_start].strip()
            if preamble:
                sections.append(("", preamble))

        # Each header and its content until the next header
        for i, match in enumerate(header_matches):
            title = match.group(2).strip()
            body_start = match.end()
            body_end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(content)
            body = content[body_start:body_end].strip()
            sections.append((title, body))

        return sections

    def _split_large_section(
        self,
        section_text: str,
        chunk_index: int,
        source_id: str,
        source_title: str,
        source_date_start: datetime,
        source_date_end: datetime,
        metadata: dict,
    ) -> list[ContentChunk]:
        """Split a large section at paragraph boundaries with overlap."""
        paragraphs = re.split(r"\n\n+", section_text)
        chunks: list[ContentChunk] = []

        current_parts: list[str] = []
        current_len = 0

        for paragraph in paragraphs:
            para_len = len(paragraph)

            if current_len + para_len > self._chunk_size and current_parts:
                chunk_text = "\n\n".join(current_parts)
                chunks.append(self._build_chunk(
                    text=chunk_text,
                    chunk_index=chunk_index + len(chunks),
                    source_id=source_id,
                    source_title=source_title,
                    source_date_start=source_date_start,
                    source_date_end=source_date_end,
                    metadata=metadata,
                ))

                overlap_parts: list[str] = []
                overlap_len = 0
                for prev_part in reversed(current_parts):
                    if overlap_len + len(prev_part) > self._chunk_overlap:
                        break
                    overlap_parts.insert(0, prev_part)
                    overlap_len += len(prev_part)

                current_parts = overlap_parts
                current_len = overlap_len

            current_parts.append(paragraph)
            current_len += para_len

        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(self._build_chunk(
                text=chunk_text,
                chunk_index=chunk_index + len(chunks),
                source_id=source_id,
                source_title=source_title,
                source_date_start=source_date_start,
                source_date_end=source_date_end,
                metadata=metadata,
            ))

        return chunks

    @staticmethod
    def _classify_section(title: str) -> str:
        """Classify a section title into a section type."""
        if not title:
            return "intro"

        for section_type, pattern in _SECTION_TYPE_PATTERNS.items():
            if pattern.search(title):
                return section_type

        # Default: treat any titled section as a discussion
        return "secondary_discussion"

    @staticmethod
    def _build_chunk(
        text: str,
        chunk_index: int,
        source_id: str,
        source_title: str,
        source_date_start: datetime,
        source_date_end: datetime,
        metadata: dict,
    ) -> ContentChunk:
        """Build a ContentChunk from text."""
        return ContentChunk(
            chunk_id=str(uuid.uuid4()),
            content=text,
            content_source=ContentSourceType.NEWSLETTER,
            source_id=source_id,
            source_title=source_title,
            chunk_index=chunk_index,
            source_date_start=source_date_start,
            source_date_end=source_date_end,
            metadata=metadata,
        )
