"""
FastAPI Main Application for LangRAG

This module defines the main FastAPI application.
It provides REST API endpoints for newsletter generation,
invoking LangGraph workflows for orchestration.

Architecture:
- FastAPI for async HTTP handling
- LangGraph workflows for business logic orchestration
- Pydantic models for request/response validation
- Automatic OpenAPI documentation at /docs
- MongoDB for persistence (runs, discussions, cache)
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Loading environment variables FIRST, before any other imports that depend on env vars
from config import load_environment

load_environment()

# Initializing logging EARLY (before other imports)
from observability.app import setup_logging, get_logger

setup_logging()

# Getting logger for this module
logger = get_logger(__name__)

# Importing routers after logging setup
from api import auth, admin_users, newsletter_gen, async_batch_orchestration, schedules, rag_conversation, images, media, google_oauth
from api.auth import require_session
from api.observability import metrics_router, runs_router
from constants import (
    API_V1_PREFIX,
    ROUTE_ROOT,
    ROUTE_HEALTH,
    ROUTE_DOCS,
    ROUTE_REDOC,
    APP_NAME,
    APP_VERSION,
    APP_DESCRIPTION,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for startup/shutdown events.

    Startup:
    - Initializing MongoDB connection
    - Ensuring database indexes exist
    - Starting newsletter scheduler

    Shutdown:
    - Stopping newsletter scheduler
    - Closing MongoDB connection gracefully
    """
    # Startup
    # Fail-fast on missing required API keys. Previously a missing OPENAI_API_KEY
    # only surfaced deep in the pipeline (MMR reranker, hybrid merger) as silent
    # fallbacks, producing degraded newsletters with no clear signal.
    import os as _os

    _required_api_keys = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    _missing_keys = [k for k in _required_api_keys if not _os.getenv(k)]
    if _missing_keys:
        raise RuntimeError(f"Required API keys missing from environment: {_missing_keys}. Set them in .env and ensure docker-compose passes them through before starting the service.")

    # Fail-fast on a misconfigured login gate so production never boots an open
    # gate. When enabled, the Fernet session key MUST be present (it is the only
    # secret the per-user cookie login path needs; the old shared
    # LANGRAG_LOGIN_PASSWORD is deprecated and no longer required at startup).
    from config import get_settings as _get_settings
    from constants import ENV_LOGIN_SESSION_KEY

    _login_settings = _get_settings().login
    if _login_settings.enabled and not _login_settings.session_key:
        raise RuntimeError(
            f"Login gate is enabled but {ENV_LOGIN_SESSION_KEY} is missing. "
            f"Set it in the environment (or set LANGRAG_LOGIN_ENABLED=false to disable the gate) before starting the service."
        )

    # Fail-fast on a misconfigured Google OAuth surface. When Google sign-in is
    # enabled, the OAuth client id/secret/redirect plus the secret signing the
    # transient Authlib session MUST all be present (mirrors the login gate
    # check above). Register the Authlib client once at startup.
    from constants import (
        ENV_GOOGLE_CLIENT_ID,
        ENV_GOOGLE_CLIENT_SECRET,
        ENV_GOOGLE_REDIRECT_URI,
        ENV_SIGNUP_OAUTH_STATE_SECRET,
    )

    _settings = _get_settings()
    if _settings.google.enabled:
        _google_missing = []
        if not _settings.google.client_id:
            _google_missing.append(ENV_GOOGLE_CLIENT_ID)
        if not _settings.google.client_secret:
            _google_missing.append(ENV_GOOGLE_CLIENT_SECRET)
        if not _settings.google.redirect_uri:
            _google_missing.append(ENV_GOOGLE_REDIRECT_URI)
        if not _settings.signup.oauth_state_secret:
            _google_missing.append(ENV_SIGNUP_OAUTH_STATE_SECRET)
        if _google_missing:
            raise RuntimeError(
                f"Google sign-in is enabled but required secrets are missing: {_google_missing}. "
                f"Set them in the environment (or set LANGRAG_GOOGLE_ENABLED=false to disable Google sign-in) before starting the service."
            )
        from api.google_oauth import register_google

        register_google(_settings)

    try:
        from db.connection import get_database, close_connection
        from db.indexes import ensure_indexes

        from db.bootstrap_admin import ensure_bootstrap_admin

        logger.info("Initializing MongoDB connection...")
        db = await get_database()
        logger.info("Creating database indexes...")
        await ensure_indexes(db)
        logger.info("Ensuring bootstrap admin...")
        await ensure_bootstrap_admin(db)
        logger.info("MongoDB initialization complete")
    except Exception as e:
        logger.error(f"MongoDB initialization failed: {e}")
        raise

    # Start newsletter scheduler
    try:
        from scheduler.newsletter_scheduler import start_scheduler

        await start_scheduler()
    except Exception as e:
        logger.warning(f"Newsletter scheduler failed to start: {e}")

    yield

    # Shutdown
    # Stop newsletter scheduler
    try:
        from scheduler.newsletter_scheduler import stop_scheduler

        await stop_scheduler()
    except Exception as e:
        logger.warning(f"Error stopping newsletter scheduler: {e}")

    try:
        from graphs.checkpointer import close_checkpointer

        await close_checkpointer()
    except Exception as e:
        logger.warning(f"Error closing checkpointer: {e}")

    try:
        from db.connection import close_connection

        logger.info("Closing MongoDB connection...")
        await close_connection()
        logger.info("MongoDB connection closed")
    except Exception as e:
        logger.warning(f"Error closing MongoDB connection: {e}")


