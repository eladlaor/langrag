"""
Per-request authentication context for the Streamable HTTP MCP transport.

FastMCP's tool invocations carry no caller identity, so scope enforcement needs a
side channel from the transport (where the bearer token is presented) to the tool
wrappers (where a tool name is known). This module provides that channel.

Transport reality (mcp 1.27.0, vendored FastMCP under mcp.server.fastmcp):

  - The Streamable HTTP transport (stateless mode) serves each JSON-RPC message
    on its own `POST /mcp` request. `ConsumerKeyAuthMiddleware` authenticates the
    bearer on that request and sets the resolved key record in a ContextVar.
    The session manager dispatches the per-request server task from WITHIN the
    request's ASGI call (via an `anyio` task-group start, which copies the
    CURRENT context), so the record set by the middleware IS captured into the
    tool task. Unlike the retired SSE transport's decoupled GET-stream/POST
    split, the authenticating request and the tool-executing request are the
    same, so identity is naturally per-call.

  - As a belt-and-suspenders fallback (should the ContextVar not propagate), the
    tool path ALSO reads the bearer off the current request via FastMCP's
    per-call `request_context.request` (headers included).

Fail-closed (C1): on the HTTP transport, if NO key record can be resolved at
tool-execution time, the call is REJECTED, never silently allowed. Only the stdio
transport (local dev, auth delegated to the local client) keeps the no-op.

Anonymous lane (BYOA): when rag.mcp_anonymous_enabled is true, a request with no
bearer gets a synthetic podcast_query-scoped record keyed by a hash of the client
IP (see build_anonymous_record) instead of a 401. A PRESENT but invalid bearer
still 401s — never a silent downgrade to anonymous. Anonymous principals are
confined to the public podcast tools by the scope machinery and admitted through
their own tighter quota stack (rag/quota/admission.py).

Live revocation (H1): to honor "keys revocable at any time",
`authorize_current_tool` re-resolves the key by key_id against the live `enabled`
flag on a short TTL (rag.mcp_key_reauth_ttl_seconds), so a revoked/rotated key
stops working within the TTL. On the stateless transport records are resolved
fresh per request, so the TTL re-resolve is a cheap no-op in the common case.
"""

import asyncio
import hashlib
import logging
import time
from contextvars import ContextVar

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.client_ip import resolve_client_ip
from config import get_settings
from constants import (
    HTTP_STATUS_UNAUTHORIZED,
    RAG_ANON_IP_HASH_LEN,
    RAG_ANON_KEY_ID_PREFIX,
    RAG_ANON_OWNER,
    RAG_API_KEY_BEARER_SCHEME,
    RAGApiKeyScope,
)
from custom_types.field_keys import RAGApiKeyKeys
from db.connection import get_database
from db.repositories.podcast_api_consumers import PodcastApiConsumersRepository
from db.repositories.rag_api_keys import RAGApiKeysRepository
from rag.auth.hashing import hash_api_key
from rag.auth.scopes import ScopeForbiddenError, authorize_tool

logger = logging.getLogger(__name__)

# The authenticated key record for the current MCP request, or None outside a
# request (e.g. stdio transport, where auth is delegated to the local client).
# The record carries a synthetic `_resolved_at` epoch used to bound how long the
# session-frozen record is trusted before a live re-resolve (H1).
_current_key_record: ContextVar[dict | None] = ContextVar("mcp_current_key_record", default=None)

# True once the Streamable HTTP transport is active. Distinguishes transport for the
# fail-closed decision: HTTP with no resolvable record MUST reject; stdio no-ops.
_http_transport_active: ContextVar[bool] = ContextVar("mcp_http_transport_active", default=False)

# Synthetic key_id for the shared internal MCP bearer (settings.rag.mcp_api_key).
# It is FULL-scoped so internal deployments keep full tool access without a
# rag_api_keys row for the shared bearer.
_INTERNAL_BEARER_KEY_ID = "mcp-internal-bearer"

