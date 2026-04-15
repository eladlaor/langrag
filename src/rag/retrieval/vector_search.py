"""
MongoDB Vector Search Wrapper

Wraps the $vectorSearch aggregation pipeline for the rag_chunks collection.
"""

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection

from constants import RAG_VECTOR_INDEX_NAME
from custom_types.field_keys import RAGChunkKeys as Keys

logger = logging.getLogger(__name__)


async def vector_search_chunks(
    collection: AsyncIOMotorCollection,
    query_embedding: list[float],
    content_sources: list[str] | None = None,
    top_k: int = 20,
    min_score: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Perform vector search on the rag_chunks collection.

    Uses MongoDB $vectorSearch aggregation with optional content_source filtering.

    Args:
        collection: rag_chunks AsyncIOMotorCollection
        query_embedding: Query embedding vector (1536-dim)
        content_sources: Optional list of content source types to filter by
        top_k: Number of results to return
        min_score: Minimum cosine similarity score threshold

    Returns:
        List of chunk documents with added 'search_score' field, sorted by score descending
    """
    # Build $vectorSearch stage
    vector_search_stage: dict[str, Any] = {
        "$vectorSearch": {
            "index": RAG_VECTOR_INDEX_NAME,
            "path": Keys.EMBEDDING,
            "queryVector": query_embedding,
            "numCandidates": top_k * 10,
            "limit": top_k,
        }
    }

    # Add pre-filter on content_source if specified
    if content_sources:
        vector_search_stage["$vectorSearch"]["filter"] = {
            Keys.CONTENT_SOURCE: {"$in": content_sources}
        }

    pipeline = [
        vector_search_stage,
        {
            "$addFields": {
                "search_score": {"$meta": "vectorSearchScore"},
            }
        },
        {
            "$match": {
                "search_score": {"$gte": min_score},
            }
        },
        {
            "$project": {
                "_id": 0,
            }
        },
    ]

    try:
        results = await collection.aggregate(pipeline).to_list(length=None)
        logger.info(f"Vector search returned {len(results)} chunks (top_k={top_k}, min_score={min_score})")
        return results
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        raise
