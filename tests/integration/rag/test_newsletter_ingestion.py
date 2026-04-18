"""
Integration tests for newsletter ingestion pipeline.

Requires Docker with MongoDB running. Tests the full flow:
newsletter doc in MongoDB -> extract -> chunk -> embed -> store in rag_chunks.

Run:
    docker compose exec app pytest tests/integration/rag/test_newsletter_ingestion.py -v

NOTE: These tests are skipped when run outside Docker (MongoDB not reachable).
"""

import uuid

import pytest
from unittest.mock import AsyncMock, patch

from constants import ContentSourceType, NewsletterVersionType, COLLECTION_RAG_CHUNKS
from custom_types.field_keys import DbFieldKeys, NewsletterStructureKeys, RAGChunkKeys as Keys

# Test newsletter content — multi-section markdown
_TEST_NEWSLETTER_ID = f"test_ingestion_{uuid.uuid4().hex[:8]}"
_TEST_MARKDOWN = """## Primary Discussion: AI Agents in Production

The community had an in-depth conversation about deploying AI agents in production.
Key topics included reliability, cost management, and monitoring strategies.
Several members shared their experiences with LangGraph-based agent systems.

## Secondary Discussion: Vector Databases Comparison

A comparison thread explored different vector database options including Pinecone,
Weaviate, and MongoDB Atlas Vector Search. Performance benchmarks and pricing
were the main focus points.

## Worth Mentioning

- New Claude model release discussion
- Quick tip about prompt caching
- Community meetup announcement
"""

_TEST_NEWSLETTER_DOC = {
    DbFieldKeys.NEWSLETTER_ID: _TEST_NEWSLETTER_ID,
    DbFieldKeys.DATA_SOURCE_NAME: "langtalks",
    DbFieldKeys.START_DATE: "2025-03-01",
    DbFieldKeys.END_DATE: "2025-03-14",
    DbFieldKeys.CHAT_NAME: "LangTalks Community",
    DbFieldKeys.DESIRED_LANGUAGE: "english",
    DbFieldKeys.NEWSLETTER_TYPE: "per_chat",
    DbFieldKeys.STATUS: "completed",
    DbFieldKeys.VERSIONS: {
        str(NewsletterVersionType.TRANSLATED): {
            NewsletterStructureKeys.MARKDOWN_CONTENT: _TEST_MARKDOWN,
        },
    },
}


