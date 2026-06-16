"""
Google OAuth2 / OIDC sign-in routes for the individual-account auth surface.

This adds "Sign in with Google" on top of the email+password login/signup in
`api.auth`. Authlib owns the OAuth dance: `authorize_redirect` stashes a `state`
+ `nonce` in the transient Starlette session (signed by SessionMiddleware, keyed
on `signup.oauth_state_secret`) and `authorize_access_token` validates them plus
the returned `id_token` signature/iss/aud/exp/nonce. We never do a manual token
exchange, so CSRF + replay are handled by the library.

Account resolution on the callback mirrors the email+password rules and the
VIEWER-only invariant: a brand-new identity is created through
`create_self_signup_user` (which structurally cannot mint an ADMIN), and only
after the allowlist check passes. On success we set the IDENTICAL Fernet cookie
as login/signup via the shared `issue_session_cookie`, then 302 the browser to
the validated `next` (or root) — a top-level navigation, not a JSON response.
"""

from urllib.parse import urlencode, urlsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from pymongo.errors import DuplicateKeyError
from starlette.responses import RedirectResponse

from config import Settings, get_settings
from constants import (
    GOOGLE_CLAIM_EMAIL,
    GOOGLE_CLAIM_EMAIL_VERIFIED,
    GOOGLE_CLAIM_SUB,
    GOOGLE_OAUTH_CLIENT_NAME,
    GOOGLE_OAUTH_SCOPE,
    GOOGLE_OIDC_DISCOVERY_URL,
    GOOGLE_TOKEN_USERINFO_KEY,
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_FOUND,
    HTTP_STATUS_NOT_FOUND,
    OAUTH_SESSION_NEXT_KEY,
    QUERY_PARAM_EMAIL,
    QUERY_PARAM_NEXT,
    QUERY_PARAM_SIGNUP,
    ROUTE_AUTH_GOOGLE_CALLBACK,
    ROUTE_AUTH_GOOGLE_LOGIN,
    ROUTE_ROOT,
    SIGNUP_STATUS_REJECTED,
)
from custom_types.db_schemas import AuthProvider, UserRole
from custom_types.field_keys import UserKeys
from db.connection import get_database
from db.repositories.users import UsersRepository
from observability.app import get_logger
from api.signup_common import is_email_allowlisted, issue_session_cookie

logger = get_logger(__name__)

# Generic messages mirroring api.auth's anti-enumeration style. The Google path
# fails closed: a redirect/OIDC error never reveals account existence.
_GOOGLE_DISABLED_MESSAGE = "Google sign-in is not enabled"
_GOOGLE_EMAIL_UNVERIFIED_MESSAGE = "Google account email is not verified"
_GOOGLE_ACCOUNT_DISABLED_MESSAGE = "This account is disabled"
_GOOGLE_SUB_CONFLICT_MESSAGE = "This Google identity cannot be linked to the account"
_GOOGLE_USERINFO_MISSING_MESSAGE = "Google sign-in did not return the required profile claims"

# Module-level Authlib registry. Registered once at startup (register_google),
# read on every login/callback. Kept module-global because the OAuth client
# carries the cached OIDC server metadata across requests.
_oauth = OAuth()
_google_registered = False


def register_google(settings: Settings) -> None:
    """Register the Authlib "google" client. Idempotent; gated on enabled.

    Called once at startup from main.py. Derives the authorize/token/jwks
    endpoints from Google's OIDC discovery document so we never hardcode them.
    """
    global _google_registered
    try:
        if not settings.google.enabled:
            logger.info(
                "Google OAuth disabled; client not registered",
                extra={"event": "google_oauth_disabled", "function": "register_google"},
            )
            return
        if _google_registered:
            return
        _oauth.register(
            name=GOOGLE_OAUTH_CLIENT_NAME,
            server_metadata_url=GOOGLE_OIDC_DISCOVERY_URL,
            client_id=settings.google.client_id,
            client_secret=settings.google.client_secret,
            client_kwargs={"scope": GOOGLE_OAUTH_SCOPE},
        )
        _google_registered = True
        logger.info(
            "Google OAuth client registered",
            extra={"event": "google_oauth_registered", "function": "register_google"},
        )
    except Exception as e:
        logger.error(
            "Failed to register Google OAuth client",
            extra={"event": "google_oauth_register_error", "function": "register_google", "error": str(e)},
        )
        raise