# Creating FastAPI app with lifespan handler
app = FastAPI(
    title=APP_NAME,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    docs_url=ROUTE_DOCS,
    redoc_url=ROUTE_REDOC,
    lifespan=lifespan,
)

# Importing config after logging setup
from config import get_settings

# CORS middleware (uses config for allowed origins)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Transient signed Starlette session for Authlib's OAuth state+nonce round-trip
# ONLY. This is NOT the Fernet auth session (that stays an HttpOnly cookie
# issued by issue_session_cookie); it is a short-lived cookie that carries the
# CSRF state and OIDC nonce across the Google redirect. SameSite=Lax is correct
# for the top-level callback navigation. Only added when Google is enabled so
# the default deployment is unaffected.
if settings.google.enabled:
    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.signup.oauth_state_secret,
        same_site="lax",
        https_only=settings.login.cookie_secure,
    )

# Security headers middleware
from api.security_headers import add_security_headers

is_production = os.getenv("ENVIRONMENT", "development") == "production"
add_security_headers(
    app,
    enable_hsts=is_production,  # Only enforce HTTPS in production
    hsts_max_age=31536000,  # 1 year
    enable_csp=True,  # Content Security Policy
)

# Rate limiting middleware
from api.rate_limiting import setup_rate_limiting

setup_rate_limiting(app)

# Auth router is mounted PUBLICLY: login/logout/session must be reachable
# without an existing session (it is what establishes the session).
app.include_router(auth.router, prefix=API_V1_PREFIX, tags=["auth"])
# Google OAuth login/callback. Mounted on the same public auth prefix so they
# resolve at /api/auth/google/login and /api/auth/google/callback. Always
# mounted; both routes 404 when Google is disabled (the SessionMiddleware they
# need is only added when enabled, but the disabled-guard returns before any
# request.session access).
app.include_router(google_oauth.router, prefix=API_V1_PREFIX, tags=["auth-google"])
# Admin-only user management. The router self-guards every route with
# require_admin (which depends on require_session), so no _session_gate here.
app.include_router(admin_users.router, prefix=API_V1_PREFIX, tags=["admin-users"])
# Admin-only extracted-images gallery + media serving. Both routers self-guard
# every route with require_admin, so no _session_gate here.
app.include_router(images.router, prefix=API_V1_PREFIX, tags=["images"])
app.include_router(media.router, prefix=API_V1_PREFIX, tags=["media"])

# UI-facing data routers are gated server-side by the require_session dependency
# so even a client that bypasses the React LoginGate (e.g. curl) cannot read
# newsletter / runs / schedules / RAG data without a valid session cookie.
_session_gate = [Depends(require_session)]
app.include_router(newsletter_gen.router, prefix=API_V1_PREFIX, tags=["newsletter-generation"], dependencies=_session_gate)
# Was previously mounted with no session gate (the only UI-data router lacking
# one). Closed while hardening the auth boundary: batch orchestration triggers
# real newsletter runs and must not be reachable unauthenticated.
app.include_router(async_batch_orchestration.router, prefix=API_V1_PREFIX, tags=["async-batch-orchestration"], dependencies=_session_gate)
app.include_router(runs_router, prefix=API_V1_PREFIX, tags=["observability-runs"], dependencies=_session_gate)
app.include_router(metrics_router, tags=["observability-metrics"])
app.include_router(schedules.router, prefix=API_V1_PREFIX, tags=["schedules"], dependencies=_session_gate)
app.include_router(rag_conversation.router, prefix=API_V1_PREFIX, tags=["rag-conversation"], dependencies=_session_gate)

# Agentic chatbot (v1.13.0+): mounted only when AGENT_ENABLED=true so the
# default deployment is unaffected. See knowledge/plans/AGENTIC_CHATBOT_LAYER.md.
if get_settings().agent.enabled:
    from api import agent_chat

    app.include_router(agent_chat.router, prefix=API_V1_PREFIX, tags=["agent"], dependencies=_session_gate)


@app.get(ROUTE_ROOT)
async def root():
    """Root endpoint with API information."""
    try:
        return {
            "message": APP_NAME,
            "version": APP_VERSION,
            "docs_url": ROUTE_DOCS,
            "redoc_url": ROUTE_REDOC,
        }
    except Exception as e:
        logger.error(f"Unexpected error in root endpoint: {e}")
        raise


@app.get(ROUTE_HEALTH)
async def health_check():
    """Health check endpoint for monitoring."""
    try:
        return {"status": "healthy", "service": "langrag-api"}
    except Exception as e:
        logger.error(f"Unexpected error in health check endpoint: {e}")
        raise


if __name__ == "__main__":
    import uvicorn

    app_settings = get_settings()
    uvicorn.run("src.main:app", host=app_settings.api.host, port=app_settings.api.port, reload=True, log_level="info")
