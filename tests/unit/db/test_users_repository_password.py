"""Tests for the password / session / disable extensions to UsersRepository."""

from __future__ import annotations

import pytest

from custom_types.db_schemas import UserRole
from custom_types.field_keys import UserKeys
from db.repositories.users import UsersRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_create_user_persists_login_fields(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(
        email=unique_email,
        communities=[],
        role=UserRole.ADMIN,
        password_hash="hash-abc",
    )
    try:
        fetched = await repo.find_by_user_id(user_id)
        assert fetched[UserKeys.PASSWORD_HASH] == "hash-abc"
        assert fetched[UserKeys.SESSION_EPOCH] == 0
        assert fetched[UserKeys.DISABLED] is False
    finally:
        await repo.delete_user(user_id)


async def test_set_password_updates_hash_and_bumps_epoch(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash="old")
    try:
        ok = await repo.set_password(user_id, "new-hash")
        assert ok is True
        fetched = await repo.find_by_user_id(user_id)
        assert fetched[UserKeys.PASSWORD_HASH] == "new-hash"
        assert fetched[UserKeys.SESSION_EPOCH] == 1
    finally:
        await repo.delete_user(user_id)


async def test_bump_session_epoch_returns_new_value(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash="h")
    try:
        new_epoch = await repo.bump_session_epoch(user_id)
        assert new_epoch == 1
        again = await repo.bump_session_epoch(user_id)
        assert again == 2
    finally:
        await repo.delete_user(user_id)


async def test_set_disabled_toggles_flag(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash="h")
    try:
        await repo.set_disabled(user_id, True)
        assert (await repo.find_by_user_id(user_id))[UserKeys.DISABLED] is True
        await repo.set_disabled(user_id, False)
        assert (await repo.find_by_user_id(user_id))[UserKeys.DISABLED] is False
    finally:
        await repo.delete_user(user_id)


async def test_list_users_and_count(db, unique_email):
    repo = UsersRepository(db)
    base = await repo.count_users()
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash="h")
    try:
        assert await repo.count_users() == base + 1
        listed = await repo.list_users(limit=500, skip=0)
        assert any(u[UserKeys.USER_ID] == user_id for u in listed)
    finally:
        await repo.delete_user(user_id)


async def test_delete_user(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[], password_hash="h")
    deleted = await repo.delete_user(user_id)
    assert deleted is True
    assert await repo.find_by_user_id(user_id) is None


async def test_email_is_normalized_for_storage_and_lookup(db, unique_email):
    """Email is canonicalized (lower+strip) so casing cannot fork an identity."""
    repo = UsersRepository(db)
    mixed = f"  {unique_email.upper()}  "
    user_id = await repo.create_user(email=mixed, communities=[], password_hash="h")
    try:
        stored = await repo.find_by_user_id(user_id)
        assert stored[UserKeys.EMAIL] == unique_email.lower()
        # Lookup under any casing / surrounding whitespace resolves the same user.
        assert (await repo.find_by_email(unique_email.upper()))[UserKeys.USER_ID] == user_id
        assert (await repo.find_by_email(f" {unique_email} "))[UserKeys.USER_ID] == user_id
    finally:
        await repo.delete_user(user_id)
