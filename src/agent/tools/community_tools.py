"""Community-introspection tools.

These tools let the agent answer "what can I act on?" without leaking
any community the user is not authorized for.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool, tool

from agent.auth.user_context import current_user_context
from constants import (
    COMMUNITY_ALLOWED_OUTPUT_ACTIONS,
    COMMUNITY_STRUCTURE,
    KNOWN_WHATSAPP_CHAT_NAMES,
)

logger = logging.getLogger(__name__)


def build_community_tools() -> list[BaseTool]:
    """Return the community-introspection tools.

    No ACL check is needed on `list_my_communities` — it can only return
    the user's own communities, sourced from `UserContext`. `describe_community`
    DOES check ACL: a user must not be able to learn the structure of a
    community they don't own.
    """

    @tool
    def list_my_communities() -> list[str]:
        """List the WhatsApp community keys the current user is authorized to act on.

        Returns the community keys (e.g., "mcp_israel", "langtalks") only —
        no chat names, no metadata. Use describe_community to drill in.
        """
        ctx = current_user_context()
        return list(ctx.communities)

    @tool
    def describe_community(community_key: str) -> dict[str, Any]:
        """Return the structure of one WhatsApp community.

        Only callable on communities the current user owns; returns a
        permission-denied error otherwise.

        Args:
            community_key: Community identifier (e.g., "mcp_israel").

        Returns:
            Dict with the community's chat groups, the flat list of all
            chat names, and the output actions permitted for that
            community (which delivery destinations are allowed).
        """
        # Lazy import: keep ACL module out of the cold-start path.
        from agent.auth.acl import assert_user_owns_community

        ctx = current_user_context()
        assert_user_owns_community(ctx, community_key)

        groups = COMMUNITY_STRUCTURE.get(community_key, {})
        return {
            "community_key": community_key,
            "groups": groups,
            "chat_names": list(KNOWN_WHATSAPP_CHAT_NAMES.get(community_key, [])),
            "allowed_output_actions": list(
                COMMUNITY_ALLOWED_OUTPUT_ACTIONS.get(community_key, [])
            ),
        }

    return [list_my_communities, describe_community]
