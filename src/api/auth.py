"""
Individual-user-account UI login gate (per-user Fernet session cookie).

This is a SEPARATE auth surface from the public RAG API keys (RAG_API_KEY_*).
Each user has an email + argon2id password; a successful login issues a Fernet
session cookie carrying only opaque claims (user_id, role, revocation epoch).

1. POST /api/auth/login   -> verify email+password, set session cookie
2. POST /api/auth/logout  -> clear session cookie
3. GET  /api/auth/session -> 200 with email+role if the session is valid, else 401

The cookie is a Fernet token (AES-128-CBC + HMAC-SHA256 + embedded timestamp),
NOT a JWT. Fernet gives authenticated encryption AND server-side TTL enforcement
without an external dependency or a server-side session store. The password is
never written to the cookie, never logged, and never returned to the client.

Server-side revocation: each user document carries a `session_epoch`. A cookie
embeds the epoch at issue time; if the stored epoch advances (password reset,
disable), every previously-issued cookie stops validating.

`require_session` returns the resolved `CurrentUser` and is the FastAPI
dependency attached to every UI data router. `require_admin` layers an ADMIN
role check on top for the user-management surface.
"""

import hmac

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pymongo.errors import DuplicateKeyError

from config import get_settings
from constants import (
    HTTP_STATUS_CONFLICT,
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_UNAUTHORIZED,
    ROUTE_AUTH_ACCESS_REQUESTS,
    ROUTE_AUTH_CONFIG,
    ROUTE_AUTH_LOGIN,
    ROUTE_AUTH_LOGOUT,
    ROUTE_AUTH_SESSION,
    ROUTE_AUTH_SIGNUP,
    INTERNAL_API_KEY_HEADER,
    ROUTE_ROOT,
    SERVICE_PRINCIPAL_SUBJECT,
    SESSION_COOKIE_NAME,
    SESSION_SUBJECT_VALUE,
    SIGNUP_CODE_NOT_ALLOWLISTED,
)
from custom_types.api_schemas import (
    AccessRequestAck,
    AccessRequestCreate,
    AuthConfigResponse,
    CurrentUser,
    LoginRequest,
    SessionResponse,
    SignupRequest,
)
from custom_types.db_schemas import AuthProvider, UserRole
from custom_types.field_keys import UserKeys
from api.session_token import (
    SessionDecodeError,
    decode_session,
)
from api.signup_common import (
    ACCESS_REQUEST_ACK_MESSAGE,
    DUPLICATE_ACCOUNT_MESSAGE,
    NOT_ALLOWLISTED_MESSAGE,
    SIGNUP_DISABLED_MESSAGE,
    is_email_allowlisted,
    issue_session_cookie,
)
from api.rate_limiting import RATE_ACCESS_REQUEST, RATE_LOGIN, RATE_SIGNUP, limiter
from db.connection import get_database
from db.repositories.access_requests import AccessRequestsRepository
from db.repositories.users import UsersRepository
from observability.app import get_logger
from rag.auth.passwords import hash_password, verify_password

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["auth"])

# Generic message returned for any login failure so an attacker cannot
# distinguish "no such email" from "wrong password" from "disabled account".
_INVALID_CREDENTIALS_MESSAGE = "Invalid credentials"
_NOT_AUTHENTICATED_MESSAGE = "Not authenticated"
_ADMIN_REQUIRED_MESSAGE = "Admin privileges required"

# Real argon2id hash of a throwaway password, computed once at import. When
# login is attempted for an unknown / disabled / passwordless account we run a
# genuine verify against this so the response time does not reveal whether the
# email exists (anti-enumeration). A fabricated string would be rejected as
# malformed and skip the hashing work, defeating the timing equalization.
_DUMMY_PASSWORD_HASH = hash_password("dummy-anti-enumeration-password")


def _sentinel_dev_user() -> CurrentUser:
    """CurrentUser returned when the login gate is disabled (dev convenience).

    Grants ADMIN so local development with the gate off is not blocked by the
    admin-only routes.
    """
    return CurrentUser(
        user_id=SESSION_SUBJECT_VALUE,
        email=SESSION_SUBJECT_VALUE,
        role=UserRole.ADMIN,
        communities=[],
    )


