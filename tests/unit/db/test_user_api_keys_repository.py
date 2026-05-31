"""Tests for UserApiKeysRepository (agentic chatbot layer)."""

from __future__ import annotations

import pytest

from constants import AGENT_USER_API_KEY_PREFIX
from custom_types.field_keys import UserApiKeyKeys
from db.repositories.user_api_keys import UserApiKeysRepository
from rag.auth.hashing import hash_api_key
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_issue_and_find_by_hash(db, unique_user_id):
    repo = UserApiKeysRepository(db)
    key_id, plaintext = await repo.issue_key(user_id=unique_user_id, name="test")
    try:
        assert plaintext.startswith(AGENT_USER_API_KEY_PREFIX)
        record = await repo.find_by_hash(hash_api_key(plaintext))
        assert record is not None
        assert record[UserApiKeyKeys.KEY_ID] == key_id
        assert record[UserApiKeyKeys.USER_ID] == unique_user_id
        assert record[UserApiKeyKeys.ENABLED] is True
    finally:
        await repo.delete_one({UserApiKeyKeys.KEY_ID: key_id})


async def test_revoke_disables_key(db, unique_user_id):
    repo = UserApiKeysRepository(db)
    key_id, plaintext = await repo.issue_key(user_id=unique_user_id, name="test")
    try:
        await repo.revoke(key_id)
        # find_by_hash filters to enabled=True so revoked keys vanish
        assert await repo.find_by_hash(hash_api_key(plaintext)) is None
        # But find_by_key_id still returns the row with enabled=False
        row = await repo.find_by_key_id(key_id)
        assert row is not None
        assert row[UserApiKeyKeys.ENABLED] is False
    finally:
        await repo.delete_one({UserApiKeyKeys.KEY_ID: key_id})


async def test_touch_last_used(db, unique_user_id):
    repo = UserApiKeysRepository(db)
    key_id, _ = await repo.issue_key(user_id=unique_user_id)
    try:
        before = await repo.find_by_key_id(key_id)
        assert before[UserApiKeyKeys.LAST_USED_AT] is None
        await repo.touch_last_used(key_id)
        after = await repo.find_by_key_id(key_id)
        assert after[UserApiKeyKeys.LAST_USED_AT] is not None
    finally:
        await repo.delete_one({UserApiKeyKeys.KEY_ID: key_id})


async def test_list_keys_for_user_strips_hash(db, unique_user_id):
    repo = UserApiKeysRepository(db)
    key_id, _ = await repo.issue_key(user_id=unique_user_id, name="k1")
    try:
        listing = await repo.list_keys_for_user(unique_user_id)
        assert len(listing) >= 1
        first = next(k for k in listing if k[UserApiKeyKeys.KEY_ID] == key_id)
        assert UserApiKeyKeys.KEY_HASH not in first
        assert "_id" not in first
    finally:
        await repo.delete_one({UserApiKeyKeys.KEY_ID: key_id})
