"""Shared `$rankFusion` aggregation builder (MongoDB 8.1+).

`$rankFusion` is MongoDB's native Reciprocal Rank Fusion stage: it accepts
multiple ranked-result subpipelines and emits one fused, ranked stream in a
single round-trip. The RAG hybrid retriever and the agent memory retriever
both want the same fusion shape (one vector leg, one lexical leg, RRF
weights), differing only in:

  - Which collection / which indexes they target
  - What pre-filter is legal for each leg
  - Whether the raw RRF score gets min-max normalized into a downstream-
    visible `search_score` field

This module exposes one function — `build_rankfusion_pipeline` — that
captures the shared *fusion* mechanics, and one helper —
`normalize_rrf_scores` — that captures the shared min-max normalization.
The legs themselves are still authored by each caller, because their pre-
filter clauses are not interchangeable between collections.

About the RRF score scale:
    `$rankFusion` emits fused scores in roughly `[0, sum_of_weights / 60]`
    (RRF uses k=60 by default). Those scores are NOT comparable to cosine
    similarity, so consumers that later reuse `search_score` for MMR or
    score-threshold gating SHOULD min-max normalize per page via
    `normalize_rrf_scores(...)`.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Field where `$rankFusion`'s raw fused score lands after the $addFields step.
# Kept separate from any downstream `search_score` field so callers can choose
# to normalize without losing the original number.
RRF_RAW_SCORE_FIELD = "rrf_score"


def build_rankfusion_pipeline(
    vector_stage: dict[str, Any],
    lexical_pipeline: list[dict[str, Any]],
    *,
    vector_weight: float,
    lexical_weight: float,
    top_k: int,
    score_details: bool = False,
    drop_id: bool = True,
    vector_extra_stages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a `$rankFusion` aggregation pipeline.

    Args:
        vector_stage: The single `$vectorSearch` stage that drives the vector
            leg. The caller owns its `index`, `path`, `queryVector`, `filter`,
            `limit`, and `numCandidates`.
        lexical_pipeline: One or more stages making up the lexical leg —
            typically a `$search` stage plus a downstream `$limit`. The caller
            owns the search index name and the compound clauses (notably the
            per-collection `filter` array that lets mongot prune before
            Lucene scoring).
        vector_weight: RRF weight for the vector leg.
        lexical_weight: RRF weight for the lexical leg.
        top_k: How many fused documents to emit. Applied AFTER fusion.
        score_details: When True, ask `$rankFusion` to emit per-leg score
            details on every result. Useful for debugging fusion ratios.
        drop_id: When True, the trailing `$project` strips `_id`. Set to
            False if the caller needs the document `_id` to survive (e.g.,
            for downstream `update_one` / `delete_one` on the same doc).
        vector_extra_stages: Optional stages appended to the vector leg right
            after `$vectorSearch` — e.g. an `$addFields` that captures
            `$meta:"vectorSearchScore"` so the cosine survives fusion (used by
            the RAG relevance floor). `$meta` for the vector score is only valid
            immediately after `$vectorSearch`, hence it must live in the leg.

    Returns:
        A list of aggregation stages: [$rankFusion, $addFields, $limit, $project].
    """
    vector_pipeline: list[dict[str, Any]] = [vector_stage]
    if vector_extra_stages:
        vector_pipeline.extend(vector_extra_stages)

    rank_fusion_stage: dict[str, Any] = {
        "$rankFusion": {
            "input": {
                "pipelines": {
                    "vector": vector_pipeline,
                    "lexical": list(lexical_pipeline),
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
    if score_details:
        rank_fusion_stage["$rankFusion"]["scoreDetails"] = True

    pipeline: list[dict[str, Any]] = [
        rank_fusion_stage,
        {"$addFields": {RRF_RAW_SCORE_FIELD: {"$meta": "score"}}},
        {"$limit": top_k},
    ]
    if drop_id:
        pipeline.append({"$project": {"_id": 0}})
    return pipeline


def normalize_rrf_scores(
    results: list[dict[str, Any]],
    *,
    score_field: str,
    raw_score_field: str = RRF_RAW_SCORE_FIELD,
) -> None:
    """Min-max normalize raw RRF scores into [0, 1] under `score_field`.

    Mutates `results` in place. Leaves `raw_score_field` untouched for
    debugging.

    Edge cases:
      - Empty page: no-op.
      - Single result, or all-equal raw scores: write 1.0 across the page
        so downstream MMR-style fusion doesn't collapse the relevance term
        to zero.
    """
    if not results:
        return

    raw = [r.get(raw_score_field, 0.0) for r in results]
    lo = min(raw)
    hi = max(raw)
    span = hi - lo

    for chunk, score in zip(results, raw):
        if span > 0:
            chunk[score_field] = (score - lo) / span
        else:
            chunk[score_field] = 1.0