def _service_principal() -> CurrentUser:
    """CurrentUser returned for an authenticated internal service caller.

    Resolved only when the login gate is enabled AND a non-empty internal API
    key is configured AND the request presents that exact key in the
    X-Internal-Key header. Grants ADMIN so headless automation can reach the
    same session-gated routes a UI admin can, without forging a session cookie
    or holding a DB-backed account. Distinguished from the dev sentinel by its
    SERVICE_PRINCIPAL_SUBJECT identity so it is unambiguous in logs/audits.
    """
    return CurrentUser(
        user_id=SERVICE_PRINCIPAL_SUBJECT,
        email=SERVICE_PRINCIPAL_SUBJECT,
        role=UserRole.ADMIN,
        communities=[],
    )


@router.post(ROUTE_AUTH_LOGIN, response_model=SessionResponse)
@limiter.limit(RATE_LOGIN)
async def login(request: Request, body: LoginRequest, response: Response) -> SessionResponse:
    """Verify email+password and, on success, issue a session cookie.

    On any failure returns 401 with a generic message and logs a warning WITHOUT
    the attempted password. Runs a dummy verify on the no-such-user path to keep
    the timing uniform (anti email-enumeration). Rate-limited (RATE_LOGIN) to
    throttle brute force and cap argon2 CPU/DoS amplification; `request: Request`
    is required by slowapi's limiter and is otherwise unused here.
    """
    try:
        settings = get_settings()

        if not settings.login.enabled:
            sentinel = _sentinel_dev_user()
            return SessionResponse(authenticated=True, email=sentinel.email, role=sentinel.role)

        email = str(body.email)
        db = await get_database()
        repo = UsersRepository(db)
        user = await repo.find_by_email(email)

        password_hash = user.get(UserKeys.PASSWORD_HASH) if user else None
        is_disabled = bool(user.get(UserKeys.DISABLED)) if user else False

        if user is None or password_hash is None or is_disabled:
            # Spend the same work as a real verify so timing does not leak which
            # branch failed. The result is intentionally discarded.
            verify_password(body.password, _DUMMY_PASSWORD_HASH)
            logger.warning(
                "Login failed",
                extra={"event": "login_failed", "function": "login", "reason": "unknown_disabled_or_passwordless"},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_MESSAGE)

        if not verify_password(body.password, password_hash):
            logger.warning(
                "Login failed",
                extra={"event": "login_failed", "function": "login", "reason": "wrong_password", "user_id": user[UserKeys.USER_ID]},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_MESSAGE)

        user_id = user[UserKeys.USER_ID]
        role = UserRole(user[UserKeys.ROLE])
        epoch = int(user.get(UserKeys.SESSION_EPOCH, 0))

        await repo.touch_last_seen(user_id)
        issue_session_cookie(response, user_id=user_id, role=role, epoch=epoch, settings=settings)
        logger.info(
            "Login succeeded; session cookie issued",
            extra={"event": "login_succeeded", "function": "login", "user_id": user_id, "role": str(role)},
        )
        return SessionResponse(authenticated=True, email=user[UserKeys.EMAIL], role=role)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during login",
            extra={"event": "login_error", "function": "login", "error": str(e)},
        )
        raise


