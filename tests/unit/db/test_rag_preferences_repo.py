"""Repository tests for per-user RAG preferences (criteria 4, 6, and 5 repo side).

DB-backed: seeds a real user, then exercises get/set of rag_preferences.
"""

from __future__ import annotations

import uuid

import pytest

from config import get_settings
from custom_types.field_keys import UserKeys
from db.repositories.users import UsersRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = requires_mongodb


async def _make_user(db) -> str:
    """Insert a minimal user doc directly.

    We bypass UsersRepository.create_user because it always writes
    google_sub=None, and this DB carries a (non-sparse) unique index on
    google_sub, so a second null would collide. Omitting the field entirely
    keeps a sparse index happy and is sufficient for these tests.
    """
    from constants import CURRENT_SCHEMA_VERSION_USER, SCHEMA_VERSION_FIELD

    repo = UsersRepository(db)
    user_id = str(uuid.uuid4())
    await repo.collection.insert_one(
        {
            SCHEMA_VERSION_FIELD: CURRENT_SCHEMA_VERSION_USER,
            UserKeys.USER_ID: user_id,
            UserKeys.EMAIL: f"rag-pref-{uuid.uuid4()}@example.com",
            UserKeys.ROLE: "viewer",
            UserKeys.DISABLED: False,
        }
    )
    _SEEDED_USER_IDS.append(user_id)
    return user_id


# user_ids seeded by this module, cleaned up after the session so the shared
# users collection is left as we found it.
_SEEDED_USER_IDS: list[str] = []


@pytest.fixture(autouse=True)
async def _cleanup_seeded_users(db):
    yield
    if _SEEDED_USER_IDS:
        repo = UsersRepository(db)
        await repo.collection.delete_many({UserKeys.USER_ID: {"$in": _SEEDED_USER_IDS}})
        _SEEDED_USER_IDS.clear()


# --- Criterion 4 + 6: precedence and round-trip ---
async def test_get_falls_back_to_config_default_when_unset(db):
    repo = UsersRepository(db)
    user_id = await _make_user(db)

    prefs = await repo.get_rag_preferences(user_id)

    rag = get_settings().rag
    assert prefs.mmr_lambda == pytest.approx(rag.mmr_lambda)
    assert prefs.enable_mmr_diversity == rag.enable_mmr_diversity


async def test_set_then_get_round_trip(db):
    repo = UsersRepository(db)
    user_id = await _make_user(db)

    saved = await repo.set_rag_preferences(user_id, mmr_lambda=0.3, enable_mmr_diversity=False)
    assert saved.mmr_lambda == pytest.approx(0.3)
    assert saved.enable_mmr_diversity is False

    prefs = await repo.get_rag_preferences(user_id)
    assert prefs.mmr_lambda == pytest.approx(0.3)
    assert prefs.enable_mmr_diversity is False


async def test_saved_value_beats_config_default(db):
    """Precedence: a saved value is returned even though it differs from config."""
    repo = UsersRepository(db)
    user_id = await _make_user(db)

    config_default = get_settings().rag.mmr_lambda
    distinct = 0.15 if config_default != 0.15 else 0.25
    await repo.set_rag_preferences(user_id, mmr_lambda=distinct, enable_mmr_diversity=True)

    prefs = await repo.get_rag_preferences(user_id)
    assert prefs.mmr_lambda == pytest.approx(distinct)
    assert prefs.mmr_lambda != pytest.approx(config_default)


# --- Criterion 5 (repository side): fail-fast ---
@pytest.mark.parametrize("bad", [-0.1, 1.1])
async def test_set_rejects_out_of_range_lambda(db, bad):
    repo = UsersRepository(db)
    user_id = await _make_user(db)
    with pytest.raises(ValueError):
        await repo.set_rag_preferences(user_id, mmr_lambda=bad, enable_mmr_diversity=True)


async def test_get_unknown_user_raises(db):
    repo = UsersRepository(db)
    with pytest.raises(ValueError):
        await repo.get_rag_preferences("does-not-exist")
