"""PodcastsRepository tests: idempotent seed + active listing.

Requires MongoDB (auto-skips otherwise). Verifies the catalog seed is
idempotent (no duplicate rows, created_at preserved) and list_active returns the
seeded row.
"""

import pytest

from constants import PODCAST_SLUG_LANGTALKS, PODCAST_TITLE_LANGTALKS
from custom_types.field_keys import PodcastCatalogKeys as Keys
from db.repositories.podcasts import PodcastsRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_seed_is_idempotent(db):
    repo = PodcastsRepository(db)
    await repo.collection.delete_many({Keys.SLUG: PODCAST_SLUG_LANGTALKS})
    try:
        await repo.seed_langtalks()
        first = await repo.get_by_slug(PODCAST_SLUG_LANGTALKS)
        assert first is not None
        created_at = first[Keys.CREATED_AT]

        await repo.seed_langtalks()  # repeat
        count = await repo.count({Keys.SLUG: PODCAST_SLUG_LANGTALKS})
        assert count == 1
        second = await repo.get_by_slug(PODCAST_SLUG_LANGTALKS)
        assert second[Keys.CREATED_AT] == created_at  # not reset
        assert second[Keys.TITLE] == PODCAST_TITLE_LANGTALKS
    finally:
        await repo.collection.delete_many({Keys.SLUG: PODCAST_SLUG_LANGTALKS})


async def test_list_active_includes_seeded_row(db):
    repo = PodcastsRepository(db)
    await repo.collection.delete_many({Keys.SLUG: PODCAST_SLUG_LANGTALKS})
    try:
        await repo.seed_langtalks()
        active = await repo.list_active()
        slugs = {r[Keys.SLUG] for r in active}
        assert PODCAST_SLUG_LANGTALKS in slugs
    finally:
        await repo.collection.delete_many({Keys.SLUG: PODCAST_SLUG_LANGTALKS})


async def test_inactive_row_excluded(db):
    repo = PodcastsRepository(db)
    slug = "test-inactive-podcast"
    await repo.collection.delete_many({Keys.SLUG: slug})
    try:
        await repo.upsert_podcast(slug=slug, title="X", description="Y", active=False)
        active = await repo.list_active()
        assert slug not in {r[Keys.SLUG] for r in active}
    finally:
        await repo.collection.delete_many({Keys.SLUG: slug})
