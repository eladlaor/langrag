"""
Rate limiter re-export for the RAG API.

Re-exports the application-wide limiter from api.rate_limiting so RAG endpoints
share quota state with the rest of the FastAPI app and the per-caller key
function (API key first, IP fallback) is consistent.
"""

from api.rate_limiting import limiter

__all__ = ["limiter"]
