"""
Rate limiting configuration for FastAPI.

Provides middleware and decorators for API rate limiting
to prevent abuse of expensive LLM operations.
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Create limiter instance using client IP as key
limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for the FastAPI application.

    Rate Limits:
    - Newsletter generation: 10/minute (expensive LLM operations)
    - Batch job queries: 60/minute
    - Health checks: 120/minute
    - Default: 30/minute

    The limiter uses client IP address as the rate limit key.
    In production behind a proxy, ensure X-Forwarded-For is trusted.

    Args:
        app: FastAPI application instance
    """
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        """Handle rate limit exceeded errors with JSON response."""
        logger.warning(f"Rate limit exceeded: {request.client.host} on {request.url.path}")
        return JSONResponse(status_code=429, content={"error": "rate_limit_exceeded", "message": f"Too many requests. {exc.detail}", "retry_after": getattr(exc, "retry_after", None)}, headers={"Retry-After": str(getattr(exc, "retry_after", 60))})

    logger.info("Rate limiting configured for API endpoints")


# Rate limit constants for easy reference in route decorators
RATE_NEWSLETTER_GENERATION = "10/minute"
RATE_BATCH_JOB_QUERY = "60/minute"
RATE_HEALTH_CHECK = "120/minute"
RATE_DEFAULT = "30/minute"
