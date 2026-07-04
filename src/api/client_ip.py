"""
Shared real-client-IP resolution behind trusted proxies.

Used by both the FastAPI app (:8000, via slowapi per-IP rate limiting) and the
MCP server process (:8765, via the anonymous-principal quota lane). Kept free of
slowapi imports so the MCP process does not grow that dependency.
"""

import logging

from starlette.requests import Request

from config import get_settings
from constants import HEADER_CF_CONNECTING_IP, HEADER_X_FORWARDED_FOR

logger = logging.getLogger(__name__)

# Fallback identity when the ASGI transport exposes no client tuple at all
# (e.g. in-process test clients). Never None so quota keys stay well-formed.
UNKNOWN_CLIENT_IP = "unknown"


def resolve_client_ip(request: Request) -> str:
    """Resolve the real client IP for per-IP limiting behind proxies.

    Behind nginx/Cloudflare the raw TCP peer is the PROXY's IP, so a per-IP
    limit collapses to one global bucket; and a raw X-Forwarded-For is
    client-spoofable. Resolution order (config-driven, see APISettings):

      1. If Cloudflare is authoritative (cloudflare_authoritative=True), trust
         the CF-Connecting-IP header. Cloudflare strips a client-supplied one,
         so this is safe ONLY when Cloudflare is the sole ingress.
      2. Else, if the immediate TCP peer is in the trusted-proxy allowlist
         (trusted_proxy_ips), use the LEFTMOST X-Forwarded-For entry (the
         original client the trusted proxy recorded).
      3. Else (dev / no proxy / untrusted peer) use the raw peer address — an
         untrusted or absent XFF is never honored, so it cannot be spoofed.

    Works for both fastapi.Request and starlette.requests.Request (the former
    subclasses the latter).
    """
    try:
        settings = get_settings().api
        peer = request.client.host if request.client else UNKNOWN_CLIENT_IP

        if settings.cloudflare_authoritative:
            cf_ip = request.headers.get(HEADER_CF_CONNECTING_IP)
            if cf_ip and cf_ip.strip():
                return cf_ip.strip()

        if peer in set(settings.trusted_proxy_ips):
            xff = request.headers.get(HEADER_X_FORWARDED_FOR, "")
            leftmost = xff.split(",", 1)[0].strip() if xff else ""
            if leftmost:
                return leftmost

        return peer
    except Exception as e:
        logger.error(f"resolve_client_ip failed: {e}", extra={"error": str(e)})
        raise
