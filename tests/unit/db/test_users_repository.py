"""Tests for UsersRepository (agentic chatbot layer)."""

from __future__ import annotations

import pytest
from pymongo.errors import DuplicateKeyError

from custom_types.db_schemas import UserDailyUsage, UserRole
from custom_types.field_keys import UserKeys
from db.repositories.users import UsersRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_create_user_round_trip(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(
        email=unique_email,
        communities=["mcp_israel", "langtalks"],
    )
    try:
        fetched = await repo.find_by_user_id(user_id)
        assert fetched is not None
        assert fetched[UserKeys.EMAIL] == unique_email
        assert fetched[UserKeys.ROLE] == str(UserRole.ADMIN)
        assert sorted(fetched[UserKeys.COMMUNITIES]) == ["langtalks", "mcp_israel"]
        assert fetched[UserKeys.QUOTAS]["daily_chat_input_tokens"] > 0
    finally:
        await repo.delete_one({UserKeys.USER_ID: user_id})


async def test_find_by_email(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[])
    try:
        found = await repo.find_by_email(unique_email)
        assert found is not None
        assert found[UserKeys.USER_ID] == user_id
    finally:
        await repo.delete_one({UserKeys.USER_ID: user_id})


async def test_unique_email_constraint(db, unique_email):
    """Inserting two users with the same email must raise DuplicateKeyError."""
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[])
    try:
        with pytest.raises(DuplicateKeyError):
            await repo.create_user(email=unique_email, communities=[])
    finally:
        await repo.delete_one({UserKeys.USER_ID: user_id})


async def test_set_daily_usage(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[])
    try:
        usage = UserDailyUsage(
            date="2026-05-28",
            chat_input_tokens=1234,
            chat_output_tokens=200,
            memory_tokens=99,
            newsletter_runs=1,
        )
        ok = await repo.set_daily_usage(user_id, usage)
        assert ok is True
        fetched = await repo.find_by_user_id(user_id)
        assert fetched[UserKeys.DAILY_USAGE]["chat_input_tokens"] == 1234
    finally:
        await repo.delete_one({UserKeys.USER_ID: user_id})


async def test_touch_last_seen(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_user(email=unique_email, communities=[])
    try:
        before = await repo.find_by_user_id(user_id)
        assert before[UserKeys.LAST_SEEN_AT] is None
        await repo.touch_last_seen(user_id)
        after = await repo.find_by_user_id(user_id)
        assert after[UserKeys.LAST_SEEN_AT] is not None
    finally:
        await repo.delete_one({UserKeys.USER_ID: user_id})
