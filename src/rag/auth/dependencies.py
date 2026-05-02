"""
FastAPI authentication dependencies for the public RAG API.

Validates the X-API-Key (or `Authorization: Bearer ...`) header against the
hashed records in rag_api_keys. When `RAG_AUTH_ENABLED` is false (default for
local dev), the dependency is a no-op so existing tests continue to pass.
"""

import logging

from fastapi import Header, HTTPException

from config import get_settings
from constants import (
    HTTP_STATUS_UNAUTHORIZED,
    RAG_API_KEY_BEARER_SCHEME,
)
from custom_types.field_keys import RAGApiKeyKeys as Keys
from db.connection import get_database
from db.repositories.rag_api_keys import RAGApiKeysRepository
from rag.auth.hashing import hash_api_key

logger = logging.getLogger(__name__)


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict:
    """
    Validate an inbound API key and return the matching key record.

    Behaviour:
      - If RAG_AUTH_ENABLED is false, returns a sentinel allowing the request through
        (no DB lookup) so local dev and existing tests don't need to provision keys.
      - Otherwise extracts the key from X-API-Key first, then a Bearer token, hashes
        it with the configured pepper, looks it up, and returns the record. Refuses
        with 401 on any miss.
    """
    settings = get_settings().rag
    if not settings.auth_enabled:
        return {Keys.KEY_ID: "auth-disabled", Keys.OWNER: "local-dev", Keys.SCOPES: []}

    plaintext = _extract_key(x_api_key, authorization)
    if not plaintext:
        raise HTTPException(
            status_code=HTTP_STATUS_UNAUTHORIZED,
            detail="Missing API key. Send X-API-Key or Authorization: Bearer <key>.",
        )

    db = await get_database()
    repo = RAGApiKeysRepository(db)
    record = await repo.find_by_hash(hash_api_key(plaintext))
    if not record:
        logger.warning("Unknown or disabled RAG API key presented")
        raise HTTPException(
            status_code=HTTP_STATUS_UNAUTHORIZED,
            detail="Invalid or disabled API key.",
        )

    await repo.touch_last_used(record[Keys.KEY_ID])
    return record


def _extract_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].strip().lower() == RAG_API_KEY_BEARER_SCHEME.lower():
            return parts[1].strip()
    return None