async def _is_mongodb_available() -> bool:
    """Check if MongoDB is reachable."""
    try:
        from db.connection import get_database
        db = await get_database()
        await db.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def skip_if_no_mongodb():
    """Skip tests if MongoDB is not available."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        available = loop.run_until_complete(_is_mongodb_available())
    finally:
        loop.close()
    if not available:
        pytest.skip("MongoDB not available — run tests inside Docker")


@pytest.fixture
async def seed_newsletter(skip_if_no_mongodb):
    """Insert a test newsletter document and clean up after test."""
    from db.connection import get_database
    from constants import COLLECTION_NEWSLETTERS

    db = await get_database()
    collection = db[COLLECTION_NEWSLETTERS]

    # Insert test newsletter
    await collection.insert_one(_TEST_NEWSLETTER_DOC.copy())

    yield _TEST_NEWSLETTER_ID

    # Cleanup: remove test newsletter and any chunks
    await collection.delete_many({DbFieldKeys.NEWSLETTER_ID: _TEST_NEWSLETTER_ID})
    chunks_collection = db[COLLECTION_RAG_CHUNKS]
    await chunks_collection.delete_many({Keys.SOURCE_ID: _TEST_NEWSLETTER_ID})


@pytest.fixture
async def cleanup_chunks(skip_if_no_mongodb):
    """Clean up rag_chunks for the test newsletter after test."""
    yield
    from db.connection import get_database
    db = await get_database()
    chunks_collection = db[COLLECTION_RAG_CHUNKS]
    await chunks_collection.delete_many({Keys.SOURCE_ID: _TEST_NEWSLETTER_ID})


class TestNewsletterIngestion:
    """Integration tests for the newsletter ingestion pipeline."""

    async def test_ingest_newsletter_stores_chunks(self, seed_newsletter):
        """Full ingestion: newsletter -> chunks in rag_chunks with correct fields."""
        from rag.sources.newsletter_source import NewsletterSource
        from rag.ingestion.pipeline import IngestionPipeline

        source = NewsletterSource()
        pipeline = IngestionPipeline()

        result = await pipeline.ingest(source, seed_newsletter)

        assert result["skipped"] is False
        assert result["chunks_stored"] > 0
        assert result["chunks_extracted"] > 0

        # Verify chunks in MongoDB
        from db.connection import get_database
        db = await get_database()
        chunks = await db[COLLECTION_RAG_CHUNKS].find(
            {Keys.SOURCE_ID: seed_newsletter}
        ).to_list(length=None)

        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk[Keys.CONTENT_SOURCE] == str(ContentSourceType.NEWSLETTER)
            assert chunk[Keys.SOURCE_ID] == seed_newsletter
            assert chunk[Keys.CONTENT]  # Non-empty content
            assert Keys.METADATA in chunk

    async def test_ingest_idempotent_skips_duplicate(self, seed_newsletter):
        """Second ingest of same newsletter should skip."""
        from rag.sources.newsletter_source import NewsletterSource
        from rag.ingestion.pipeline import IngestionPipeline

        source = NewsletterSource()
        pipeline = IngestionPipeline()

        # First ingest
        result1 = await pipeline.ingest(source, seed_newsletter)
        assert result1["skipped"] is False

        # Second ingest — should skip
        result2 = await pipeline.ingest(source, seed_newsletter)
        assert result2["skipped"] is True
        assert result2["chunks_stored"] == 0

    async def test_ingest_force_refresh_replaces_chunks(self, seed_newsletter):
        """force_refresh=True should delete old chunks and re-ingest."""
        from rag.sources.newsletter_source import NewsletterSource
        from rag.ingestion.pipeline import IngestionPipeline

        source = NewsletterSource()
        pipeline = IngestionPipeline()

        # First ingest
        result1 = await pipeline.ingest(source, seed_newsletter)
        original_count = result1["chunks_stored"]

        # Force refresh
        result2 = await pipeline.ingest(source, seed_newsletter, force_refresh=True)
        assert result2["skipped"] is False
        assert result2["chunks_stored"] == original_count

    async def test_chunks_have_embeddings(self, seed_newsletter):
        """Stored chunks should have non-empty embedding vectors."""
        from rag.sources.newsletter_source import NewsletterSource
        from rag.ingestion.pipeline import IngestionPipeline
        from db.connection import get_database

        source = NewsletterSource()
        pipeline = IngestionPipeline()
        await pipeline.ingest(source, seed_newsletter)

        db = await get_database()
        chunks = await db[COLLECTION_RAG_CHUNKS].find(
            {Keys.SOURCE_ID: seed_newsletter}
        ).to_list(length=None)

        for chunk in chunks:
            assert Keys.EMBEDDING in chunk
            embedding = chunk[Keys.EMBEDDING]
            assert isinstance(embedding, list)
            assert len(embedding) > 0
            assert all(isinstance(v, float) for v in embedding)

    async def test_chunks_metadata_includes_newsletter_fields(self, seed_newsletter):
        """Chunks should carry newsletter-specific metadata."""
        from rag.sources.newsletter_source import NewsletterSource
        from rag.ingestion.pipeline import IngestionPipeline
        from db.connection import get_database

        source = NewsletterSource()
        pipeline = IngestionPipeline()
        await pipeline.ingest(source, seed_newsletter)

        db = await get_database()
        chunks = await db[COLLECTION_RAG_CHUNKS].find(
            {Keys.SOURCE_ID: seed_newsletter}
        ).to_list(length=None)

        for chunk in chunks:
            metadata = chunk[Keys.METADATA]
            assert "newsletter_date_range" in metadata
            assert "data_source_name" in metadata
            assert "section_title" in metadata
            assert "section_type" in metadata
