"""
Gmail SMTP Email Sender

Sends emails via Gmail SMTP using App Passwords.

Setup:
1. Enable 2FA on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate an "App Password" for "Mail"
4. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from custom_types.exceptions import EmailDeliveryError

logger = logging.getLogger(__name__)

# Gmail SMTP settings
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465  # SSL


class GmailSMTPEmailSender:
    """
    Email sender using Gmail SMTP with App Passwords.

    Does not extend BaseEmailSender since it uses different auth mechanism.
    """

    def __init__(self, sender_email_address: str | None = None):
        """
        Initialize Gmail SMTP sender.

        Args:
            sender_email_address: Gmail address (optional, defaults to GMAIL_ADDRESS env var)
        """
        self.sender_email_address = sender_email_address or os.getenv("GMAIL_ADDRESS")
        self.app_password = os.getenv("GMAIL_APP_PASSWORD")

        if not self.sender_email_address:
            raise EmailDeliveryError("Gmail address not configured. Set GMAIL_ADDRESS env var.")

        if not self.app_password:
            raise EmailDeliveryError("Gmail App Password not configured. Set GMAIL_APP_PASSWORD env var. " "Generate at: https://myaccount.google.com/apppasswords")

    def _send(self, subject: str, html_content: str, recipient_emails: list[str]) -> None:
        """
        Send email via Gmail SMTP.

        Args:
            subject: Email subject line
            html_content: HTML body content
            recipient_emails: List of recipient email addresses

        Raises:
            EmailDeliveryError: When sending fails
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender_email_address
            msg["To"] = ", ".join(recipient_emails)

            # Attach HTML content
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            # Send via Gmail SMTP SSL
            with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as server:
                server.login(self.sender_email_address, self.app_password)
                server.sendmail(self.sender_email_address, recipient_emails, msg.as_string())

            logger.info(f"Email sent successfully via Gmail SMTP to {len(recipient_emails)} recipients")

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Gmail SMTP authentication failed: {e}")
            raise EmailDeliveryError(f"Gmail authentication failed. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD. " f"Make sure you're using an App Password, not your regular password. Error: {e}") from e

        except smtplib.SMTPException as e:
            logger.error(f"Gmail SMTP error: {e}")
            raise EmailDeliveryError(f"Failed to send email via Gmail SMTP: {e}") from e

        except Exception as e:
            logger.error(f"Unexpected error sending email via Gmail SMTP: {e}")
            raise EmailDeliveryError(f"Unexpected error sending email: {e}") from e