def _validated_next(next_value: str | None) -> str:
    """Return a safe post-login redirect target.

    Open-redirect prevention: only a RELATIVE same-origin path is accepted — it
    must start with a single "/", must not start with "//" (protocol-relative),
    and must carry no scheme or netloc. Anything else falls back to root.
    """
    if not next_value:
        return ROUTE_ROOT
    if not next_value.startswith(ROUTE_ROOT) or next_value.startswith("//"):
        return ROUTE_ROOT
    split = urlsplit(next_value)
    if split.scheme or split.netloc:
        return ROUTE_ROOT
    return next_value


def _rejection_redirect(email: str) -> RedirectResponse:
    """302 to the SPA invite-only rejection screen with the email prefilled.

    No session cookie is set: a brand-new, non-allowlisted identity is not an
    account. The email is URL-encoded so addresses with reserved characters
    round-trip intact.
    """
    query = urlencode({QUERY_PARAM_SIGNUP: SIGNUP_STATUS_REJECTED, QUERY_PARAM_EMAIL: email})
    return RedirectResponse(url=f"{ROUTE_ROOT}?{query}", status_code=HTTP_STATUS_FOUND)


router = APIRouter(prefix="", tags=["auth-google"])


@router.get(ROUTE_AUTH_GOOGLE_LOGIN)
async def google_login(request: Request):
    """Kick off the Google OAuth redirect.

    404 when Google is disabled (the route is always mounted so it is trivially
    testable, but it is inert unless configured). An optional `?next=` is
    validated as a relative same-origin path and stashed in the transient
    Starlette session for the callback; an unsafe value silently falls back to
    root. The state+nonce are stored by Authlib in the same session.
    """
    try:
        settings = get_settings()
        if not settings.google.enabled:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_GOOGLE_DISABLED_MESSAGE)

        next_path = _validated_next(request.query_params.get(QUERY_PARAM_NEXT))
        request.session[OAUTH_SESSION_NEXT_KEY] = next_path

        client = _oauth.create_client(GOOGLE_OAUTH_CLIENT_NAME)
        logger.info(
            "Google login: issuing authorize redirect",
            extra={"event": "google_login_redirect", "function": "google_login"},
        )
        return await client.authorize_redirect(request, settings.google.redirect_uri)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected error starting Google login",
            extra={"event": "google_login_error", "function": "google_login", "error": str(e)},
        )
        raise


