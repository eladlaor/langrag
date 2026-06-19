"""Integration test: hot queries are served by an index, not a collection scan.

This is the committed explain-plan evidence the MongoDB audit asked for. Every
index in `src/db/indexes.py` is justified by reasoning; this test VERIFIES that
the reasoning holds at runtime by running each hot query through
`.explain("executionStats")` and asserting:

  * the winning plan uses an index (IXSCAN / index-backed stages), never a
    full COLLSCAN, and
  * the examined/returned ratio is sane (no examined-blowup that would mean the
    index is the wrong shape).

It is Docker-gated like the other integration suites (auto-skips when MongoDB is
absent) and read-only against a small fixture it seeds and tears down itself.

The vector/hybrid ($vectorSearch / $rankFusion) paths run on mongot, whose
explain shape differs from btree and is not always available locally; those are
covered with a lighter, mongot-tolerant assertion that skips when mongot is
absent.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from constants import (
    COLLECTION_DISCUSSIONS,
    COLLECTION_MESSAGES,
    COLLECTION_POLLS,
    COLLECTION_RAG_CHUNKS,
    RAG_VECTOR_INDEX_NAME,
)
from custom_types.field_keys import DbFieldKeys, PollDbKeys
from db.indexes import ensure_indexes
from db.repositories.discussions import DiscussionsRepository
from db.repositories.messages import MessagesRepository
from db.repositories.polls import PollsRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


# Seeded enough rows that a COLLSCAN would examine many more docs than a query
# returns — small enough to stay fast, large enough that the examined/returned
# ratio is meaningful.
_SEED_MESSAGES = 50
_SEED_DISCUSSIONS = 10
_SEED_POLLS = 8

# Run IDs seeded by this module, cleaned up after the session so the shared
# collections are left as we found them.
_SEEDED_RUN_IDS: list[str] = []


@pytest_asyncio.fixture
async def db():
    """Motor database handle with per-test singleton reset (mirrors unit/db conftest)."""
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    database = await conn_mod.get_database()
    try:
        await ensure_indexes(database)
        yield database
    finally:
        await conn_mod.close_connection()


@pytest_asyncio.fixture
async def seeded_run(db):
    """Seed one run's worth of messages, discussions, and polls; clean up after.

    Seeds THROUGH the repositories so the documents carry schema_version and
    pass the $jsonSchema validators (the same write path production uses).
    Discussion embeddings are skipped (generate_embeddings=False) so the fixture
    makes no OpenAI calls.
    """
    run_id = f"plan-test-{uuid.uuid4().hex[:8]}"
    chat_name = "Plan Test Chat"
    _SEEDED_RUN_IDS.append(run_id)

    messages_repo = MessagesRepository(db)
    discussions_repo = DiscussionsRepository(db)
    polls_repo = PollsRepository(db)

    await messages_repo.insert_batch(
        [
            {
                DbFieldKeys.MESSAGE_ID: f"{run_id}_msg_{i}",
                DbFieldKeys.RUN_ID: run_id,
                DbFieldKeys.CHAT_NAME: chat_name,
                DbFieldKeys.SENDER: f"sender-{i % 3}",
                DbFieldKeys.TIMESTAMP: 1_700_000_000_000 + i,
                DbFieldKeys.CONTENT: f"message {i}",
            }
            for i in range(_SEED_MESSAGES)
        ]
    )

    await discussions_repo.create_discussions_bulk(
        [
            {
                DbFieldKeys.DISCUSSION_ID: f"{run_id}_disc_{i}",
                DbFieldKeys.RUN_ID: run_id,
                DbFieldKeys.CHAT_NAME: chat_name,
                DbFieldKeys.TITLE: f"disc {i}",
                DbFieldKeys.NUTSHELL: f"nutshell {i}",
                DbFieldKeys.MESSAGE_IDS: [f"{run_id}_msg_{i}"],
                DbFieldKeys.RANKING_SCORE: float(i),
            }
            for i in range(_SEED_DISCUSSIONS)
        ],
        generate_embeddings=False,
    )

    await polls_repo.create_polls_bulk(
        [
            {
                PollDbKeys.POLL_ID: f"{run_id}_poll_{i}",
                PollDbKeys.RUN_ID: run_id,
                PollDbKeys.CHAT_NAME: chat_name,
                PollDbKeys.TIMESTAMP: 1_700_000_000_000 + i,
                PollDbKeys.QUESTION: f"q {i}",
            }
            for i in range(_SEED_POLLS)
        ]
    )

    yield {"run_id": run_id, "chat_name": chat_name}

    await db[COLLECTION_MESSAGES].delete_many({DbFieldKeys.RUN_ID: run_id})
    await db[COLLECTION_DISCUSSIONS].delete_many({DbFieldKeys.RUN_ID: run_id})
    await db[COLLECTION_POLLS].delete_many({PollDbKeys.RUN_ID: run_id})
    if run_id in _SEEDED_RUN_IDS:
        _SEEDED_RUN_IDS.remove(run_id)


def _winning_stage_names(explain: dict) -> set[str]:
    """Collect every stage name in the winning plan tree."""
    names: set[str] = set()
    query_planner = explain.get("queryPlanner", {})
    root = query_planner.get("winningPlan", {})

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        stage = node.get("stage")
        if stage:
            names.add(stage)
        # Compound/optimized plans nest the real stages under these keys.
        for key in ("inputStage", "innerStage", "outerStage", "thenStage", "elseStage"):
            if key in node:
                walk(node[key])
        for child in node.get("inputStages", []) or []:
            walk(child)
        # Newer servers wrap the classic plan under queryPlan.
        if "queryPlan" in node:
            walk(node["queryPlan"])

    walk(root)
    return names


def _assert_index_backed(explain: dict, label: str) -> None:
    """Assert the winning plan is index-backed (has IXSCAN) and never a COLLSCAN."""
    stages = _winning_stage_names(explain)
    assert "COLLSCAN" not in stages, f"{label}: winning plan does a COLLSCAN (stages={stages})"
    assert "IXSCAN" in stages, f"{label}: winning plan is not index-backed (stages={stages})"

    stats = explain.get("executionStats", {})
    examined = stats.get("totalDocsExamined", 0)
    returned = stats.get("nReturned", 0)
    if returned:
        ratio = examined / returned
        # An index-backed query should examine on the order of what it returns.
        # Allow generous slack for fetch overhead while still catching a scan.
        assert ratio <= 5, f"{label}: examined/returned ratio {ratio:.1f} too high (examined={examined}, returned={returned})"


async def test_get_messages_by_run_uses_index(db, seeded_run):
    """messages by {run_id, chat_name} sorted by timestamp -> the ESR compound."""
    run_id, chat_name = seeded_run["run_id"], seeded_run["chat_name"]
    cursor = db[COLLECTION_MESSAGES].find({DbFieldKeys.RUN_ID: run_id, DbFieldKeys.CHAT_NAME: chat_name}).sort([(DbFieldKeys.TIMESTAMP, 1)])
    explain = await cursor.explain()
    _assert_index_backed(explain, "get_messages_by_run")


async def test_get_messages_page_keyset_uses_index(db, seeded_run):
    """Keyset page query ($or cursor predicate + (timestamp, message_id) sort)."""
    run_id, chat_name = seeded_run["run_id"], seeded_run["chat_name"]
    last_ts = 1_700_000_000_000 + 10
    last_id = f"{run_id}_msg_10"
    cursor = (
        db[COLLECTION_MESSAGES]
        .find(
            {
                DbFieldKeys.RUN_ID: run_id,
                DbFieldKeys.CHAT_NAME: chat_name,
                "$or": [
                    {DbFieldKeys.TIMESTAMP: {"$gt": last_ts}},
                    {DbFieldKeys.TIMESTAMP: last_ts, DbFieldKeys.MESSAGE_ID: {"$gt": last_id}},
                ],
            }
        )
        .sort([(DbFieldKeys.TIMESTAMP, 1), (DbFieldKeys.MESSAGE_ID, 1)])
    )
    explain = await cursor.explain()
    _assert_index_backed(explain, "get_messages_page")


async def test_get_discussions_by_run_uses_index(db, seeded_run):
    """discussions by run sorted by ranking_score -> {run_id, ranking_score} compound."""
    run_id = seeded_run["run_id"]
    cursor = db[COLLECTION_DISCUSSIONS].find({DbFieldKeys.RUN_ID: run_id}).sort([(DbFieldKeys.RANKING_SCORE, -1)])
    explain = await cursor.explain()
    _assert_index_backed(explain, "get_discussions_by_run")


async def test_get_polls_by_run_uses_index(db, seeded_run):
    """polls by run sorted by timestamp -> {run_id} / {run_id, chat_name} index."""
    run_id = seeded_run["run_id"]
    cursor = db[COLLECTION_POLLS].find({PollDbKeys.RUN_ID: run_id}).sort([(PollDbKeys.TIMESTAMP, -1)])
    explain = await cursor.explain()
    _assert_index_backed(explain, "get_polls_by_run")


async def test_rag_vector_index_is_queryable(db):
    """The rag_chunks $vectorSearch index exists and is queryable on mongot.

    The vector/hybrid explain shape on mongot is unstable across versions, so we
    do not assert a plan tree here (the btree tests above carry the IXSCAN
    evidence). Instead we confirm the vector index the hot path depends on is
    registered and queryable, which is the runtime precondition for
    $vectorSearch to use an index rather than degrade. Skips when mongot is
    absent (stock local Mongo).
    """
    coll = db[COLLECTION_RAG_CHUNKS]
    try:
        indexes = [idx async for idx in coll.list_search_indexes()]
    except Exception:
        pytest.skip("mongot not available — vector search index can't be inspected")

    match = next((idx for idx in indexes if idx.get("name") == RAG_VECTOR_INDEX_NAME), None)
    if match is None:
        pytest.skip(f"{RAG_VECTOR_INDEX_NAME} not built on this instance")
    # queryable is the field the readiness poller in indexes.py trusts over status.
    assert match.get("queryable") is True, f"{RAG_VECTOR_INDEX_NAME} exists but is not queryable: {match}"
