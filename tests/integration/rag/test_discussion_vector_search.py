"""Integration test: server-side $vectorSearch for discussion similarity.

Validates the P2 fix that replaced the O(N) client-side cosine loop in
anti_repetition_hybrid with a server-side $vectorSearch over the
discussion_embeddings index (created programmatically by ensure_indexes).

Property under test (parity, not exact-float): given a query embedding equal to
one stored discussion's embedding, find_similar_discussions returns that
discussion as the top hit, restricted to the requested run_ids, with embeddings
projected out of the result.

Requires Docker with MongoDB + the mongot sidecar (vector search). Skipped when
either is unavailable: the test waits for the index to become queryable and
skips if it never does.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# src/ holds the real packages; ensure it precedes the test dir on sys.path so
# `db`/`constants` resolve to production modules (see sibling test for rationale).
_src = str(Path(__file__).resolve().parents[3] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from constants import COLLECTION_DISCUSSIONS, DISCUSSION_VECTOR_INDEX_NAME  # noqa: E402
from custom_types.field_keys import DbFieldKeys  # noqa: E402
from tests._helpers.mongo import requires_mongodb  # noqa: E402


def _unit_vec(dims: int, hot_index: int) -> list[float]:
    """A simple near-one-hot unit vector, distinct per hot_index."""
    v = [0.01] * dims
    v[hot_index % dims] = 1.0
    return v


def _vec_at_cosine(dims: int, cosine: float) -> list[float]:
    """Build a unit vector whose cosine with the canonical base e0 is `cosine`.

    base = e0 (the first standard basis vector). We set v = cosine on axis 0 and
    spread sqrt(1 - cosine^2) onto axis 1 so |v| == 1, giving exactly
    dot(base, v) == cosine. Lets a test straddle a known cosine threshold.
    """
    import math

    v = [0.0] * dims
    v[0] = cosine
    v[1] = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return v


def _base_vec(dims: int) -> list[float]:
    """The canonical base (e0) used by _vec_at_cosine."""
    v = [0.0] * dims
    v[0] = 1.0
    return v


def _to_binData(vec: list[float]):
    """Encode as BSON Binary FLOAT32 — the representation production stores."""
    from bson.binary import Binary, BinaryVectorDtype

    return Binary.from_vector(vec, dtype=BinaryVectorDtype.FLOAT32)


async def _fresh_db():
    """Reset the memoized Motor client and return a handle bound to the current
    event loop. pytest-asyncio gives each test its own loop; the cached client
    from a prior test would otherwise raise "Event loop is closed".
    """
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    return await conn_mod.get_database()


async def _index_queryable(collection) -> bool:
    from db.indexes import _wait_for_search_index_ready

    return await _wait_for_search_index_ready(collection, DISCUSSION_VECTOR_INDEX_NAME)


@requires_mongodb
async def test_find_similar_discussions_top_hit_and_scoping():
    from db.indexes import ensure_indexes
    from db.repositories.discussions import DiscussionsRepository

    db = await _fresh_db()
    await ensure_indexes(db)
    collection = db[COLLECTION_DISCUSSIONS]
    if not await _index_queryable(collection):
        pytest.skip("discussion_embeddings index not queryable (mongot unavailable)")

    dims = 1536
    run_id = f"vs-test-{uuid.uuid4().hex[:8]}"
    other_run_id = f"vs-other-{uuid.uuid4().hex[:8]}"
    target_id = f"d-target-{uuid.uuid4().hex[:8]}"
    distractor_id = f"d-distract-{uuid.uuid4().hex[:8]}"
    other_id = f"d-other-{uuid.uuid4().hex[:8]}"

    target_vec = _unit_vec(dims, 0)
    # Store as BinData FLOAT32 — the representation production now writes.
    docs = [
        {DbFieldKeys.DISCUSSION_ID: target_id, DbFieldKeys.RUN_ID: run_id, DbFieldKeys.CHAT_NAME: "c", DbFieldKeys.TITLE: "target", DbFieldKeys.NUTSHELL: "n", DbFieldKeys.EMBEDDING: _to_binData(target_vec)},
        {DbFieldKeys.DISCUSSION_ID: distractor_id, DbFieldKeys.RUN_ID: run_id, DbFieldKeys.CHAT_NAME: "c", DbFieldKeys.TITLE: "distractor", DbFieldKeys.NUTSHELL: "n", DbFieldKeys.EMBEDDING: _to_binData(_unit_vec(dims, 500))},
        {DbFieldKeys.DISCUSSION_ID: other_id, DbFieldKeys.RUN_ID: other_run_id, DbFieldKeys.CHAT_NAME: "c", DbFieldKeys.TITLE: "other-run", DbFieldKeys.NUTSHELL: "n", DbFieldKeys.EMBEDDING: _to_binData(target_vec)},
    ]
    await collection.insert_many(docs)

    try:
        repo = DiscussionsRepository(db)

        # mongot indexes newly-inserted docs asynchronously; retry briefly.
        import asyncio

        results = []
        for _ in range(20):
            results = await repo.find_similar_discussions(query_embedding=target_vec, run_ids=[run_id], top_k=5, min_score=0.0)
            if results:
                break
            await asyncio.sleep(0.5)

        if not results:
            pytest.skip("mongot did not index the test docs in time")

        # Top hit is the exact-match target.
        assert results[0][DbFieldKeys.DISCUSSION_ID] == target_id
        # Scoped to run_id: the identical-embedding doc in other_run_id is excluded.
        returned_ids = {r[DbFieldKeys.DISCUSSION_ID] for r in results}
        assert other_id not in returned_ids
        # Embeddings are projected out of every result.
        assert all(DbFieldKeys.EMBEDDING not in r for r in results)
        # Similarity score is present and descending.
        sims = [r["similarity"] for r in results]
        assert sims == sorted(sims, reverse=True)
    finally:
        await collection.delete_many({DbFieldKeys.DISCUSSION_ID: {"$in": [target_id, distractor_id, other_id]}})


@requires_mongodb
async def test_raw_cosine_threshold_semantics():
    """min_score is a RAW-COSINE floor, not the normalized Atlas score (B1).

    Stores two vectors at known raw cosines straddling 0.80 (0.85 and 0.70) and
    queries with min_score=0.80. Only the 0.85 vector must survive. If the floor
    were (incorrectly) applied directly to the normalized vectorSearchScore, the
    effective cut would be ~0.60 raw cosine and the 0.70 vector would leak
    through — this test guards exactly that regression. It also asserts the
    returned `similarity` is reported in raw cosine (~0.85), not ~0.925.
    """
    from db.indexes import ensure_indexes
    from db.repositories.discussions import DiscussionsRepository

    db = await _fresh_db()
    await ensure_indexes(db)
    collection = db[COLLECTION_DISCUSSIONS]
    if not await _index_queryable(collection):
        pytest.skip("discussion_embeddings index not queryable (mongot unavailable)")

    dims = 1536
    run_id = f"vs-thresh-{uuid.uuid4().hex[:8]}"
    above_id = f"d-above-{uuid.uuid4().hex[:8]}"  # cosine 0.85, must survive 0.80
    below_id = f"d-below-{uuid.uuid4().hex[:8]}"  # cosine 0.70, must be cut at 0.80

    query_vec = _base_vec(dims)
    docs = [
        {DbFieldKeys.DISCUSSION_ID: above_id, DbFieldKeys.RUN_ID: run_id, DbFieldKeys.CHAT_NAME: "c", DbFieldKeys.TITLE: "above", DbFieldKeys.NUTSHELL: "n", DbFieldKeys.EMBEDDING: _to_binData(_vec_at_cosine(dims, 0.85))},
        {DbFieldKeys.DISCUSSION_ID: below_id, DbFieldKeys.RUN_ID: run_id, DbFieldKeys.CHAT_NAME: "c", DbFieldKeys.TITLE: "below", DbFieldKeys.NUTSHELL: "n", DbFieldKeys.EMBEDDING: _to_binData(_vec_at_cosine(dims, 0.70))},
    ]
    await collection.insert_many(docs)

    try:
        import asyncio

        repo = DiscussionsRepository(db)
        results = []
        for _ in range(20):
            results = await repo.find_similar_discussions(query_embedding=query_vec, run_ids=[run_id], top_k=5, min_score=0.80)
            if results:
                break
            await asyncio.sleep(0.5)

        if not results:
            pytest.skip("mongot did not index the test docs in time")

        returned_ids = {r[DbFieldKeys.DISCUSSION_ID] for r in results}
        # The 0.85 vector survives the 0.80 raw-cosine floor.
        assert above_id in returned_ids
        # The 0.70 vector is cut — would only survive if the floor were applied
        # to the normalized score (effective ~0.60 raw cosine).
        assert below_id not in returned_ids
        # Returned similarity is raw cosine (~0.85), not normalized (~0.925).
        above = next(r for r in results if r[DbFieldKeys.DISCUSSION_ID] == above_id)
        assert above["similarity"] == pytest.approx(0.85, abs=0.02)
    finally:
        await collection.delete_many({DbFieldKeys.DISCUSSION_ID: {"$in": [above_id, below_id]}})
