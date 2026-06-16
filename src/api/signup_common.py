"""
Shared helpers for the self-signup auth surface.

`is_email_allowlisted` is the single chokepoint deciding whether an email may
self-register; encapsulating it here lets the allowlist storage swap from a
config list to a collection later without touching call sites.

`issue_session_cookie` is the one definition of the session-cookie attributes,
extracted from `login()` so login, email/password signup, and the Google
callback all set a byte-identical cookie (so `require_session` is unchanged).
"""

from fastapi import Response

from config import Settings
from constants import ROUTE_ROOT, SESSION_COOKIE_NAME
from custom_types.db_schemas import UserRole
from db.repositories.users import normalize_email
from api.session_token import encode_session, session_ttl_seconds
from observability.app import get_logger

logger = get_logger(__name__)

# User-facing messages mirroring api.auth._INVALID_CREDENTIALS_MESSAGE.
SIGNUP_DISABLED_MESSAGE = "Self-signup is currently disabled"
NOT_ALLOWLISTED_MESSAGE = "This email is not on the access allowlist"
DUPLICATE_ACCOUNT_MESSAGE = "An account with that email already exists"
ACCESS_REQUEST_ACK_MESSAGE = "Your request has been received and will be reviewed"


def is_email_allowlisted(email: str, settings: Settings) -> bool:
    """Return True if `email` is on the self-signup allowlist.

    Normalizes both the candidate and every configured entry through the same
    canonicalization the users repo uses, so the comparison is case- and
    whitespace-insensitive.
    """
    candidate = normalize_email(email)
    allowed = {normalize_email(entry) for entry in settings.signup.allowlist}
    return candidate in allowed


def issue_session_cookie(response: Response, *, user_id: str, role: UserRole, epoch: int, settings: Settings) -> None:
    """Set the Fernet session cookie on `response`.

    This is the single source of truth for the session-cookie attributes;
    login, signup, and the Google callback all call it so the issued cookie is
    identical across every auth path.
    """
    token = encode_session(user_id=user_id, role=role, epoch=epoch)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=settings.login.cookie_secure,
        samesite=str(settings.login.cookie_samesite),
        path=ROUTE_ROOT,
    )


def normalized_signup_email(email: str) -> str:
    """Canonicalize a signup email for storage and comparison."""
    return normalize_email(email)
