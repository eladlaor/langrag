"""
Unit tests for MarkdownChunker.

Tests chunking logic: section splitting, overlap, section type classification, metadata.
"""

import pytest

from rag.chunking.markdown_chunker import MarkdownChunker
from constants import ContentSourceType


class TestMarkdownChunker:
    """Tests for MarkdownChunker.chunk()."""

    def test_empty_content_returns_empty(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        assert chunker.chunk("", source_id="nl1", source_title="NL") == []

    def test_whitespace_only_returns_empty(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        assert chunker.chunk("   \n\n  ", source_id="nl1", source_title="NL") == []

    def test_no_headers_returns_single_chunk(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "This is plain text with no markdown headers. Just regular paragraphs."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].metadata["section_title"] == ""
        assert chunks[0].metadata["section_type"] == "intro"

    def test_splits_on_headers(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Section One\n\nContent of section one.\n\n## Section Two\n\nContent of section two.\n\n## Section Three\n\nContent of section three."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) == 3
        assert "Section One" in chunks[0].content
        assert "Section Two" in chunks[1].content
        assert "Section Three" in chunks[2].content

    def test_preserves_preamble_before_first_header(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "This is the intro preamble.\n\n## First Section\n\nSection content here."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) == 2
        assert chunks[0].content == "This is the intro preamble."
        assert chunks[0].metadata["section_title"] == ""
        assert "First Section" in chunks[1].content

    def test_section_fits_in_chunk_size_stays_intact(self):
        """A section shorter than chunk_size should not be split."""
        chunker = MarkdownChunker(chunk_size=500, chunk_overlap=50)
        content = "## Short Section\n\nThis is a short section."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) == 1
        assert "Short Section" in chunks[0].content
        assert "This is a short section." in chunks[0].content

    def test_large_section_splits_at_paragraph_boundaries(self):
        """A section exceeding chunk_size should be split into multiple chunks."""
        chunker = MarkdownChunker(chunk_size=100, chunk_overlap=20)
        # Build a section with multiple paragraphs, each ~40 chars
        paragraphs = [f"Paragraph {i} with enough text to fill." for i in range(5)]
        content = "## Big Section\n\n" + "\n\n".join(paragraphs)

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) >= 2
        # All text should be present across chunks
        combined = " ".join(c.content for c in chunks)
        for p in paragraphs:
            assert p in combined

    def test_overlap_in_large_section(self):
        """Consecutive chunks from a large section should share overlap text."""
        chunker = MarkdownChunker(chunk_size=80, chunk_overlap=40)
        content = "## Big Section\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here.\n\nFourth paragraph here."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) >= 2
        # Find overlapping text between consecutive chunks
        found_overlap = False
        for i in range(len(chunks) - 1):
            # Check if any paragraph text appears in both consecutive chunks
            for word in chunks[i].content.split("\n\n"):
                if word.strip() and word.strip() in chunks[i + 1].content:
                    found_overlap = True
                    break
        assert found_overlap, "Expected overlap between consecutive chunks"

    def test_section_type_classification_primary(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Primary Discussion: AI Agents\n\nDiscussion about agents."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert chunks[0].metadata["section_type"] == "primary_discussion"

    def test_section_type_classification_worth_mentioning(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Worth Mentioning\n\nSome brief items."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert chunks[0].metadata["section_type"] == "worth_mentioning"

    def test_section_type_classification_intro(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Introduction\n\nWelcome to the newsletter."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert chunks[0].metadata["section_type"] == "intro"

    def test_section_type_classification_outro(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Conclusion\n\nSee you next time."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert chunks[0].metadata["section_type"] == "outro"

    def test_section_type_classification_unknown_defaults_secondary(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Some Random Title\n\nContent here."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert chunks[0].metadata["section_type"] == "secondary_discussion"

    def test_untitled_section_classified_as_intro(self):
        """Content without a header (preamble) gets section_type 'intro'."""
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "Preamble text before any header.\n\n## Section\n\nContent."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert chunks[0].metadata["section_type"] == "intro"

    def test_metadata_passthrough(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Section\n\nContent here."

        chunks = chunker.chunk(
            content,
            source_id="nl1",
            source_title="NL",
            metadata={"newsletter_date_range": "2025-03-01 to 2025-03-14", "data_source_name": "langtalks"},
        )

        assert chunks[0].metadata["newsletter_date_range"] == "2025-03-01 to 2025-03-14"
        assert chunks[0].metadata["data_source_name"] == "langtalks"
        assert "section_title" in chunks[0].metadata  # chunker-added fields also present

    def test_chunk_ids_are_unique(self):
        chunker = MarkdownChunker(chunk_size=50, chunk_overlap=10)
        content = "## Section One\n\nContent one.\n\n## Section Two\n\nContent two.\n\n## Section Three\n\nContent three."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_indices_are_sequential(self):
        chunker = MarkdownChunker(chunk_size=50, chunk_overlap=10)
        content = "## Section One\n\nContent one.\n\n## Section Two\n\nContent two.\n\n## Section Three\n\nContent three."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_content_source_is_newsletter(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Section\n\nContent here."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        for chunk in chunks:
            assert chunk.content_source == ContentSourceType.NEWSLETTER

    def test_source_id_and_title_propagated(self):
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Section One\n\nContent.\n\n## Section Two\n\nMore content."

        chunks = chunker.chunk(content, source_id="newsletter_abc", source_title="LangTalks Newsletter: 2025-03-01 to 2025-03-14")

        for chunk in chunks:
            assert chunk.source_id == "newsletter_abc"
            assert chunk.source_title == "LangTalks Newsletter: 2025-03-01 to 2025-03-14"

    def test_h3_headers_also_split(self):
        """The chunker should split on any header level (##, ###, etc.)."""
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "### Sub Section One\n\nContent one.\n\n### Sub Section Two\n\nContent two."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        assert len(chunks) == 2

    def test_headers_with_empty_bodies(self):
        """Headers with no body text should still produce chunks (header text only)."""
        chunker = MarkdownChunker(chunk_size=1000, chunk_overlap=100)
        content = "## Header One\n\n## Header Two\n\nSome content here."

        chunks = chunker.chunk(content, source_id="nl1", source_title="NL")

        # At least the header with content should be present
        assert len(chunks) >= 1
        assert any("Header Two" in c.content for c in chunks)
