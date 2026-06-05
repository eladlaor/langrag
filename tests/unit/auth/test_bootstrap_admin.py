"""Tests for bootstrap-admin seeding (src/db/bootstrap_admin.py)."""

from __future__ import annotations

import pytest

from config import get_settings
from db.bootstrap_admin import ensure_bootstrap_admin
from db.repositories.users import UsersRepository
from rag.auth.passwords import verify_password


async def _drop_users(db) -> None:
    """Empty the users collection so each test starts from a clean slate."""
    repo = UsersRepository(db)
    for user in await repo.list_users(limit=1000):
        await repo.delete_user(user["user_id"])


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """The settings singleton is cached; clear it so per-test env edits apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_seeds_admin_when_empty(db, monkeypatch, unique_email):
    await _drop_users(db)
    monkeypatch.setenv("LANGRAG_BOOTSTRAP_ADMIN_EMAIL", unique_email)
    monkeypatch.setenv("LANGRAG_BOOTSTRAP_ADMIN_PASSWORD", "s3cret-bootstrap-pw")
    get_settings.cache_clear()

    await ensure_bootstrap_admin(db)

    repo = UsersRepository(db)
    seeded = await repo.find_by_email(unique_email)
    assert seeded is not None
    assert seeded["role"] == "admin"
    assert seeded["disabled"] is False
    # Password is hashed, never stored in plaintext.
    assert seeded["password_hash"] != "s3cret-bootstrap-pw"
    assert verify_password("s3cret-bootstrap-pw", seeded["password_hash"]) is True


async def test_is_idempotent_when_users_exist(db, monkeypatch, unique_email):
    await _drop_users(db)
    repo = UsersRepository(db)
    await repo.create_user(email=unique_email, communities=[], password_hash="x")
    before = await repo.count_users()

    # Bootstrap creds set, but DB is non-empty -> must be a no-op.
    monkeypatch.setenv("LANGRAG_BOOTSTRAP_ADMIN_EMAIL", f"other-{unique_email}")
    monkeypatch.setenv("LANGRAG_BOOTSTRAP_ADMIN_PASSWORD", "another-pw")
    get_settings.cache_clear()

    await ensure_bootstrap_admin(db)

    assert await repo.count_users() == before
    assert await repo.find_by_email(f"other-{unique_email}") is None


async def test_fails_fast_when_empty_and_unconfigured(db, monkeypatch):
    await _drop_users(db)
    monkeypatch.delenv("LANGRAG_BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("LANGRAG_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError):
        await ensure_bootstrap_admin(db)