@router.get(ROUTE_AUTH_GOOGLE_CALLBACK)
async def google_callback(request: Request):
    """Complete the Google OAuth dance and establish a session.

    Authlib validates state+nonce+id_token inside authorize_access_token. We
    reject an unverified email outright, then resolve the account by google_sub
    (login), else by email (link to an existing password account, or reject a
    conflicting sub), else create a brand-new VIEWER only if allowlisted (a
    non-allowlisted brand-new identity is redirected to the rejection screen
    with NO cookie). A disabled account is rejected like the login path. On
    success we set the standard Fernet cookie and 302 to the validated next.
    """
    try:
        settings = get_settings()
        if not settings.google.enabled:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_GOOGLE_DISABLED_MESSAGE)

        client = _oauth.create_client(GOOGLE_OAUTH_CLIENT_NAME)
        token = await client.authorize_access_token(request)
        userinfo = token.get(GOOGLE_TOKEN_USERINFO_KEY) if token else None
        if not userinfo:
            logger.warning(
                "Google callback: missing userinfo claims",
                extra={"event": "google_callback_no_userinfo", "function": "google_callback"},
            )
            raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_GOOGLE_USERINFO_MISSING_MESSAGE)

        google_sub = userinfo.get(GOOGLE_CLAIM_SUB)
        email = userinfo.get(GOOGLE_CLAIM_EMAIL)
        email_verified = userinfo.get(GOOGLE_CLAIM_EMAIL_VERIFIED)

        if not google_sub or not email:
            logger.warning(
                "Google callback: incomplete userinfo claims",
                extra={"event": "google_callback_incomplete_claims", "function": "google_callback", "has_sub": bool(google_sub), "has_email": bool(email)},
            )
            raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_GOOGLE_USERINFO_MISSING_MESSAGE)

        # Trust the Google email only when Google asserts it is verified.
        if email_verified is not True:
            logger.warning(
                "Google callback rejected: email not verified",
                extra={"event": "google_callback_email_unverified", "function": "google_callback"},
            )
            raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_GOOGLE_EMAIL_UNVERIFIED_MESSAGE)

        repo = UsersRepository(await get_database())
        next_path = _validated_next(request.session.pop(OAUTH_SESSION_NEXT_KEY, None))

        user = await repo.find_by_google_sub(google_sub)
        if user is None:
            existing = await repo.find_by_email(email)
            if existing is not None:
                existing_sub = existing.get(UserKeys.GOOGLE_SUB)
                if existing_sub is None:
                    await repo.link_google_identity(existing[UserKeys.USER_ID], google_sub)
                    user = await repo.find_by_user_id(existing[UserKeys.USER_ID])
                    logger.info(
                        "Google callback: linked Google identity to existing account",
                        extra={"event": "google_link", "function": "google_callback", "user_id": existing[UserKeys.USER_ID]},
                    )
                elif existing_sub != google_sub:
                    logger.warning(
                        "Google callback rejected: email bound to a different Google sub",
                        extra={"event": "google_callback_sub_conflict", "function": "google_callback", "user_id": existing[UserKeys.USER_ID]},
                    )
                    raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_GOOGLE_SUB_CONFLICT_MESSAGE)
                else:
                    user = existing
            else:
                # Brand-new identity: allowlist gate BEFORE creating the account.
                if not is_email_allowlisted(email, settings):
                    logger.warning(
                        "Google callback: brand-new identity not on allowlist; redirecting to rejection screen",
                        extra={"event": "google_callback_not_allowlisted", "function": "google_callback"},
                    )
                    return _rejection_redirect(email)
                try:
                    user_id = await repo.create_self_signup_user(
                        email=email,
                        auth_provider=AuthProvider.GOOGLE,
                        google_sub=google_sub,
                    )
                except DuplicateKeyError:
                    # Concurrent create or a sub already bound elsewhere.
                    logger.warning(
                        "Google callback: duplicate key creating self-signup user",
                        extra={"event": "google_callback_duplicate", "function": "google_callback"},
                    )
                    raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_GOOGLE_SUB_CONFLICT_MESSAGE)
                user = await repo.find_by_user_id(user_id)
                logger.info(
                    "Google callback: created new VIEWER via Google",
                    extra={"event": "google_signup_created", "function": "google_callback", "user_id": user_id},
                )

        if bool(user.get(UserKeys.DISABLED)):
            logger.warning(
                "Google callback rejected: account disabled",
                extra={"event": "google_callback_disabled", "function": "google_callback", "user_id": user[UserKeys.USER_ID]},
            )
            raise HTTPException(status_code=HTTP_STATUS_FORBIDDEN, detail=_GOOGLE_ACCOUNT_DISABLED_MESSAGE)

        user_id = user[UserKeys.USER_ID]
        role = UserRole(user[UserKeys.ROLE])
        epoch = int(user.get(UserKeys.SESSION_EPOCH, 0))

        await repo.touch_last_seen(user_id)
        redirect = RedirectResponse(url=next_path, status_code=HTTP_STATUS_FOUND)
        issue_session_cookie(redirect, user_id=user_id, role=role, epoch=epoch, settings=settings)
        logger.info(
            "Google callback succeeded; session cookie issued",
            extra={"event": "google_callback_succeeded", "function": "google_callback", "user_id": user_id, "role": str(role)},
        )
        return redirect
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during Google callback",
            extra={"event": "google_callback_error", "function": "google_callback", "error": str(e)},
        )
        raise
