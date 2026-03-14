import logging
import os

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv

from core.delivery.base import BaseEmailSender
from custom_types.exceptions import EmailDeliveryError

load_dotenv()
logger = logging.getLogger(__name__)


class SendGridEmailSender(BaseEmailSender):
    def __init__(self, sender_email_address: str):
        super().__init__(os.getenv("SENDGRID_API_KEY"), sender_email_address)

    def _send(self, subject: str, html_content: str, recipient_emails: list[str]) -> None:
        message = Mail(
            from_email=self.sender_email_address,
            to_emails=recipient_emails,
            subject=subject,
            html_content=html_content,
        )
        try:
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(message)
            logger.info(f"Email sent successfully. Status Code: {response.status_code}")
            logger.debug(f"SendGrid Response Body: {response.body}")
            return response
        except Exception as e:
            raise EmailDeliveryError(f"Failed to send email via SendGrid: {e}") from e
