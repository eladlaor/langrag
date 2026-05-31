"""Tests for `resolve_user_from_api_key` (and indirectly `require_user`)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from agent.auth.user_resolver import resolve_user_from_api_key
from constants import COLLECTION_USER_API_KEYS, COLLECTION_USERS
from custom_types.field_keys import UserApiKeyKeys, UserKeys
from db.repositories.user_api_keys import UserApiKeysRepository
from db.repositories.users import UsersRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_valid_key_returns_user_context(db, unique_email):
    users = UsersRepository(db)
    keys = UserApiKeysRepository(db)
    user_id = await users.create_user(email=unique_email, communities=["mcp_israel"])
    key_id, plaintext = await keys.issue_key(user_id=user_id, name="t")
    try:
        ctx = await resolve_user_from_api_key(plaintext)
        assert ctx.user_id == user_id
        assert ctx.email == unique_email
        assert ctx.communities == ("mcp_israel",)
        # Quota remaining should be populated from the default quotas.
        assert ctx.quota_remaining[UserKeys.QUOTA_DAILY_CHAT_INPUT_TOKENS] > 0
    finally:
        await db[COLLECTION_USER_API_KEYS].delete_one({UserApiKeyKeys.KEY_ID: key_id})
        await db[COLLECTION_USERS].delete_one({UserKeys.USER_ID: user_id})


async def test_missing_key_raises_401(db):
    with pytest.raises(HTTPException) as exc_info:
        await resolve_user_from_api_key("")
    assert exc_info.value.status_code == 401


async def test_unknown_key_raises_401(db):
    with pytest.raises(HTTPException) as exc_info:
        await resolve_user_from_api_key("lk_user_definitely-not-a-real-key")
    assert exc_info.value.status_code == 401


async def test_disabled_key_raises_401(db, unique_email):
    users = UsersRepository(db)
    keys = UserApiKeysRepository(db)
    user_id = await users.create_user(email=unique_email, communities=["mcp_israel"])
    key_id, plaintext = await keys.issue_key(user_id=user_id, name="t")
    try:
        await keys.revoke(key_id)
        with pytest.raises(HTTPException) as exc_info:
            await resolve_user_from_api_key(plaintext)
        assert exc_info.value.status_code == 401
    finally:
        await db[COLLECTION_USER_API_KEYS].delete_one({UserApiKeyKeys.KEY_ID: key_id})
        await db[COLLECTION_USERS].delete_one({UserKeys.USER_ID: user_id})


async def test_dangling_key_with_missing_user_raises_401(db, unique_email):
    """A key whose user_id row no longer exists must NOT authenticate as a
    half-empty user; it must hard-fail."""
    users = UsersRepository(db)
    keys = UserApiKeysRepository(db)
    user_id = await users.create_user(email=unique_email, communities=["mcp_israel"])
    key_id, plaintext = await keys.issue_key(user_id=user_id, name="t")
    try:
        # Delete the user row, leave the key behind.
        await db[COLLECTION_USERS].delete_one({UserKeys.USER_ID: user_id})
        with pytest.raises(HTTPException) as exc_info:
            await resolve_user_from_api_key(plaintext)
        assert exc_info.value.status_code == 401
    finally:
        await db[COLLECTION_USER_API_KEYS].delete_one({UserApiKeyKeys.KEY_ID: key_id})
