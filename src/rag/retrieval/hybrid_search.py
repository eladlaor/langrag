"""
MongoDB Hybrid Search via $rankFusion

Server-side Reciprocal Rank Fusion (MongoDB 8.1+) combining $vectorSearch and
$search over rag_chunks in a single aggregation. Replaces client-side fusion
and removes the need for a second store. Returned chunks carry the same
content_source / source_date_start / source_date_end fields as vector_search,
so downstream rerank + freshness logic stays unchanged.

$rankFusion returns RRF-fused scores (typically in the ~[0, 0.03] range) that
are NOT comparable to cosine similarity. To keep downstream code (MMR rerank,
citation UI, eval gates) score-scale-compatible with vector_search, the raw
fused score is min-max normalized into [0, 1] across the returned page and
written to `search_score`. The raw RRF score is preserved under `rrf_score`
for debugging. Score-threshold gating (min_score) is not applied here; use
top_k bounding instead.
"""

import logging
from datetime import datetime
from typing import Any

from bson.binary import Binary, BinaryVectorDtype
from motor.motor_asyncio import AsyncIOMotorCollection

from config import get_settings
from constants import (
    RAG_HYBRID_LEXICAL_WEIGHT,
    RAG_HYBRID_VECTOR_WEIGHT,
    RAG_LEXICAL_INDEX_NAME,
    RAG_SEARCH_SCORE_FIELD,
    RAG_VECTOR_INDEX_NAME,
)
from custom_types.field_keys import RAGChunkKeys as Keys
from db.queries.rankfusion import (
    RRF_RAW_SCORE_FIELD,
    build_rankfusion_pipeline,
    normalize_rrf_scores,
)

# Atlas Search caps numCandidates around 10,000 in practice; keep a defensive
# upper bound so callers can't accidentally over-request.
_MAX_NUM_CANDIDATES = 1000

logger = logging.getLogger(__name__)

# Backwards-compatible re-export: prior callers imported RRF_RAW_SCORE_FIELD
# from this module. The canonical definition now lives in db.queries.rankfusion;
# keep the name available here so external code doesn't break.
__all__ = ["hybrid_search_chunks", "RRF_RAW_SCORE_FIELD", "_normalize_rrf_scores"]


def _normalize_rrf_scores(results: list[dict[str, Any]]) -> None:
    """Backwards-compatible wrapper over `normalize_rrf_scores`.

    Pre-v1.13.0 callers (notably `tests/unit/rag/test_hybrid_search.py`)
    imported a private `_normalize_rrf_scores` from this module. The shared
    helper now lives at `db.queries.rankfusion.normalize_rrf_scores`; this
    shim delegates with the RAG-specific score field name so existing code
    keeps working unchanged.
    """
    normalize_rrf_scores(results, score_field=RAG_SEARCH_SCORE_FIELD)


