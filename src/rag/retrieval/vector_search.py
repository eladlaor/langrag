"""
MongoDB Vector Search Wrapper

Wraps the $vectorSearch aggregation pipeline for the rag_chunks collection.
Supports content-source filtering and date-range scoping ("AI info melts like
ice cream" — callers can constrain retrieval to content from a given window).
"""

import logging
from datetime import datetime
from typing import Any

from bson.binary import Binary, BinaryVectorDtype
from pymongo.asynchronous.collection import AsyncCollection

from config import get_settings
from constants import (
    RAG_VECTOR_INDEX_NAME,
    RAG_VECTOR_SEARCH_MAX_NUM_CANDIDATES as _MAX_NUM_CANDIDATES,
    RAG_VECTOR_SEARCH_MIN_NUM_CANDIDATES as _MIN_NUM_CANDIDATES,
)
from custom_types.field_keys import RAGChunkKeys as Keys

logger = logging.getLogger(__name__)


async def vector_search_chunks(
    collection: AsyncCollection,
    query_embedding: list[float],
    content_sources: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    top_k: int = 20,
    min_score: float = 0.5,
) -> list[dict[str, Any]]:
    """
    Perform vector search on the rag_chunks collection.

    Uses MongoDB $vectorSearch aggregation with optional content_source and
    date-range filtering. The date filter selects chunks whose source date
    range overlaps with the requested window:
        chunk.source_date_start <= date_end AND chunk.source_date_end >= date_start

    Args:
        collection: rag_chunks AsyncCollection
        query_embedding: Query embedding vector (1536-dim)
        content_sources: Optional list of content source types to filter by
        date_start: Optional inclusive lower bound on source date range
        date_end: Optional inclusive upper bound on source date range
        top_k: Number of results to return
        min_score: Minimum `vectorSearchScore` floor in [0, 1]. NOTE: this is
            the NORMALIZED Atlas score `(1 + cosine) / 2`, NOT raw cosine, since
            it is compared directly against `$meta:"vectorSearchScore"` below. A
            value of 0.5 corresponds to raw cosine 0.0; 0.7 to raw cosine 0.4.
            This matches the domain of `config.rag.min_similarity_score` and the
            hybrid path's `min_vector_score` so all retrieval paths agree.
            (Contrast DiscussionsRepository.find_similar_discussions, which
            instead accepts a RAW-cosine floor and converts it internally.)

    Returns:
        List of chunk documents with added 'search_score' field, sorted by score descending
    """
    pre_filter: dict[str, Any] = {}
    if content_sources:
        pre_filter[Keys.CONTENT_SOURCE] = {"$in": content_sources}
    if date_end is not None:
        pre_filter[Keys.SOURCE_DATE_START] = {"$lte": date_end}
    if date_start is not None:
        pre_filter[Keys.SOURCE_DATE_END] = {"$gte": date_start}

    # Encode the query vector as BSON Binary subtype 9 (FLOAT32). MongoDB 8.1+
    # accepts BinData queryVectors against scalar-quantized vector indexes and
    # this avoids serializing a 1536-element BSON array on every request.
    query_vector_bin = Binary.from_vector(
        list(query_embedding),
        dtype=BinaryVectorDtype.FLOAT32,
    )

    num_candidates_multiplier = get_settings().rag.vector_search_num_candidates_multiplier
    # Enforce both the configured multiplier and an absolute recall floor, then
    # cap so a large top_k can't over-request. Without the floor, a small top_k
    # drives numCandidates below what HNSW needs for stable recall.
    num_candidates = min(max(top_k * num_candidates_multiplier, _MIN_NUM_CANDIDATES), _MAX_NUM_CANDIDATES)
    vector_search_stage: dict[str, Any] = {
        "$vectorSearch": {
            "index": RAG_VECTOR_INDEX_NAME,
            "path": Keys.EMBEDDING,
            "queryVector": query_vector_bin,
            "numCandidates": num_candidates,
            "limit": top_k,
        }
    }
    if pre_filter:
        vector_search_stage["$vectorSearch"]["filter"] = pre_filter

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
        results = (await collection.aggregate(pipeline)).to_list()
        logger.info(
            f"Vector search returned {len(results)} chunks "
            f"(top_k={top_k}, min_score={min_score}, "
            f"date_filter={'yes' if (date_start or date_end) else 'no'})"
        )
        return results
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        raise
