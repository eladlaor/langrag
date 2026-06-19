"""FastAPI router for per-user preferences (saved RAG MMR setting).

Greenfield user-settings surface. Both endpoints are scoped to the caller's
own `user_id` resolved from the authenticated `UserContext`; there is no
admin override and no cross-user access.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from agent.auth.dependencies import require_user
from agent.auth.user_context import UserContext
from constants import ROUTE_USER_RAG_PREFERENCES
from custom_types.api_schemas import RagPreferencesResponse, RagPreferencesUpdate
from db.connection import get_database
from db.repositories.users import UsersRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["user-preferences"])


@router.get(ROUTE_USER_RAG_PREFERENCES.removeprefix("/users"), response_model=RagPreferencesResponse)
async def get_rag_preferences(user: UserContext = Depends(require_user)) -> RagPreferencesResponse:
    """Return the caller's resolved RAG preferences (saved value or config default)."""
    try:
        db = await get_database()
        repo = UsersRepository(db)
        prefs = await repo.get_rag_preferences(user.user_id)
        logger.info(
            "get_rag_preferences served",
            extra={"event": "get_rag_preferences", "function": "get_rag_preferences", "user_id": user.user_id},
        )
        return RagPreferencesResponse(
            mmr_lambda=prefs.mmr_lambda,
            enable_mmr_diversity=prefs.enable_mmr_diversity,
        )
    except Exception as e:
        logger.error(
            "get_rag_preferences handler failed",
            extra={"event": "get_rag_preferences_failed", "function": "get_rag_preferences", "user_id": user.user_id, "error": str(e)},
        )
        raise


@router.put(ROUTE_USER_RAG_PREFERENCES.removeprefix("/users"), response_model=RagPreferencesResponse)
async def put_rag_preferences(
    body: RagPreferencesUpdate,
    user: UserContext = Depends(require_user),
) -> RagPreferencesResponse:
    """Persist the caller's RAG preferences and return the saved values.

    `body.mmr_lambda` is already validated to [0, 1] by Pydantic (422 on
    violation), so no in-handler range check is needed here.
    """
    try:
        db = await get_database()
        repo = UsersRepository(db)
        await repo.set_rag_preferences(
            user.user_id,
            mmr_lambda=body.mmr_lambda,
            enable_mmr_diversity=body.enable_mmr_diversity,
        )
        logger.info(
            "put_rag_preferences saved",
            extra={"event": "put_rag_preferences", "function": "put_rag_preferences", "user_id": user.user_id, "mmr_lambda": body.mmr_lambda, "enable_mmr_diversity": body.enable_mmr_diversity},
        )
        return RagPreferencesResponse(
            mmr_lambda=body.mmr_lambda,
            enable_mmr_diversity=body.enable_mmr_diversity,
        )
    except Exception as e:
        logger.error(
            "put_rag_preferences handler failed",
            extra={"event": "put_rag_preferences_failed", "function": "put_rag_preferences", "user_id": user.user_id, "error": str(e)},
        )
        raise