async def hybrid_search_chunks(
    collection: AsyncIOMotorCollection,
    query_text: str,
    query_embedding: list[float],
    content_sources: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    top_k: int = 20,
    vector_weight: float = RAG_HYBRID_VECTOR_WEIGHT,
    lexical_weight: float = RAG_HYBRID_LEXICAL_WEIGHT,
    debug_score_details: bool = False,
) -> list[dict[str, Any]]:
    """
    Hybrid retrieval over rag_chunks using server-side $rankFusion.

    Args:
        collection: rag_chunks AsyncIOMotorCollection
        query_text: Raw user query for the lexical leg
        query_embedding: Embedded query for the vector leg
        content_sources: Optional content_source filter
        date_start: Optional inclusive lower bound on source date range
        date_end: Optional inclusive upper bound on source date range
        top_k: Final number of fused results to return
        vector_weight: Weight of the vector leg in RRF combination
        lexical_weight: Weight of the lexical leg in RRF combination

    Returns:
        List of fused chunk documents with `search_score` (fused RRF score),
        sorted by fused rank descending.
    """
    pre_filter: dict[str, Any] = {}
    if content_sources:
        pre_filter[Keys.CONTENT_SOURCE] = {"$in": content_sources}
    if date_end is not None:
        pre_filter[Keys.SOURCE_DATE_START] = {"$lte": date_end}
    if date_start is not None:
        pre_filter[Keys.SOURCE_DATE_END] = {"$gte": date_start}

    query_vector_bin = Binary.from_vector(
        list(query_embedding),
        dtype=BinaryVectorDtype.FLOAT32,
    )

    num_candidates_multiplier = get_settings().rag.vector_search_num_candidates_multiplier
    num_candidates = min(top_k * num_candidates_multiplier, _MAX_NUM_CANDIDATES)
    vector_stage: dict[str, Any] = {
        "$vectorSearch": {
            "index": RAG_VECTOR_INDEX_NAME,
            "path": Keys.EMBEDDING,
            "queryVector": query_vector_bin,
            "numCandidates": num_candidates,
            "limit": top_k * 4,
        }
    }
    if pre_filter:
        vector_stage["$vectorSearch"]["filter"] = pre_filter

    # The lexical leg uses $search.compound so the equality (content_source)
    # and range (source_date_*) clauses are pushed into mongot and applied
    # before scoring, instead of being filtered post-hoc with a downstream
    # $match. This keeps the Lucene candidate set bounded and avoids paying
    # to score documents that will be discarded.
    lexical_search_stage = _build_lexical_search_stage(query_text, content_sources, date_start, date_end)
    lexical_pipeline: list[dict[str, Any]] = [
        lexical_search_stage,
        {"$limit": top_k * 4},
    ]

    # Surface the raw RRF score under RRF_RAW_SCORE_FIELD so we can normalize
    # it to [0, 1] in Python before downstream consumers (MMR rerank, citation
    # UI) see it under the shared search_score key. We deliberately do NOT
    # emit the un-normalized RRF score under search_score: it would silently
    # break MMR (lambda * relevance collapses to ~0 when relevance is RRF).
    pipeline = build_rankfusion_pipeline(
        vector_stage=vector_stage,
        lexical_pipeline=lexical_pipeline,
        vector_weight=vector_weight,
        lexical_weight=lexical_weight,
        top_k=top_k,
        score_details=debug_score_details,
    )

    try:
        results = await collection.aggregate(pipeline).to_list(length=None)
        normalize_rrf_scores(results, score_field=RAG_SEARCH_SCORE_FIELD)
        logger.info(
            f"Hybrid $rankFusion returned {len(results)} chunks "
            f"(top_k={top_k}, num_candidates={num_candidates}, "
            f"vector_weight={vector_weight}, lexical_weight={lexical_weight}, "
            f"date_filter={'yes' if (date_start or date_end) else 'no'})"
        )
        return results
    except Exception as e:
        logger.error(f"Hybrid search via $rankFusion failed: {e}")
        raise


def _build_lexical_search_stage(
    query_text: str,
    content_sources: list[str] | None,
    date_start: datetime | None,
    date_end: datetime | None,
) -> dict[str, Any]:
    """Build the lexical $search stage with filter clauses pushed into compound.

    Atlas Search `compound.filter` evaluates filter clauses without contributing
    to the relevance score, so mongot prunes non-matching documents before
    Lucene scoring runs. The lexical index in src/db/indexes.py declares
    content_source/source_date_start/source_date_end as filter-typed fields
    (token + date), which is what compound.filter needs.
    """
    must_clause: dict[str, Any] = {
        "text": {"query": query_text, "path": Keys.CONTENT},
    }

    filter_clauses: list[dict[str, Any]] = []
    if content_sources:
        filter_clauses.append({"in": {"path": Keys.CONTENT_SOURCE, "value": content_sources}})
    if date_end is not None:
        filter_clauses.append({"range": {"path": Keys.SOURCE_DATE_START, "lte": date_end}})
    if date_start is not None:
        filter_clauses.append({"range": {"path": Keys.SOURCE_DATE_END, "gte": date_start}})

    if not filter_clauses:
        return {
            "$search": {
                "index": RAG_LEXICAL_INDEX_NAME,
                **must_clause,
            }
        }

    return {
        "$search": {
            "index": RAG_LEXICAL_INDEX_NAME,
            "compound": {
                "must": [must_clause],
                "filter": filter_clauses,
            },
        }
    }


