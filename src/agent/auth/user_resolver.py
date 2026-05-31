"""Resolve an inbound API key to its owning `User` + `UserContext`.

The agent API uses a separate `user_api_keys` collection from the public
RAG path's `rag_api_keys` (see commit 2). Each row maps `key_hash ->
user_id`; the resolver looks the hash up, then loads the matching `users`
row, and assembles a `UserContext`.

Failure modes raise `HTTPException(401)` — fail-fast, no soft denials.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from constants import HTTP_STATUS_UNAUTHORIZED
from custom_types.field_keys import UserApiKeyKeys, UserKeys
from db.connection import get_database
from db.repositories.user_api_keys import UserApiKeysRepository
from db.repositories.users import UsersRepository
from rag.auth.hashing import hash_api_key

from .user_context import UserContext

logger = logging.getLogger(__name__)


def _today_usage(user_row: dict[str, Any]) -> dict[str, int]:
    """Compute today's remaining quotas from the user's daily_usage row.

    The agent runtime persists daily counters via
    `UsersRepository.set_daily_usage`; commit 11 (observability + quota
    enforcement) wires the rolling reset against the UTC date.
    """
    from datetime import UTC, datetime

    quotas = user_row.get(UserKeys.QUOTAS, {}) or {}
    usage = user_row.get(UserKeys.DAILY_USAGE) or {}
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if usage.get(UserKeys.USAGE_DATE) != today:
        # Stale row from a previous day — treat as full budget remaining.
        usage = {}

    remaining: dict[str, int] = {}
    for quota_key, usage_key in [
        (UserKeys.QUOTA_DAILY_CHAT_INPUT_TOKENS, UserKeys.USAGE_CHAT_INPUT_TOKENS),
        (UserKeys.QUOTA_DAILY_CHAT_OUTPUT_TOKENS, UserKeys.USAGE_CHAT_OUTPUT_TOKENS),
        (UserKeys.QUOTA_DAILY_MEMORY_TOKENS, UserKeys.USAGE_MEMORY_TOKENS),
        (UserKeys.QUOTA_DAILY_NEWSLETTER_RUNS, UserKeys.USAGE_NEWSLETTER_RUNS),
    ]:
        cap = int(quotas.get(quota_key, 0))
        used = int(usage.get(usage_key, 0))
        remaining[quota_key] = max(0, cap - used)
    return remaining


async def resolve_user_from_api_key(api_key: str) -> UserContext:
    """Resolve a plaintext API key to a `UserContext`.

    Raises `HTTPException(401)` on:
      - missing / empty key
      - unknown / disabled key
      - dangling key (key row exists but user row is missing)
    """
    if not api_key:
        raise HTTPException(
            status_code=HTTP_STATUS_UNAUTHORIZED,
            detail="Missing API key.",
        )

    db = await get_database()
    keys_repo = UserApiKeysRepository(db)
    key_row = await keys_repo.find_by_hash(hash_api_key(api_key))
    if not key_row:
        logger.warning("Unknown or disabled user API key presented")
        raise HTTPException(
            status_code=HTTP_STATUS_UNAUTHORIZED,
            detail="Invalid or disabled API key.",
        )

    user_id = key_row[UserApiKeyKeys.USER_ID]
    users_repo = UsersRepository(db)
    user_row = await users_repo.find_by_user_id(user_id)
    if not user_row:
        # Dangling key — refuse rather than fall back to an empty user.
        logger.error(
            "Dangling user_api_keys row: key_id=%s user_id=%s has no users row",
            key_row.get(UserApiKeyKeys.KEY_ID),
            user_id,
        )
        raise HTTPException(
            status_code=HTTP_STATUS_UNAUTHORIZED,
            detail="Invalid or disabled API key.",
        )

    # Best-effort: bump last_used_at + last_seen_at; don't fail auth on a write hiccup.
    await keys_repo.touch_last_used(key_row[UserApiKeyKeys.KEY_ID])
    await users_repo.touch_last_seen(user_id)

    return UserContext(
        user_id=user_id,
        email=user_row.get(UserKeys.EMAIL, ""),
        role=user_row.get(UserKeys.ROLE, "admin"),
        communities=tuple(user_row.get(UserKeys.COMMUNITIES, []) or []),
        quota_remaining=_today_usage(user_row),
    )
