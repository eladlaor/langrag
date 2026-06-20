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


def test_capture_vector_score_keeps_legs_selection_only_and_extracts_post_fusion():
    """When capturing the vector-leg score for a relevance floor, the vector
    input pipeline MUST stay selection-only (no in-leg $addFields -> server
    error 9191103). The score is instead pulled from scoreDetails by a
    post-$rankFusion $addFields, and scoreDetails is forced on."""
    built = build_rankfusion_pipeline(
        vector_stage=VEC,
        lexical_pipeline=LEX,
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=20,
        capture_vector_score_field="_vc",
    )

    rank_fusion = built[0]["$rankFusion"]
    # scoreDetails is required to recover the per-leg score.
    assert rank_fusion["scoreDetails"] is True
    # The vector leg is JUST $vectorSearch — selection-only.
    vector_leg = rank_fusion["input"]["pipelines"]["vector"]
    assert vector_leg == [VEC]
    assert not any("$addFields" in s or "$set" in s for s in vector_leg)

    # Exactly one post-fusion $addFields captures the cosine, reading scoreDetails.
    capture = [s["$addFields"] for s in built if "$addFields" in s and "_vc" in s["$addFields"]]
    assert len(capture) == 1
    assert "scoreDetails" in str(capture[0]["_vc"])

    # Trailing shape still ends with limit + project.
    assert "$limit" in built[-2]
    assert built[-1] == {"$project": {"_id": 0}}
