"""
Single-use verification tokens for the public podcast-MCP key issuance flow.

A verification token is a bearer secret handed to a would-be consumer via email;
possession of it is what authorizes minting a PODCAST_QUERY-scoped API key. It is
therefore treated exactly like an API key at rest: only its HMAC-SHA-256 hash
(with the server pepper) is stored, never the plaintext. Reusing `hash_api_key`
keeps a single hashing definition and the same fail-fast pepper requirement.
"""

import logging
import secrets

from constants import RAG_API_KEY_PREFIX
from rag.auth.hashing import constant_time_equal, hash_api_key

logger = logging.getLogger(__name__)

# Length (in bytes of entropy) of a generated verification token. 32 bytes of
# url-safe randomness is unguessable; the prefix is only for log/debug triage.
_TOKEN_ENTROPY_BYTES = 32
_CONSUMER_TOKEN_PREFIX = f"{RAG_API_KEY_PREFIX}vt_"


def generate_verification_token() -> str:
    """Return a fresh, opaque, single-use verification token (plaintext).

    The plaintext is emailed to the requester and never persisted; only its hash
    is stored (see `hash_verification_token`).
    """
    return f"{_CONSUMER_TOKEN_PREFIX}{secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)}"


def hash_verification_token(plaintext: str) -> str:
    """Return the HMAC-SHA-256(pepper, token) hex digest stored at rest."""
    return hash_api_key(plaintext)


def verify_token_matches(plaintext: str, stored_hash: str) -> bool:
    """Constant-time check that a presented token hashes to the stored hash."""
    return constant_time_equal(hash_verification_token(plaintext), stored_hash)
