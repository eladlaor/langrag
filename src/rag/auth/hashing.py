"""
API key hashing.

Keys are hashed with HMAC-SHA-256 using a server-side pepper from config so a
DB-only compromise cannot be replayed without the pepper. Pepper is required
when authentication is enabled — fail-fast if it's missing.
"""

import hashlib
import hmac
import logging

from config import get_settings

logger = logging.getLogger(__name__)


def hash_api_key(plaintext: str) -> str:
    """Return the hex digest of HMAC-SHA-256(pepper, plaintext)."""
    pepper = get_settings().rag.api_key_pepper
    if not pepper:
        raise RuntimeError(
            "RAG_API_KEY_PEPPER is not configured. Set it in the environment before "
            "issuing or validating API keys."
        )
    digest = hmac.new(
        key=pepper.encode("utf-8"),
        msg=plaintext.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest


def constant_time_equal(a: str, b: str) -> bool:
    """Constant-time string compare to avoid timing oracles on auth checks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
