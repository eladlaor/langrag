"""FastAPI router for per-user agent API key management.

The agentic chatbot endpoints (`/api/agent/*`) authenticate with an
`X-API-Key` header resolved against the `user_api_keys` collection. A user has
no such key before minting one, so these management endpoints are gated by the
ordinary **cookie session** (`require_session`) instead — the cookie's
`user_id` is the same identifier stored on each `user_api_keys` row, so every
issued key is bound to the calling user.

Plaintext keys are returned exactly once, at issue time. Listing strips both
the hash and the plaintext; only the stable `key_id` is ever shown again.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response

from api.auth import require_session
from constants import HTTP_STATUS_NO_CONTENT, HTTP_STATUS_NOT_FOUND, ROUTE_USER_AGENT_KEYS
from custom_types.api_schemas import (
    AgentApiKeyIssued,
    AgentApiKeyIssueRequest,
    AgentApiKeySummary,
    CurrentUser,
)
from custom_types.field_keys import UserApiKeyKeys as Keys
from db.connection import get_database
from db.repositories.user_api_keys import UserApiKeysRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["agent-keys"])

_SUFFIX = ROUTE_USER_AGENT_KEYS.removeprefix("/users")


def _iso(value: object) -> str | None:
    """Render a stored timestamp as ISO-8601, tolerating None / non-datetime."""
    if isinstance(value, datetime):
        return value.isoformat()
    return None


@router.post(_SUFFIX, response_model=AgentApiKeyIssued)
async def issue_agent_key(
    body: AgentApiKeyIssueRequest,
    user: CurrentUser = Depends(require_session),
) -> AgentApiKeyIssued:
    """Mint a fresh agent API key bound to the calling user.

    The plaintext is present in the response only here; it is hashed before
    storage and can never be retrieved again.
    """
    try:
        db = await get_database()
        repo = UserApiKeysRepository(db)
        key_id, plaintext = await repo.issue_key(user_id=user.user_id, name=body.name)
        logger.info(
            "agent api key issued",
            extra={"event": "agent_key_issued", "function": "issue_agent_key", "user_id": user.user_id, "key_id": key_id},
        )
        return AgentApiKeyIssued(key_id=key_id, name=body.name, plaintext=plaintext)
    except Exception as e:
        logger.error(
            "issue_agent_key handler failed",
            extra={"event": "agent_key_issue_failed", "function": "issue_agent_key", "user_id": user.user_id, "error": str(e)},
        )
        raise


@router.get(_SUFFIX, response_model=list[AgentApiKeySummary])
async def list_agent_keys(
    user: CurrentUser = Depends(require_session),
) -> list[AgentApiKeySummary]:
    """List the caller's agent API keys (hashes and plaintext stripped)."""
    try:
        db = await get_database()
        repo = UserApiKeysRepository(db)
        rows = await repo.list_keys_for_user(user.user_id)
        return [
            AgentApiKeySummary(
                key_id=row[Keys.KEY_ID],
                name=row.get(Keys.NAME, ""),
                enabled=bool(row.get(Keys.ENABLED, False)),
                created_at=_iso(row.get(Keys.CREATED_AT)),
                last_used_at=_iso(row.get(Keys.LAST_USED_AT)),
            )
            for row in rows
        ]
    except Exception as e:
        logger.error(
            "list_agent_keys handler failed",
            extra={"event": "agent_keys_list_failed", "function": "list_agent_keys", "user_id": user.user_id, "error": str(e)},
        )
        raise


@router.delete(_SUFFIX + "/{key_id}", status_code=HTTP_STATUS_NO_CONTENT, response_class=Response)
async def revoke_agent_key(
    key_id: str,
    user: CurrentUser = Depends(require_session),
) -> Response:
    """Revoke one of the caller's keys.

    Ownership is enforced: a key_id that does not exist or belongs to another
    user yields 404, so a caller cannot probe for or disable foreign keys.
    """
    try:
        db = await get_database()
        repo = UserApiKeysRepository(db)
        row = await repo.find_by_key_id(key_id)
        if not row or row.get(Keys.USER_ID) != user.user_id:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail="Key not found.")
        await repo.revoke(key_id)
        logger.info(
            "agent api key revoked",
            extra={"event": "agent_key_revoked", "function": "revoke_agent_key", "user_id": user.user_id, "key_id": key_id},
        )
        return Response(status_code=HTTP_STATUS_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "revoke_agent_key handler failed",
            extra={"event": "agent_key_revoke_failed", "function": "revoke_agent_key", "user_id": user.user_id, "key_id": key_id, "error": str(e)},
        )
        raise
