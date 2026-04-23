"""
Security Headers Middleware

Adds security headers to all HTTP responses to protect against common web vulnerabilities:
- HSTS (HTTP Strict Transport Security)
- CSP (Content Security Policy)
- X-Frame-Options (Clickjacking protection)
- X-Content-Type-Options (MIME sniffing protection)
- X-XSS-Protection (Legacy XSS protection)
- Referrer-Policy (Control referrer information)
- Permissions-Policy (Control browser features)

These headers implement defense-in-depth security best practices.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.

    Implements OWASP security recommendations:
    - Prevents clickjacking attacks
    - Mitigates XSS attacks
    - Controls content loading policies
    - Enforces HTTPS in production
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        enable_hsts: bool = True,
        hsts_max_age: int = 31536000,  # 1 year
        enable_csp: bool = True,
        csp_directives: dict[str, list[str]] | None = None,
    ):
        """
        Initialize security headers middleware.

        Args:
            app: ASGI application
            enable_hsts: Enable HTTP Strict Transport Security
            hsts_max_age: HSTS max-age in seconds (default: 1 year)
            enable_csp: Enable Content Security Policy
            csp_directives: Custom CSP directives (default: secure baseline)
        """
        try:
            super().__init__(app)
            self.enable_hsts = enable_hsts
            self.hsts_max_age = hsts_max_age
            self.enable_csp = enable_csp

            # Default CSP: Strict baseline allowing only same-origin and specific CDNs
            self.csp_directives = csp_directives or {
                "default-src": ["'self'"],
                "script-src": [
                    "'self'",
                    "'unsafe-inline'",  # Required for React inline scripts
                    "https://cdn.jsdelivr.net",  # Bootstrap CDN
                ],
                "style-src": [
                    "'self'",
                    "'unsafe-inline'",  # Required for inline styles
                    "https://cdn.jsdelivr.net",
                ],
                "img-src": ["'self'", "data:", "https:"],
                "font-src": ["'self'", "data:", "https://cdn.jsdelivr.net"],
                "connect-src": ["'self'"],  # Allow same-origin API calls
                "frame-ancestors": ["'none'"],  # Prevent embedding (clickjacking)
                "base-uri": ["'self'"],
                "form-action": ["'self'"],
            }

            logger.info("SecurityHeadersMiddleware initialized with HSTS=%s, CSP=%s", enable_hsts, enable_csp)
        except Exception as e:
            logger.error(f"Failed to initialize SecurityHeadersMiddleware: {e}")
            raise

    def _build_csp_header(self) -> str:
        """
        Build Content-Security-Policy header from directives.

        Returns:
            CSP header string
        """
        try:
            directives = []
            for directive, sources in self.csp_directives.items():
                directives.append(f"{directive} {' '.join(sources)}")
            return "; ".join(directives)
        except Exception as e:
            logger.error(f"Failed to build CSP header: {e}")
            # Return minimal safe CSP as fallback
            return "default-src 'self'"

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Add security headers to response.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware in chain

        Returns:
            Response with security headers added
        """
        try:
            # Process request through rest of middleware chain
            response = await call_next(request)

            # Add security headers
            headers = {}

            # 1. X-Frame-Options: Prevent clickjacking
            headers["X-Frame-Options"] = "DENY"

            # 2. X-Content-Type-Options: Prevent MIME sniffing
            headers["X-Content-Type-Options"] = "nosniff"

            # 3. X-XSS-Protection: Legacy XSS protection (for older browsers)
            headers["X-XSS-Protection"] = "1; mode=block"

            # 4. Referrer-Policy: Control referrer information leakage
            headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

            # 5. Permissions-Policy: Disable unused browser features
            headers["Permissions-Policy"] = "geolocation=(), " "microphone=(), " "camera=(), " "payment=(), " "usb=(), " "magnetometer=(), " "gyroscope=()"

            # 6. HSTS: Enforce HTTPS (production only)
            if self.enable_hsts:
                headers["Strict-Transport-Security"] = f"max-age={self.hsts_max_age}; " "includeSubDomains; " "preload"

            # 7. Content-Security-Policy: Control content loading
            if self.enable_csp:
                headers["Content-Security-Policy"] = self._build_csp_header()

            # Apply all headers to response
            for header_name, header_value in headers.items():
                response.headers[header_name] = header_value

            return response

        except Exception as e:
            logger.error(f"Error in SecurityHeadersMiddleware: {e}")
            # Re-raise — calling call_next(request) again would double-dispatch
            raise


def add_security_headers(app: ASGIApp, **kwargs) -> None:
    """
    Convenience function to add security headers middleware.

    Args:
        app: FastAPI application
        **kwargs: Middleware configuration options

    Example:
        from api.security_headers import add_security_headers
        add_security_headers(app, enable_hsts=True)
    """
    try:
        app.add_middleware(SecurityHeadersMiddleware, **kwargs)
        logger.info("Security headers middleware added successfully")
    except Exception as e:
        logger.error(f"Failed to add security headers middleware: {e}")
        raise
