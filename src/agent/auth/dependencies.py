"""FastAPI dependency that resolves a request to its `UserContext`.

Mirrors `src/rag/auth/dependencies.py::require_api_key` but resolves the
key into a full `UserContext` (rather than a raw api-key record) so the
agent route handler can `with user_context(ctx):` for the duration of
the turn.

The `Authorization: Bearer <key>` form is accepted alongside the
`X-API-Key` header so both conventions Just Work.
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException

from constants import (
    HTTP_STATUS_UNAUTHORIZED,
    RAG_API_KEY_BEARER_SCHEME,
)

from .user_context import UserContext
from .user_resolver import resolve_user_from_api_key

logger = logging.getLogger(__name__)


async def require_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserContext:
    """Resolve the inbound request to an authenticated `UserContext`."""
    plaintext = _extract_key(x_api_key, authorization)
    if not plaintext:
        raise HTTPException(
            status_code=HTTP_STATUS_UNAUTHORIZED,
            detail="Missing API key. Send X-API-Key or Authorization: Bearer <key>.",
        )
    return await resolve_user_from_api_key(plaintext)


def _extract_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].strip().lower() == RAG_API_KEY_BEARER_SCHEME.lower():
            return parts[1].strip()
    return None