@router.post(ROUTE_AUTH_SIGNUP, response_model=SessionResponse)
@limiter.limit(RATE_SIGNUP)
async def signup(request: Request, body: SignupRequest, response: Response) -> SessionResponse:
    """Email+password self-signup. Always creates a VIEWER with no communities.

    Flow: signup-disabled -> 403; not on allowlist -> structured 403 carrying
    the machine-readable not_allowlisted code; otherwise create the account
    (VIEWER-only, enforced by the repo), issue a session cookie, and return the
    session response. A duplicate email is a documented anti-enumeration
    tradeoff inherent to self-serve signup -> 409 with a generic message.
    """
    email = str(body.email)
    try:
        settings = get_settings()

        if not settings.signup.enabled:
            logger.warning(
                "Signup rejected: signup disabled",
                extra={"event": "signup_disabled", "function": "signup"},
            )
            raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=SIGNUP_DISABLED_MESSAGE)

        if not is_email_allowlisted(email, settings):
            logger.warning(
                "Signup rejected: email not on allowlist",
                extra={"event": "signup_not_allowlisted", "function": "signup"},
            )
            raise HTTPException(
                status_code=HTTP_STATUS_FORBIDDEN,
                detail={"message": NOT_ALLOWLISTED_MESSAGE, "code": SIGNUP_CODE_NOT_ALLOWLISTED},
            )

        repo = UsersRepository(await get_database())
        try:
            user_id = await repo.create_self_signup_user(
                email=email,
                auth_provider=AuthProvider.PASSWORD,
                password_hash=hash_password(body.password),
            )
        except DuplicateKeyError:
            logger.warning(
                "Signup rejected: duplicate email",
                extra={"event": "signup_duplicate", "function": "signup"},
            )
            raise HTTPException(status_code=HTTP_STATUS_CONFLICT, detail=DUPLICATE_ACCOUNT_MESSAGE)

        user = await repo.find_by_user_id(user_id)
        role = UserRole(user[UserKeys.ROLE])
        epoch = int(user.get(UserKeys.SESSION_EPOCH, 0))

        await repo.touch_last_seen(user_id)
        issue_session_cookie(response, user_id=user_id, role=role, epoch=epoch, settings=settings)
        logger.info(
            "Signup succeeded; session cookie issued",
            extra={"event": "signup_succeeded", "function": "signup", "user_id": user_id, "role": str(role)},
        )
        return SessionResponse(authenticated=True, email=user[UserKeys.EMAIL], role=role)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during signup",
            extra={"event": "signup_error", "function": "signup", "error": str(e)},
        )
        raise


@router.post(ROUTE_AUTH_ACCESS_REQUESTS, response_model=AccessRequestAck)
@limiter.limit(RATE_ACCESS_REQUEST)
async def create_access_request(request: Request, body: AccessRequestCreate) -> AccessRequestAck:
    """Public contact form for users who are not on the allowlist.

    Persists the request for admin review and returns a generic acknowledgement
    that is identical for new and duplicate submissions (anti-enumeration: the
    caller cannot learn whether the email is already known).
    """
    try:
        repo = AccessRequestsRepository(await get_database())
        request_id = await repo.create_request(
            email=str(body.email),
            name=body.name,
            message=body.message,
        )
        logger.info(
            "Access request submitted",
            extra={"event": "access_request_submitted", "function": "create_access_request", "request_id": request_id},
        )
        return AccessRequestAck(received=True, message=ACCESS_REQUEST_ACK_MESSAGE)
    except Exception as e:
        logger.error(
            "Unexpected error creating access request",
            extra={"event": "access_request_error", "function": "create_access_request", "error": str(e)},
        )
        raise


@router.get(ROUTE_AUTH_CONFIG, response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    """Public booleans driving which auth options the SPA renders."""
    try:
        settings = get_settings()
        return AuthConfigResponse(
            google_enabled=settings.google.enabled,
            signup_enabled=settings.signup.enabled,
        )
    except Exception as e:
        logger.error(
            "Unexpected error reading auth config",
            extra={"event": "auth_config_error", "function": "auth_config", "error": str(e)},
        )
        raise


@router.post(ROUTE_AUTH_LOGOUT, response_model=SessionResponse)
async def logout(response: Response) -> SessionResponse:
    """Clear the session cookie (same attributes as when it was set)."""
    try:
        settings = get_settings()
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path=ROUTE_ROOT,
            httponly=True,
            secure=settings.login.cookie_secure,
            samesite=str(settings.login.cookie_samesite),
        )
        logger.info("Logout: session cookie cleared", extra={"event": "logout", "function": "logout"})
        return SessionResponse(authenticated=False)
    except Exception as e:
        logger.error(
            "Unexpected error during logout",
            extra={"event": "logout_error", "function": "logout", "error": str(e)},
        )
        raise