# Synthetic field: epoch seconds when the record was (re)resolved, for the H1 TTL.
_RESOLVED_AT = "_resolved_at"


def anonymous_key_id_for_ip(client_ip: str) -> str:
    """Derive the anonymous principal's key_id from the resolved client IP.

    The IP is hashed (SHA-256 prefix) so quota rows, Langfuse trace tags, and
    logs never carry a raw IP; the id stays stable per IP so per-IP quotas hold.
    """
    digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:RAG_ANON_IP_HASH_LEN]
    return f"{RAG_ANON_KEY_ID_PREFIX}{digest}"


def is_anonymous_key_id(key_id: str | None) -> bool:
    """True when the key_id denotes a keyless (anonymous) principal."""
    return bool(key_id) and key_id.startswith(RAG_ANON_KEY_ID_PREFIX)


def build_anonymous_record(client_ip: str) -> dict:
    """Synthesize the key record for a keyless (anonymous) caller.

    SCOPES is an EXPLICIT non-empty list: resolve_scopes() promotes a record with
    empty/missing scopes and no created_at to FULL (legacy carve-out), which must
    never happen for an anonymous principal. Regression-tested.
    """
    return {
        RAGApiKeyKeys.KEY_ID: anonymous_key_id_for_ip(client_ip),
        RAGApiKeyKeys.OWNER: RAG_ANON_OWNER,
        RAGApiKeyKeys.SCOPES: [str(RAGApiKeyScope.PODCAST_QUERY)],
    }

_UNAUTHORIZED_MESSAGE = "Invalid or missing MCP API key."

# Strong refs to fire-and-forget tasks. asyncio only holds a weak ref to a task
# created by create_task, so without this the last_used_at update can be GC'd
# mid-flight ("Task was destroyed but it is pending"). Discard on completion.
_background_tasks: set[asyncio.Task] = set()


def mark_http_transport_active() -> None:
    """Flag that the Streamable HTTP transport is running (enables fail-closed enforcement)."""
    _http_transport_active.set(True)


def set_current_key_record(record: dict | None) -> None:
    """Set the per-request authenticated key record (used by the middleware/tests)."""
    _current_key_record.set(record)


def get_current_key_record() -> dict | None:
    """Return the per-request authenticated key record, or None when unset."""
    return _current_key_record.get()


def _stamp(record: dict | None) -> dict | None:
    """Attach the resolve timestamp used by the H1 TTL re-resolve."""
    if record is not None:
        record[_RESOLVED_AT] = time.monotonic()
    return record


async def _reresolve_if_stale(record: dict) -> dict | None:
    """Re-resolve the key against the live `enabled` flag when the TTL elapsed.

    Returns the (refreshed) record if still valid, or None if the key is now
    disabled/unknown (caller fails closed). The internal bearer is never
    re-resolved (no DB row); it stays FULL for the stream lifetime by design.

    Re-resolution applies ONLY to a stamped record — one that came through the
    HTTP middleware / request-context fallback (which always stamp). An UNSTAMPED
    record (set directly, e.g. a stdio/test path) is trusted as-is and never
    triggers a DB read: only the long-lived HTTP stream has the staleness problem
    H1 addresses.
    """
    key_id = record.get(RAGApiKeyKeys.KEY_ID)
    if not key_id or key_id == _INTERNAL_BEARER_KEY_ID or is_anonymous_key_id(key_id):
        # Internal bearer and anonymous principals have no rag_api_keys row; a
        # re-resolve would find nothing and wrongly fail-close them.
        return record

    resolved_at = record.get(_RESOLVED_AT)
    if resolved_at is None:
        return record

    ttl = get_settings().rag.mcp_key_reauth_ttl_seconds
    if ttl > 0 and (time.monotonic() - resolved_at) < ttl:
        return record

    db = await get_database()
    fresh = await RAGApiKeysRepository(db).find_enabled_by_key_id(key_id)
    if fresh is None:
        logger.warning(
            "MCP key re-authorization failed: key no longer enabled",
            extra={"event": "mcp_key_reauth_revoked", "key_id": key_id},
        )
        return None
    return _stamp(fresh)


