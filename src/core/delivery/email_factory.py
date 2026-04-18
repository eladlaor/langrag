"""
Email Sender Factory

Provides a unified interface for sending emails via different providers.
Automatically selects the appropriate provider based on configuration.

Supported Providers:
- gmail: Gmail SMTP with App Passwords
- sendgrid: SendGrid API

Configuration:
    EMAIL_PROVIDER=gmail|sendgrid (default: auto-detect)

    For Gmail:
        GMAIL_ADDRESS=your_email@gmail.com
        GMAIL_APP_PASSWORD=your_16_char_app_password

    For SendGrid:
        SENDGRID_API_KEY=your_api_key
        EMAIL_SENDER_ADDRESS=verified_sender@yourdomain.com
"""

import logging
import os
from pathlib import Path
from typing import Protocol

from constants import EmailProvider

TEMPLATES_DIR = Path(__file__).parent / "templates"

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    """Protocol for email senders."""

    def _send(self, subject: str, html_content: str, recipient_emails: list[str]) -> None:
        """Send an email."""
        ...


def get_email_sender() -> EmailSender:
    """
    Get the configured email sender.

    Auto-detection order:
    1. If EMAIL_PROVIDER is set, use that provider
    2. If GMAIL_ADDRESS and GMAIL_APP_PASSWORD are set, use Gmail
    3. If SENDGRID_API_KEY is set, use SendGrid
    4. Raise error if no provider configured

    Returns:
        EmailSender instance

    Raises:
        RuntimeError: If no email provider is configured
    """
    provider = os.getenv("EMAIL_PROVIDER", "").lower()

    # Explicit provider selection
    if provider == EmailProvider.GMAIL:
        return _get_gmail_sender()
    elif provider == EmailProvider.SENDGRID:
        return _get_sendgrid_sender()

    # Auto-detect based on available credentials
    if os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"):
        logger.info("Auto-detected Gmail SMTP configuration")
        return _get_gmail_sender()

    if os.getenv("SENDGRID_API_KEY"):
        logger.info("Auto-detected SendGrid configuration")
        return _get_sendgrid_sender()

    raise RuntimeError("No email provider configured. Set one of:\n" "  - EMAIL_PROVIDER=gmail with GMAIL_ADDRESS and GMAIL_APP_PASSWORD\n" "  - EMAIL_PROVIDER=sendgrid with SENDGRID_API_KEY and EMAIL_SENDER_ADDRESS\n" "  - Or just set the credentials and provider will be auto-detected")


def _get_gmail_sender() -> EmailSender:
    """Get Gmail SMTP sender."""
    from core.delivery.gmail_smtp import GmailSMTPEmailSender

    return GmailSMTPEmailSender()


def _get_sendgrid_sender() -> EmailSender:
    """Get SendGrid sender."""
    from core.delivery.sendgrid import SendGridEmailSender

    sender_address = os.getenv("EMAIL_SENDER_ADDRESS")
    if not sender_address:
        raise RuntimeError("SendGrid requires EMAIL_SENDER_ADDRESS to be set. " "This must be a verified sender in your SendGrid account.")

    return SendGridEmailSender(sender_email_address=sender_address)


def render_email_template(template_name: str, **kwargs: str) -> str:
    """
    Load and render an HTML email template from the templates directory.

    Args:
        template_name: Filename of the template (e.g., "newsletter_notification.html")
        **kwargs: Template variables to substitute

    Returns:
        Rendered HTML string

    Raises:
        FileNotFoundError: If the template file does not exist
    """
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Email template not found: {template_path}")

    template = template_path.read_text(encoding="utf-8")
    return template.format(**kwargs)


def send_email(subject: str, html_content: str, recipient_emails: list[str]) -> None:
    """
    Send an email using the configured provider.

    This is the main entry point for sending emails throughout the application.

    Args:
        subject: Email subject line
        html_content: HTML body content
        recipient_emails: List of recipient email addresses

    Raises:
        RuntimeError: If no email provider is configured
        EmailDeliveryError: If sending fails
    """
    sender = get_email_sender()
    sender._send(subject=subject, html_content=html_content, recipient_emails=recipient_emails)