async def require_session(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    internal_key: str | None = Header(default=None, alias=INTERNAL_API_KEY_HEADER),
) -> CurrentUser:
    """FastAPI dependency: resolve the authenticated user from the cookie.

    Decodes the Fernet token (TTL-enforced), loads the user, and rejects when
    the user is missing, disabled, or the token epoch is stale relative to the
    stored epoch. Returns a CurrentUser on success; raises 401 on any failure.
    When the gate is disabled, returns a sentinel ADMIN user so dev is unblocked.

    Internal service path: when the gate is enabled, a non-empty internal API
    key is configured, and the request presents that exact key in the
    X-Internal-Key header, the call resolves to the admin-equivalent service
    principal (no cookie, no DB lookup). A wrong key is an explicit 401 and does
    NOT fall through to the cookie path. When no key is configured or no header
    is sent, the header path is inert and the cookie path runs unchanged.
    """
    try:
        settings = get_settings()
        if not settings.login.enabled:
            return _sentinel_dev_user()

        configured = settings.login.internal_api_key
        if configured and internal_key is not None:
            if hmac.compare_digest(internal_key, configured):
                logger.info(
                    "Internal service auth accepted",
                    extra={"event": "internal_auth_ok", "function": "require_session"},
                )
                return _service_principal()
            logger.warning(
                "Internal service auth rejected: key mismatch",
                extra={"event": "internal_auth_failed", "function": "require_session"},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_NOT_AUTHENTICATED_MESSAGE)

        if not session_cookie:
            logger.warning(
                "Session check failed: cookie missing",
                extra={"event": "session_missing", "function": "require_session"},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_NOT_AUTHENTICATED_MESSAGE)

        try:
            payload = decode_session(session_cookie)
        except SessionDecodeError:
            logger.warning(
                "Session check failed: invalid or expired token",
                extra={"event": "session_invalid", "function": "require_session"},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_NOT_AUTHENTICATED_MESSAGE)

        db = await get_database()
        repo = UsersRepository(db)
        user = await repo.find_by_user_id(payload.sub)

        if user is None or bool(user.get(UserKeys.DISABLED)):
            logger.warning(
                "Session check failed: user missing or disabled",
                extra={"event": "session_user_invalid", "function": "require_session", "user_id": payload.sub},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_NOT_AUTHENTICATED_MESSAGE)

        if int(user.get(UserKeys.SESSION_EPOCH, 0)) != payload.epoch:
            logger.warning(
                "Session check failed: revoked session (epoch mismatch)",
                extra={"event": "session_revoked", "function": "require_session", "user_id": payload.sub},
            )
            raise HTTPException(status_code=HTTP_STATUS_UNAUTHORIZED, detail=_NOT_AUTHENTICATED_MESSAGE)

        return CurrentUser(
            user_id=user[UserKeys.USER_ID],
            email=user[UserKeys.EMAIL],
            role=UserRole(user[UserKeys.ROLE]),
            communities=list(user.get(UserKeys.COMMUNITIES, [])),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected error verifying session",
            extra={"event": "session_error", "function": "require_session", "error": str(e)},
        )
        raise


async def require_admin(current: CurrentUser = Depends(require_session)) -> CurrentUser:
    """FastAPI dependency: require an ADMIN role on top of a valid session."""
    if current.role != UserRole.ADMIN:
        logger.warning(
            "Admin-only access denied",
            extra={"event": "admin_required", "function": "require_admin", "user_id": current.user_id, "role": str(current.role)},
        )
        raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_ADMIN_REQUIRED_MESSAGE)
    return current


@router.get(ROUTE_AUTH_SESSION, response_model=SessionResponse)
async def session(current: CurrentUser = Depends(require_session)) -> SessionResponse:
    """Return 200 with the authenticated user's email + role when valid."""
    return SessionResponse(authenticated=True, email=current.email, role=current.role)
