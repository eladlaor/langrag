"""Hybrid retrieval over `agent_memories` via MongoDB 8.1+ `$rankFusion`.

Mirrors the RAG hybrid retriever pattern (`src/rag/retrieval/hybrid_search.py`)
using the shared builder from `db.queries.rankfusion`. Every query MUST
pre-filter on `user_id` — that is the multi-tenancy boundary, enforced at
the aggregation layer (not just in Python), so cross-tenant data simply
cannot be returned even by a buggy caller.

The fused RRF score is min-max normalized into [0, 1] under `score` so the
retriever can rank items uniformly across the page.
"""

from __future__ import annotations

import logging
from typing import Any

from bson.binary import Binary, BinaryVectorDtype
from motor.motor_asyncio import AsyncIOMotorCollection

from config import get_settings
from constants import (
    AGENT_MEMORY_HYBRID_LEXICAL_WEIGHT,
    AGENT_MEMORY_HYBRID_VECTOR_WEIGHT,
    AGENT_MEMORY_LEXICAL_INDEX_NAME,
    AGENT_MEMORY_VECTOR_INDEX_NAME,
)
from custom_types.db_schemas import MemoryNamespace
from custom_types.field_keys import AgentMemoryKeys as Keys
from db.queries.rankfusion import build_rankfusion_pipeline, normalize_rrf_scores

logger = logging.getLogger(__name__)

# Field where the [0, 1]-normalized fused RRF score lands. Distinct from
# the raw rrf_score field so debugging can inspect both.
MEMORY_SCORE_FIELD = "score"

# Defensive upper bound on numCandidates, matching the RAG retriever.
_MAX_NUM_CANDIDATES = 1000


async def hybrid_search_memories(
    collection: AsyncIOMotorCollection,
    user_id: str,
    query_text: str,
    query_embedding: list[float],
    *,
    namespace: MemoryNamespace | str | None = None,
    top_k: int = 6,
    vector_weight: float = AGENT_MEMORY_HYBRID_VECTOR_WEIGHT,
    lexical_weight: float = AGENT_MEMORY_HYBRID_LEXICAL_WEIGHT,
) -> list[dict[str, Any]]:
    """Hybrid retrieval over agent_memories scoped to one user_id.

    Args:
        collection: agent_memories AsyncIOMotorCollection.
        user_id: Owning user; every query MUST pre-filter on this. Required.
        query_text: Raw user query for the lexical leg.
        query_embedding: Embedded query for the vector leg.
        namespace: Optional `MemoryNamespace` restriction (e.g., only
            semantic memories). When None, all three namespaces are eligible.
        top_k: Final number of fused results to return.
        vector_weight: RRF weight of the vector leg.
        lexical_weight: RRF weight of the lexical leg.

    Returns:
        Memory documents (embeddings stripped) with `MEMORY_SCORE_FIELD`
        carrying the [0, 1]-normalized fused score.
    """
    if not user_id:
        raise ValueError(
            "hybrid_search_memories called without user_id; cross-tenant "
            "retrieval is forbidden — every query must pre-filter on user_id."
        )

    namespace_str = str(namespace) if namespace is not None else None

    vector_filter: dict[str, Any] = {Keys.USER_ID: user_id}
    if namespace_str is not None:
        vector_filter[Keys.NAMESPACE] = namespace_str

    query_vector_bin = Binary.from_vector(
        list(query_embedding),
        dtype=BinaryVectorDtype.FLOAT32,
    )

    num_candidates_multiplier = get_settings().agent.memory_search_num_candidates_multiplier
    num_candidates = min(top_k * num_candidates_multiplier, _MAX_NUM_CANDIDATES)
    vector_stage: dict[str, Any] = {
        "$vectorSearch": {
            "index": AGENT_MEMORY_VECTOR_INDEX_NAME,
            "path": Keys.EMBEDDING,
            "queryVector": query_vector_bin,
            "numCandidates": num_candidates,
            "limit": top_k * 4,
            "filter": vector_filter,
        }
    }

    # Lexical leg: $search.compound with the user_id (and optional namespace)
    # pushed into `filter` so mongot prunes non-matching docs before Lucene
    # scoring runs. Mirrors the RAG hybrid retriever pattern.
    lexical_must: dict[str, Any] = {
        "text": {"query": query_text or " ", "path": Keys.CONTENT},
    }
    lexical_filters: list[dict[str, Any]] = [
        {"equals": {"path": Keys.USER_ID, "value": user_id}},
    ]
    if namespace_str is not None:
        lexical_filters.append({"equals": {"path": Keys.NAMESPACE, "value": namespace_str}})

    lexical_pipeline: list[dict[str, Any]] = [
        {
            "$search": {
                "index": AGENT_MEMORY_LEXICAL_INDEX_NAME,
                "compound": {"must": [lexical_must], "filter": lexical_filters},
            }
        },
        {"$limit": top_k * 4},
    ]

    pipeline = build_rankfusion_pipeline(
        vector_stage=vector_stage,
        lexical_pipeline=lexical_pipeline,
        vector_weight=vector_weight,
        lexical_weight=lexical_weight,
        top_k=top_k,
    )
    # Strip the embedding from the output so the retriever doesn't ship
    # vectors back into Python state on every turn.
    pipeline.append({"$project": {Keys.EMBEDDING: 0}})

    try:
        results = await collection.aggregate(pipeline).to_list(length=None)
        normalize_rrf_scores(results, score_field=MEMORY_SCORE_FIELD)
        logger.info(
            "agent_memories $rankFusion: user_id=%s namespace=%s top_k=%d returned=%d",
            user_id,
            namespace_str or "*",
            top_k,
            len(results),
        )
        return results
    except Exception as e:
        logger.error(f"agent_memories $rankFusion failed for user_id={user_id}: {e}")
        raise
