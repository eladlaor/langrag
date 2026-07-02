"""
API-key scope resolution and MCP tool authorization.

Scopes gate what a RAG API key may do. The two scopes are defined by
`RAGApiKeyScope` (constants): FULL (internal/admin — every tool) and
PODCAST_QUERY (public consumer — only the public podcast tools).

Enforcement here is SERVER-SIDE and routing-independent: given a key record and a
tool name, `authorize_tool` decides admission. A PODCAST_QUERY-scoped key can
invoke ONLY search_podcasts / list_podcasts, so even if such a key ever reaches
an internal tool by any path, it is rejected.

Backward compatibility: a key record with no `scopes` field (or an empty list) is
treated as FULL, so every already-issued key keeps working. A key is treated as
PODCAST_QUERY-restricted only when PODCAST_QUERY is present AND FULL is absent.
"""

import logging
from datetime import UTC, datetime

from constants import (
    MCP_TOOL_LIST_PODCASTS,
    MCP_TOOL_SEARCH_PODCASTS,
    RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys

logger = logging.getLogger(__name__)


def _as_aware(value: datetime) -> datetime:
    """Coerce a possibly-naive Mongo datetime to UTC-aware."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# The exact set of tools a PODCAST_QUERY-scoped key may invoke. Frozen public
# surface; anything not in here is denied for that scope.
PUBLIC_MCP_TOOLS: frozenset[str] = frozenset({MCP_TOOL_SEARCH_PODCASTS, MCP_TOOL_LIST_PODCASTS})


class ScopeForbiddenError(PermissionError):
    """Raised when a key's scope does not permit the requested tool."""


def resolve_scopes(key_record: dict) -> set[str]:
    """Return the effective scope set for a key record.

    Deny-by-default with a legacy carve-out: an EXPLICIT non-empty `scopes` list
    is used as-is. An empty/missing `scopes` list resolves to {FULL} ONLY for a
    LEGACY key created before RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF (keys minted
    before scopes existed keep working). Any key created at/after the cutoff with
    empty scopes resolves to the EMPTY set (no FULL) — so a row written without
    explicit scopes post-deploy is denied, not silently promoted to admin. Mint
    time additionally forbids empty scopes (issue_key), so this is defense in
    depth against direct DB writes.
    """
    raw = key_record.get(RAGApiKeyKeys.SCOPES) or []
    if raw:
        return {str(s) for s in raw}

    created_at = key_record.get(RAGApiKeyKeys.CREATED_AT)
    if created_at is not None and _as_aware(created_at) >= RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF:
        logger.warning(
            "Empty-scope key created after the FULL cutoff resolves to no scopes (deny-by-default)",
            extra={"key_id": key_record.get(RAGApiKeyKeys.KEY_ID, "<unknown>"), "created_at": str(created_at)},
        )
        return set()
    return {str(RAGApiKeyScope.FULL)}


def is_full_scope(key_record: dict) -> bool:
    """True when the key has FULL scope (explicitly or by the empty-scope default)."""
    return str(RAGApiKeyScope.FULL) in resolve_scopes(key_record)


def is_podcast_query_only(key_record: dict) -> bool:
    """True when the key is restricted to the public podcast query surface.

    That is: PODCAST_QUERY is granted and FULL is not.
    """
    scopes = resolve_scopes(key_record)
    return str(RAGApiKeyScope.PODCAST_QUERY) in scopes and str(RAGApiKeyScope.FULL) not in scopes


def is_tool_allowed(key_record: dict, tool_name: str) -> bool:
    """Return whether the key's scope permits invoking `tool_name`.

    FULL-scoped keys may invoke any tool. PODCAST_QUERY-only keys are restricted
    to the PUBLIC_MCP_TOOLS set.
    """
    if is_full_scope(key_record):
        return True
    if is_podcast_query_only(key_record):
        return tool_name in PUBLIC_MCP_TOOLS
    # Any other (future) non-FULL scope defaults to deny-by-default for unknown
    # tools: only the explicitly-public tools are allowed.
    return tool_name in PUBLIC_MCP_TOOLS


def authorize_tool(key_record: dict, tool_name: str) -> None:
    """Fail-fast authorization gate for an MCP tool invocation.

    Raises ScopeForbiddenError (logged with context) when the key's scope does
    not permit the tool. Returns None on success.
    """
    if is_tool_allowed(key_record, tool_name):
        return
    key_id = key_record.get(RAGApiKeyKeys.KEY_ID, "<unknown>")
    logger.warning(
        "Scope-forbidden MCP tool invocation blocked",
        extra={
            "key_id": key_id,
            "tool_name": tool_name,
            "scopes": sorted(resolve_scopes(key_record)),
        },
    )
    raise ScopeForbiddenError(f"API key is not authorized to invoke tool '{tool_name}'. This key is scoped to the public podcast query surface only.")
