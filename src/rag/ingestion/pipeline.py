"""
RAG Ingestion Pipeline

Source-agnostic pipeline: extract -> chunk -> embed -> store.
Idempotent: checks if source_id already ingested before re-processing.
"""

import asyncio
import logging
from typing import Any

from config import get_settings
from custom_types.field_keys import RAGChunkKeys as Keys
from db.connection import get_database
from db.repositories.chunks import ChunksRepository
from rag.sources.base import ContentSourceInterface
from utils.embedding.factory import EmbeddingProviderFactory

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Source-agnostic ingestion pipeline for RAG content.

    Flow:
    1. Receives a ContentSourceInterface instance
    2. Calls source.extract() to get ContentChunk list
    3. Embeds all chunks via EmbeddingProviderFactory
    4. Stores chunks + embeddings in rag_chunks via ChunksRepository
    5. Idempotent: skips sources that are already ingested
    """

    def __init__(self) -> None:
        self._embedder = EmbeddingProviderFactory.create()
        self._embedding_model = get_settings().embedding.default_model

    async def ingest(
        self,
        source: ContentSourceInterface,
        source_id: str,
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Ingest a single source: extract, chunk, embed, store.

        Args:
            source: ContentSourceInterface implementation
            source_id: Identifier for the specific source to ingest
            force_refresh: If True, delete existing chunks and re-ingest
            **kwargs: Passed to source.extract()

        Returns:
            Dict with ingestion stats (chunks_stored, source_id, skipped, etc.)
        """
        db = await get_database()
        chunks_repo = ChunksRepository(db)

        # Idempotency check
        if not force_refresh and await chunks_repo.source_exists(source_id):
            logger.info(f"Source already ingested, skipping: source_id={source_id}")
            return {
                "source_id": source_id,
                "skipped": True,
                "reason": "already_ingested",
                "chunks_stored": 0,
            }

        # Delete existing chunks if force_refresh
        if force_refresh:
            deleted = await chunks_repo.delete_source_chunks(source_id)
            logger.info(f"Force refresh: deleted {deleted} existing chunks for source_id={source_id}")

        # Step 1: Extract and chunk
        logger.info(f"Extracting source: type={source.source_type}, source_id={source_id}")
        chunks = await source.extract(source_id, **kwargs)

        if not chunks:
            logger.warning(f"No chunks extracted from source_id={source_id}")
            return {
                "source_id": source_id,
                "skipped": False,
                "reason": "no_chunks_extracted",
                "chunks_stored": 0,
            }

        # Step 2: Embed
        logger.info(f"Embedding {len(chunks)} chunks for source_id={source_id}")
        texts = [chunk.content for chunk in chunks]
        embeddings = await asyncio.to_thread(self._embedder.embed_texts_batch, texts)

        # Step 3: Build documents for storage
        documents = []
        for chunk, embedding in zip(chunks, embeddings):
            if embedding is None:
                logger.warning(f"Embedding failed for chunk_id={chunk.chunk_id}, skipping")
                continue

            documents.append({
                Keys.CHUNK_ID: chunk.chunk_id,
                Keys.CONTENT_SOURCE: str(chunk.content_source),
                Keys.SOURCE_ID: chunk.source_id,
                Keys.SOURCE_TITLE: chunk.source_title,
                Keys.CONTENT: chunk.content,
                Keys.EMBEDDING: embedding,
                Keys.EMBEDDING_MODEL: self._embedding_model,
                Keys.CHUNK_INDEX: chunk.chunk_index,
                Keys.METADATA: chunk.metadata,
            })

        # Step 4: Store
        stored = await chunks_repo.store_chunks(documents)
        logger.info(f"Ingestion complete: source_id={source_id}, chunks_stored={stored}")

        return {
            "source_id": source_id,
            "skipped": False,
            "chunks_extracted": len(chunks),
            "chunks_stored": stored,
            "chunks_failed_embedding": len(chunks) - stored,
        }

    async def ingest_batch(
        self,
        source: ContentSourceInterface,
        source_ids: list[str],
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Ingest multiple sources sequentially.

        Args:
            source: ContentSourceInterface implementation
            source_ids: List of source identifiers to ingest
            force_refresh: If True, re-ingest already processed sources
            **kwargs: Passed to source.extract()

        Returns:
            List of per-source ingestion result dicts
        """
        results = []
        for source_id in source_ids:
            try:
                result = await self.ingest(source, source_id, force_refresh=force_refresh, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Ingestion failed for source_id={source_id}: {e}")
                results.append({
                    "source_id": source_id,
                    "skipped": False,
                    "error": str(e),
                    "chunks_stored": 0,
                })
        return results