async def authorize_current_tool(tool_name: str) -> None:
    """Enforce the current key's scope for `tool_name` (fail-fast, fail-closed on HTTP).

    Resolution order at tool-execution time:
      1. The ContextVar record set by the auth middleware on the POST /mcp
         request (propagated into the tool task via the anyio context copy).
      2. Fallback: the bearer on the current request, read from FastMCP's
         per-call request context.
    On the HTTP transport, if neither yields a record the call is REJECTED
    (ScopeForbiddenError). On stdio (no HTTP transport, no record), it is a no-op.

    Before authorizing, a stale session-frozen record is re-resolved against the
    live `enabled` flag on a short TTL (H1), so a revoked key stops working.

    Raises ScopeForbiddenError when the presented key may not invoke the tool, or
    when no key can be resolved on the HTTP transport.
    """
    record = get_current_key_record()
    if record is None:
        record = await _record_from_request_context()

    if record is None:
        if _http_transport_active.get():
            logger.warning(
                "MCP tool call rejected: no key record resolved on HTTP transport (fail-closed)",
                extra={"event": "mcp_authz_no_record_failclosed", "tool_name": tool_name},
            )
            raise ScopeForbiddenError(f"No authenticated MCP key present for tool '{tool_name}'.")
        # stdio path: auth delegated to the local client.
        return

    fresh = await _reresolve_if_stale(record)
    if fresh is None:
        raise ScopeForbiddenError(f"MCP key is revoked or disabled; not authorized for tool '{tool_name}'.")
    # Keep the ContextVar record fresh so the next call reuses the new stamp.
    set_current_key_record(fresh)
    authorize_tool(fresh, tool_name)


async def _record_from_request_context() -> dict | None:
    """Resolve a key record from the current request's bearer, if reachable.

    FastMCP exposes the per-call request context; on the Streamable HTTP
    transport its `request` is the POST /mcp Starlette Request, whose
    Authorization header carries the bearer even when the ContextVar did not
    propagate. Any failure to reach the context resolves to None (caller decides
    fail-open vs fail-closed by transport).
    """
    try:
        from mcp.server.lowlevel.server import request_ctx

        request = request_ctx.get().request
    except Exception:
        # LookupError when there is no active request context (outside a tool
        # dispatch); any other failure means the vendored internals shifted.
        # Either way, degrade to "no record" — the caller fails closed on HTTP.
        return None

    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    plaintext = _extract_bearer(headers.get("authorization"))
    if not plaintext:
        # Mirror the middleware's keyless decision so the fail-closed check does
        # not reject a legitimate anonymous call if the ContextVar ever fails to
        # propagate. An anonymous record is only synthesized under the flag.
        try:
            if get_settings().rag.mcp_anonymous_enabled:
                return _stamp(build_anonymous_record(resolve_client_ip(request)))
        except Exception as e:  # noqa: BLE001 — degrade to no-record, caller fail-closes
            logger.error("MCP request-context anonymous resolution failed", extra={"event": "mcp_reqctx_anon_error", "error": str(e)})
        return None
    try:
        return _stamp(await resolve_key_record(plaintext))
    except Exception as e:  # noqa: BLE001 — auth failure must not 500 the tool
        logger.error("MCP request-context key resolution failed", extra={"event": "mcp_reqctx_auth_error", "error": str(e)})
        return None


