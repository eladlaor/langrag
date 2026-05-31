"""Unit tests for the shared `$rankFusion` aggregation builder.

These tests are pure builders / pure functions — no MongoDB required, so they
don't need the `requires_mongodb` skip marker.
"""

from __future__ import annotations

import pytest

from db.queries.rankfusion import (
    RRF_RAW_SCORE_FIELD,
    build_rankfusion_pipeline,
    normalize_rrf_scores,
)


def _vector_stage() -> dict:
    return {
        "$vectorSearch": {
            "index": "test_vec_index",
            "path": "embedding",
            "queryVector": [0.0] * 4,
            "numCandidates": 100,
            "limit": 20,
        }
    }


def _lexical_pipeline() -> list[dict]:
    return [
        {
            "$search": {
                "index": "test_lex_index",
                "text": {"query": "foo", "path": "content"},
            }
        },
        {"$limit": 20},
    ]


# ---------------------------------------------------------------------------
# Pipeline shape
# ---------------------------------------------------------------------------


def test_pipeline_shape_default():
    pipeline = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=10,
    )
    assert [list(s.keys())[0] for s in pipeline] == [
        "$rankFusion",
        "$addFields",
        "$limit",
        "$project",
    ]


def test_pipeline_carries_weights_and_pipelines():
    pipeline = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.8,
        lexical_weight=0.2,
        top_k=5,
    )
    rf = pipeline[0]["$rankFusion"]
    assert rf["combination"]["weights"] == {"vector": 0.8, "lexical": 0.2}
    assert list(rf["input"]["pipelines"].keys()) == ["vector", "lexical"]
    # Vector pipeline carries the user-supplied $vectorSearch stage verbatim
    assert rf["input"]["pipelines"]["vector"][0] == _vector_stage()
    # Lexical pipeline is copied; mutating the original after building must not
    # leak into the built pipeline.
    lex = _lexical_pipeline()
    p2 = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=lex,
        vector_weight=0.5,
        lexical_weight=0.5,
        top_k=3,
    )
    lex.append({"$count": "x"})
    assert {"$count": "x"} not in p2[0]["$rankFusion"]["input"]["pipelines"]["lexical"]


def test_pipeline_top_k_applied_after_fusion():
    pipeline = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=7,
    )
    limits = [s for s in pipeline if "$limit" in s]
    assert limits[0]["$limit"] == 7


def test_pipeline_raw_score_field_added():
    pipeline = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=5,
    )
    add_fields = pipeline[1]["$addFields"]
    assert RRF_RAW_SCORE_FIELD in add_fields
    assert add_fields[RRF_RAW_SCORE_FIELD] == {"$meta": "score"}


def test_pipeline_score_details_optional():
    no_details = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=5,
    )
    assert "scoreDetails" not in no_details[0]["$rankFusion"]

    with_details = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=5,
        score_details=True,
    )
    assert with_details[0]["$rankFusion"]["scoreDetails"] is True


def test_pipeline_keep_id_when_drop_id_false():
    pipeline = build_rankfusion_pipeline(
        vector_stage=_vector_stage(),
        lexical_pipeline=_lexical_pipeline(),
        vector_weight=0.7,
        lexical_weight=0.3,
        top_k=5,
        drop_id=False,
    )
    # Last stage is $limit when drop_id=False; no trailing $project
    assert "$project" not in [list(s.keys())[0] for s in pipeline]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_empty_is_no_op():
    results: list[dict] = []
    normalize_rrf_scores(results, score_field="s")
    assert results == []


def test_normalize_single_writes_one():
    results = [{RRF_RAW_SCORE_FIELD: 0.02}]
    normalize_rrf_scores(results, score_field="s")
    assert results[0]["s"] == 1.0
    # raw preserved
    assert results[0][RRF_RAW_SCORE_FIELD] == 0.02


def test_normalize_all_equal_writes_one():
    results = [
        {RRF_RAW_SCORE_FIELD: 0.02},
        {RRF_RAW_SCORE_FIELD: 0.02},
        {RRF_RAW_SCORE_FIELD: 0.02},
    ]
    normalize_rrf_scores(results, score_field="s")
    assert [r["s"] for r in results] == [1.0, 1.0, 1.0]


def test_normalize_min_max():
    results = [
        {RRF_RAW_SCORE_FIELD: 0.03},
        {RRF_RAW_SCORE_FIELD: 0.01},
        {RRF_RAW_SCORE_FIELD: 0.02},
    ]
    normalize_rrf_scores(results, score_field="s")
    scores = [r["s"] for r in results]
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)
    assert scores[2] == pytest.approx(0.5)


def test_normalize_uses_custom_raw_field():
    results = [
        {"custom_raw": 1.0},
        {"custom_raw": 0.0},
    ]
    normalize_rrf_scores(results, score_field="s", raw_score_field="custom_raw")
    assert [r["s"] for r in results] == [1.0, 0.0]


def test_normalize_missing_raw_treated_as_zero():
    """If a result lacks the raw-score field, it's treated as 0.0 so the
    normalization still produces a stable [0, 1] range."""
    results = [
        {RRF_RAW_SCORE_FIELD: 0.5},
        {},
    ]
    normalize_rrf_scores(results, score_field="s")
    assert results[0]["s"] == pytest.approx(1.0)
    assert results[1]["s"] == pytest.approx(0.0)
