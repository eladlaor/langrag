"""Access control checks for agent tools.

Every tool that targets a community MUST call `assert_user_owns_community`
as its first line, BEFORE any DB write or graph kick-off. The check
raises `PermissionError`; the custom tool node catches it and returns a
`ToolMessage(status="error")` so the LLM sees the denial in its loop
instead of crashing the turn.

`filter_communities` is the multi-community equivalent: useful when the
LLM emits a list and we want to strip unauthorized entries silently
(e.g., `list_my_communities` should never error on a user with no
communities — just return empty).
"""

from __future__ import annotations

import logging

from constants import COMMUNITY_STRUCTURE

from .user_context import UserContext

logger = logging.getLogger(__name__)


class CommunityPermissionError(PermissionError):
    """Raised when a user attempts an action on a community they don't own.

    Subclasses `PermissionError` so a generic `except PermissionError`
    catches it, but carries extra context (`community_key`, `user_id`)
    that the tool node uses to format the `ToolMessage` content.
    """

    def __init__(self, user_id: str, community_key: str) -> None:
        self.user_id = user_id
        self.community_key = community_key
        super().__init__(
            f"User {user_id!r} is not authorized for community {community_key!r}."
        )


def assert_user_owns_community(user: UserContext, community_key: str) -> None:
    """Raise `CommunityPermissionError` if `user` does not own `community_key`.

    Also raises `ValueError` if `community_key` is not a known community —
    a typo from the LLM should not silently pass auth.
    """
    if community_key not in COMMUNITY_STRUCTURE:
        raise ValueError(
            f"Unknown community: {community_key!r}. "
            f"Valid keys: {sorted(COMMUNITY_STRUCTURE)}"
        )
    if not user.owns(community_key):
        logger.info(
            "ACL denial: user_id=%s community=%s",
            user.user_id,
            community_key,
        )
        raise CommunityPermissionError(user.user_id, community_key)


def filter_communities(user: UserContext, requested: list[str]) -> list[str]:
    """Return only the requested communities the user is authorized for.

    Unknown community keys are dropped (NOT errors), because the LLM may
    typo and we'd rather silently exclude than crash a multi-community
    listing. Authorization is still per-community.
    """
    out: list[str] = []
    for key in requested:
        if key not in COMMUNITY_STRUCTURE:
            logger.debug("filter_communities: dropping unknown community %r", key)
            continue
        if user.owns(key):
            out.append(key)
    return out
