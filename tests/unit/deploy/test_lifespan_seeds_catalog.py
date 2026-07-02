"""F2: the FastAPI lifespan seeds the podcast catalog on startup.

Without this, a fresh deploy makes list_podcasts() return []. This drives the
lifespan with all external deps mocked and asserts PodcastsRepository.seed_langtalks
is awaited during the DB-init block (right after indexes + bootstrap admin).
No Docker.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The lifespan fails fast on missing API keys / login secrets before the DB block.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_lifespan_seeds_podcast_catalog():
    import main

    fake_db = MagicMock()
    seeded = AsyncMock()

    with (
        patch("config.get_settings") as p_settings,
        patch("db.connection.get_database", AsyncMock(return_value=fake_db)),
        patch("db.connection.close_connection", AsyncMock()),
        patch("db.indexes.ensure_indexes", AsyncMock()),
        patch("db.bootstrap_admin.ensure_bootstrap_admin", AsyncMock()),
        patch("db.repositories.podcasts.PodcastsRepository") as p_repo,
        patch("scheduler.newsletter_scheduler.start_scheduler", AsyncMock()),
        patch("scheduler.newsletter_scheduler.stop_scheduler", AsyncMock()),
        patch("graphs.checkpointer.close_checkpointer", AsyncMock()),
    ):
        # Disable the login / google gates so the pre-DB fail-fast checks pass.
        settings = MagicMock()
        settings.login.enabled = False
        settings.google.enabled = False
        p_settings.return_value = settings
        p_repo.return_value.seed_langtalks = seeded

        async with main.lifespan(MagicMock()):
            pass

    seeded.assert_awaited_once()