def touch_current_consumer_last_used() -> None:
    """Fire-and-forget refresh of the consumer's last_used_at after an authorized call.

    Schedules the update as a background task so it never adds latency to the tool
    response. No-op for the internal bearer (no consumer row). A strong ref is
    held in a module set until the task finishes, so it cannot be GC'd mid-flight.
    """
    record = get_current_key_record()
    if record is None:
        return
    key_id = record.get(RAGApiKeyKeys.KEY_ID)
    if not key_id or key_id == _INTERNAL_BEARER_KEY_ID or is_anonymous_key_id(key_id):
        # Internal bearer and anonymous principals have no podcast_api_consumers row.
        return
    try:
        task = asyncio.create_task(_touch_last_used(key_id))
    except RuntimeError:
        # No running loop (shouldn't happen on the async tool path); skip quietly.
        logger.debug("No running loop for last_used_at update", extra={"key_id": key_id})
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _touch_last_used(key_id: str) -> None:
    try:
        db = await get_database()
        await PodcastApiConsumersRepository(db).touch_last_used(key_id)
    except Exception as e:  # noqa: BLE001 — non-critical fire-and-forget path
        logger.warning(
            "Failed to refresh consumer last_used_at",
            extra={"event": "mcp_consumer_touch_failed", "key_id": key_id, "error": str(e)},
        )


def _extract_bearer(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) == 2 and parts[0].strip().lower() == RAG_API_KEY_BEARER_SCHEME.lower():
        return parts[1].strip()
    return None


async def resolve_key_record(plaintext: str) -> dict | None:
    """Resolve a presented bearer to a key record, or None if unknown/disabled.

    The shared internal bearer (settings.rag.mcp_api_key) resolves to a synthetic
    FULL-scope record. Otherwise the token is hashed and looked up in rag_api_keys
    (which returns only ENABLED keys), so a disabled/unknown key both resolve to
    None — no oracle distinguishing them.
    """
    settings = get_settings().rag
    if settings.mcp_api_key and plaintext == settings.mcp_api_key:
        return {
            RAGApiKeyKeys.KEY_ID: _INTERNAL_BEARER_KEY_ID,
            RAGApiKeyKeys.OWNER: "mcp-internal",
            RAGApiKeyKeys.SCOPES: [str(RAGApiKeyScope.FULL)],
        }
    db = await get_database()
    return await RAGApiKeysRepository(db).find_by_hash(hash_api_key(plaintext))


class ConsumerKeyAuthMiddleware:
    """ASGI middleware: authenticate the MCP bearer and set the request auth context.

    Applied to the FastMCP Streamable HTTP Starlette app. Rejects
    unauthenticated/invalid requests with a flat 401. On success it stashes the
    resolved key record in the ContextVar so the tool wrappers can enforce scope
    per invocation. The tool task is started from within this request's ASGI
    call (anyio copies the current context), so the record set here is what the
    tool sees.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        plaintext = _extract_bearer(request.headers.get("authorization"))
        if not plaintext:
            # Keyless lane (BYOA): no bearer at all — and also an EMPTY bearer
            # ("Authorization: Bearer " from an unset ${LANGRAG_MCP_API_KEY}
            # expansion), which _extract_bearer parses to falsy. A PRESENT but
            # invalid bearer never lands here: it must 401 below, not silently
            # downgrade to the anonymous tier (revocation semantics).
            if get_settings().rag.mcp_anonymous_enabled:
                anon_record = build_anonymous_record(resolve_client_ip(request))
                token = _current_key_record.set(_stamp(anon_record))
                try:
                    await self.app(scope, receive, send)
                finally:
                    _current_key_record.reset(token)
                return
            await self._reject(scope, receive, send)
            return

        try:
            record = await resolve_key_record(plaintext)
        except Exception as e:  # noqa: BLE001 — auth failure must not 500-leak
            logger.error("MCP key resolution failed", extra={"event": "mcp_auth_error", "error": str(e)})
            await self._reject(scope, receive, send)
            return

        if record is None:
            logger.warning("MCP request rejected: unknown or disabled key", extra={"event": "mcp_auth_rejected"})
            await self._reject(scope, receive, send)
            return

        token = _current_key_record.set(_stamp(record))
        try:
            await self.app(scope, receive, send)
        finally:
            _current_key_record.reset(token)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"detail": _UNAUTHORIZED_MESSAGE}, status_code=HTTP_STATUS_UNAUTHORIZED)
        await response(scope, receive, send)
