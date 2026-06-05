"""
Password hashing for individual user accounts (argon2id).

Separate from `rag.auth.hashing` (which HMAC-hashes API keys with a server-side
pepper). User passwords are low-entropy human secrets, so they need a slow,
memory-hard KDF (argon2id) with a per-hash random salt embedded in the PHC
string. There is no shared pepper here: the salt lives in the stored hash.

The PasswordHasher is a module-level singleton so its tuned argon2 parameters
(time/memory/parallelism) are defined once and reused for every verify, which
is what lets `password_needs_rehash` detect parameter drift later.
"""

import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

logger = logging.getLogger(__name__)

# argon2id with library defaults (sane, modern parameters). Tuning the cost here
# later automatically makes `password_needs_rehash` flag pre-tuning hashes.
_password_hasher = PasswordHasher()


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password into an argon2id PHC string (salt embedded).

    Args:
        plaintext: The user-supplied password.

    Returns:
        The PHC-format hash string suitable for storage.
    """
    try:
        return _password_hasher.hash(plaintext)
    except Exception as e:
        logger.error(
            "Failed to hash password",
            extra={"event": "password_hash_failed", "function": "hash_password", "error": str(e)},
        )
        raise


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored argon2id hash.

    Never raises: a mismatch, a malformed hash, or an empty hash all return
    False. This keeps the login path branchless on the caller side and avoids
    leaking, via exception vs boolean, whether the stored hash was malformed.

    Args:
        plaintext: The candidate password.
        stored_hash: The stored PHC hash string.

    Returns:
        True only when the password matches the stored hash.
    """
    if not stored_hash:
        return False
    try:
        return _password_hasher.verify(stored_hash, plaintext)
    except VerifyMismatchError:
        return False
    except InvalidHashError as e:
        logger.warning(
            "verify_password called with a malformed stored hash",
            extra={"event": "password_verify_invalid_hash", "function": "verify_password", "error": str(e)},
        )
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    """Return True when a stored hash should be re-computed at next login.

    True when argon2 parameters have changed since the hash was created, or when
    the stored value is not a valid argon2 hash (so the caller upgrades it).

    Args:
        stored_hash: The stored PHC hash string.

    Returns:
        True if the hash should be regenerated.
    """
    if not stored_hash:
        return True
    try:
        return _password_hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
