"""Parity test: the shared `build_rankfusion_pipeline` helper produces a
structurally identical aggregation to the hand-rolled fusion construction
that previously lived inside `hybrid_search_chunks`.

This is a snapshot test — no MongoDB needed. The RAG eval gate
(`scripts/run_rag_evals.py`) provides the runtime parity check.
"""

from __future__ import annotations

from typing import Any

from db.queries.rankfusion import RRF_RAW_SCORE_FIELD, build_rankfusion_pipeline


def _hand_rolled_pipeline(
    vector_stage: dict[str, Any],
    lexical_pipeline: list[dict[str, Any]],
    *,
    vector_weight: float,
    lexical_weight: float,
    top_k: int,
    debug_score_details: bool,
) -> list[dict[str, Any]]:
    """Replicates the pre-refactor inline pipeline assembly from
    `src/rag/retrieval/hybrid_search.py` so we can diff it against the
    output of `build_rankfusion_pipeline`. If this snapshot drifts in a
    future refactor, the parity test fails loudly.
    """
    rank_fusion_stage: dict[str, Any] = {
        "$rankFusion": {
            "input": {
                "pipelines": {
                    "vector": [vector_stage],
                    "lexical": lexical_pipeline,
                }
            },
            "combination": {
                "weights": {
                    "vector": vector_weight,
                    "lexical": lexical_weight,
                }
            },
        }
    }
    if debug_score_details:
        rank_fusion_stage["$rankFusion"]["scoreDetails"] = True
    return [
        rank_fusion_stage,
        {"$addFields": {RRF_RAW_SCORE_FIELD: {"$meta": "score"}}},
        {"$limit": top_k},
        {"$project": {"_id": 0}},
    ]


VEC = {
    "$vectorSearch": {
        "index": "rag_chunk_embeddings_v2",
        "path": "embedding",
        "queryVector": [0.1, 0.2, 0.3, 0.4],
        "numCandidates": 400,
        "limit": 80,
    }
}

LEX = [
    {
        "$search": {
            "index": "rag_chunks_lexical",
            "compound": {
                "must": [{"text": {"query": "foo", "path": "content"}}],
                "filter": [{"in": {"path": "content_source", "value": ["podcast"]}}],
            },
        }
    },
    {"$limit": 80},
]


def test_helper_matches_pre_refactor_pipeline_default():
    built = build_rankfusion_pipeline(
        vector_stage=VEC,
        lexical_pipeline=LEX,
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=20,
    )
    reference = _hand_rolled_pipeline(
        VEC,
        LEX,
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=20,
        debug_score_details=False,
    )
    assert built == reference


def test_helper_matches_pre_refactor_pipeline_with_score_details():
    built = build_rankfusion_pipeline(
        vector_stage=VEC,
        lexical_pipeline=LEX,
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=20,
        score_details=True,
    )
    reference = _hand_rolled_pipeline(
        VEC,
        LEX,
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=20,
        debug_score_details=True,
    )
    assert built == reference
