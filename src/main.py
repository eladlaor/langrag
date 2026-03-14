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

from fastapi import FastAPI
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
from api import newsletter_gen, async_batch_orchestration, schedules
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
    try:
        from db.connection import get_database, close_connection
        from db.indexes import ensure_indexes

        logger.info("Initializing MongoDB connection...")
        db = await get_database()
        logger.info("Creating database indexes...")
        await ensure_indexes(db)
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

# Including routers
app.include_router(newsletter_gen.router, prefix=API_V1_PREFIX, tags=["newsletter-generation"])
app.include_router(async_batch_orchestration.router, prefix=API_V1_PREFIX, tags=["async-batch-orchestration"])
app.include_router(runs_router, prefix=API_V1_PREFIX, tags=["observability-runs"])
app.include_router(metrics_router, tags=["observability-metrics"])
app.include_router(schedules.router, prefix=API_V1_PREFIX, tags=["schedules"])


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
