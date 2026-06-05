"""
Fernet session-token encode/decode helpers for individual-user sessions.

Extracted from the FastAPI auth router so the crypto and the claim shape are
unit-testable without spinning up FastAPI. The cookie is a Fernet token
(AES-128-CBC + HMAC-SHA256 + embedded timestamp), NOT a JWT: Fernet gives
authenticated encryption AND server-side TTL enforcement with no external
dependency and no server-side session store.

The payload carries only opaque claims (user_id, role, revocation epoch); no
password or hash is ever written to the cookie.
"""

import json

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings
from constants import (
    ENV_LOGIN_SESSION_KEY,
    SESSION_EPOCH_CLAIM,
    SESSION_ROLE_CLAIM,
    SESSION_SUBJECT_CLAIM,
)
from custom_types.db_schemas import UserRole
from custom_types.api_schemas import SessionPayload
from observability.app import get_logger

logger = get_logger(__name__)


class SessionDecodeError(Exception):
    """Raised when a session token is missing, tampered, expired, or malformed."""


def get_fernet() -> Fernet:
    """Build the Fernet instance from the configured session key.

    Fails fast with RuntimeError if the key is empty, mirroring the
    hash_api_key pepper check.
    """
    try:
        session_key = get_settings().login.session_key
        if not session_key:
            raise RuntimeError(
                f"{ENV_LOGIN_SESSION_KEY} is not configured. Generate one with "
                "Fernet.generate_key() and set it in the environment before "
                "enabling the login gate."
            )
        return Fernet(session_key.encode("utf-8"))
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(
            "Failed to construct Fernet from session key",
            extra={"event": "fernet_init_failed", "function": "get_fernet", "error": str(e)},
        )
        raise RuntimeError(f"get_fernet failed: invalid {ENV_LOGIN_SESSION_KEY}") from e


def session_ttl_seconds() -> int:
    """Session lifetime in seconds, derived from the configured minutes."""
    return get_settings().login.session_ttl_minutes * 60


def encode_session(user_id: str, role: UserRole, epoch: int) -> str:
    """Encrypt a session payload into a Fernet token string.

    Args:
        user_id: Authenticated user_id (becomes the subject claim).
        role: User role captured at issue time.
        epoch: User revocation epoch captured at issue time.

    Returns:
        The Fernet token as a string suitable for a cookie value.
    """
    try:
        payload = {
            SESSION_SUBJECT_CLAIM: user_id,
            SESSION_ROLE_CLAIM: str(role),
            SESSION_EPOCH_CLAIM: epoch,
        }
        fernet = get_fernet()
        return fernet.encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(
            "Failed to encode session token",
            extra={"event": "session_encode_failed", "function": "encode_session", "user_id": user_id, "error": str(e)},
        )
        raise


def decode_session(token: str) -> SessionPayload:
    """Decrypt and validate a Fernet session token with TTL enforcement.

    Args:
        token: The cookie value to decode.

    Returns:
        A validated SessionPayload.

    Raises:
        SessionDecodeError: if the token is missing, tampered, expired, or its
            decrypted payload does not match the expected claim shape.
    """
    if not token:
        raise SessionDecodeError("session token missing")
    try:
        fernet = get_fernet()
        try:
            decrypted = fernet.decrypt(token.encode("utf-8"), ttl=session_ttl_seconds())
        except InvalidToken as e:
            raise SessionDecodeError("invalid or expired session token") from e

        raw = json.loads(decrypted.decode("utf-8"))
        return SessionPayload(
            sub=raw[SESSION_SUBJECT_CLAIM],
            role=raw[SESSION_ROLE_CLAIM],
            epoch=raw[SESSION_EPOCH_CLAIM],
        )
    except SessionDecodeError:
        raise
    except Exception as e:
        logger.warning(
            "Session token failed to decode into a valid payload",
            extra={"event": "session_decode_failed", "function": "decode_session", "error": str(e)},
        )
        raise SessionDecodeError("malformed session payload") from e
