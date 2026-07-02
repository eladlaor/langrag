"""
Verification email for the public podcast-MCP key issuance flow.

Builds the single-use verification link (base URL from config + ?token=<TOKEN>)
and sends a minimal HTML email via the existing delivery layer
(`core.delivery.email_factory.send_email`), so provider selection (Gmail /
SendGrid) and credentials are reused exactly as the newsletter path uses them.

Delivery failures propagate as exceptions; the API layer catches them, logs at
error level, and still returns the generic 202 (opaque externally, fail-fast
internally).
"""

import logging
from urllib.parse import urlencode

from constants import PODCAST_CONSUMER_TOKEN_QUERY_PARAM
from core.delivery.email_factory import send_email

logger = logging.getLogger(__name__)

_SUBJECT = "Verify your LangTalks podcast MCP API key"


def build_verification_link(base_url: str, token: str) -> str:
    """Return the verification URL: base_url with the token as a query param.

    Uses urlencode so the opaque token is safely escaped. The query param name is
    a constant (frozen contract with the langrag.ai/podcasts frontend).
    """
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({PODCAST_CONSUMER_TOKEN_QUERY_PARAM: token})}"


def _render_html(verify_link: str) -> str:
    """Minimal HTML body. The link is the only dynamic, security-relevant part."""
    return (
        '<div style="font-family: sans-serif; line-height: 1.5;">'
        "<h2>Your LangTalks podcast MCP key</h2>"
        "<p>Click the button below to verify your email and reveal your API key "
        "for the LangTalks podcast MCP server. This link is single-use and "
        "expires shortly.</p>"
        f'<p><a href="{verify_link}" '
        'style="display:inline-block;padding:10px 18px;background:#4f46e5;'
        'color:#fff;text-decoration:none;border-radius:6px;">Verify & get my key</a></p>'
        f"<p>Or paste this link into your browser:<br><span>{verify_link}</span></p>"
        '<p style="color:#666;font-size:12px;">If you did not request this, you '
        "can safely ignore this email.</p>"
        "</div>"
    )


def send_verification_email(recipient_email: str, *, base_url: str, token: str) -> None:
    """Send the verification email carrying the single-use token link.

    Raises on delivery failure (the caller decides how to translate it — this
    surface returns 202 regardless, but logs the failure server-side).
    """
    verify_link = build_verification_link(base_url, token)
    try:
        send_email(subject=_SUBJECT, html_content=_render_html(verify_link), recipient_emails=[recipient_email])
        logger.info(
            "Sent podcast consumer verification email",
            extra={"event": "podcast_consumer_email_sent", "function": "send_verification_email", "email": recipient_email},
        )
    except Exception as e:
        logger.error(
            "Failed to send podcast consumer verification email",
            extra={"event": "podcast_consumer_email_failed", "function": "send_verification_email", "email": recipient_email, "error": str(e)},
        )
        raise
