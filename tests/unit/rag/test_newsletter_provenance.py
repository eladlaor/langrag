"""
Unit tests for newsletter -> message provenance resolution (D10 ingest side).

Verifies the shared helper that both ingest and the backfill use: given a stored
newsletter document, it resolves featured/brief discussion ids -> discussions ->
flattened, deduped message ids, scoped by run_id. No live MongoDB.
"""

import pytest

from custom_types.field_keys import DbFieldKeys
from rag.sources import provenance


class _FakeDiscussionsRepo:
    """Stand-in for DiscussionsRepository capturing the find_many query."""

    _EXCLUDE_EMBEDDING_PROJECTION = {DbFieldKeys.EMBEDDING: 0}
    last_query = None

    def __init__(self, _db):
        pass

    async def find_many(self, query, projection=None):
        type(self).last_query = query
        # Two discussions, overlapping message id "m2" to prove dedup.
        return [
            {DbFieldKeys.DISCUSSION_ID: "d1", DbFieldKeys.MESSAGE_IDS: ["m1", "m2"]},
            {DbFieldKeys.DISCUSSION_ID: "d2", DbFieldKeys.MESSAGE_IDS: ["m2", "m3"]},
        ]


@pytest.mark.asyncio
async def test_resolve_provenance_flattens_dedups_and_scopes(monkeypatch):
    monkeypatch.setattr(provenance, "DiscussionsRepository", _FakeDiscussionsRepo)

    newsletter = {
        DbFieldKeys.NEWSLETTER_ID: "nl1",
        DbFieldKeys.RUN_ID: "run42",
        DbFieldKeys.FEATURED_DISCUSSION_IDS: ["d1", "d2"],
        DbFieldKeys.BRIEF_MENTION_DISCUSSION_IDS: ["d2"],  # dup, should collapse
    }

    discussion_ids, message_ids = await provenance.resolve_newsletter_message_provenance(
        db=object(), newsletter=newsletter
    )

    assert discussion_ids == ["d1", "d2"]  # featured+brief, deduped, ordered
    assert message_ids == ["m1", "m2", "m3"]  # flattened + deduped, order-preserving
    # Scoped by run_id to avoid cross-run discussion-id collisions.
    assert _FakeDiscussionsRepo.last_query[DbFieldKeys.RUN_ID] == "run42"
    assert _FakeDiscussionsRepo.last_query[DbFieldKeys.DISCUSSION_ID] == {"$in": ["d1", "d2"]}


@pytest.mark.asyncio
async def test_resolve_provenance_failsoft_on_legacy_newsletter(monkeypatch):
    monkeypatch.setattr(provenance, "DiscussionsRepository", _FakeDiscussionsRepo)

    # Legacy newsletter with no discussion references -> empty, no raise.
    newsletter = {DbFieldKeys.NEWSLETTER_ID: "old", DbFieldKeys.RUN_ID: "r"}
    discussion_ids, message_ids = await provenance.resolve_newsletter_message_provenance(
        db=object(), newsletter=newsletter
    )
    assert discussion_ids == []
    assert message_ids == []
