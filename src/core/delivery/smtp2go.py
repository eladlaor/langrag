import os

import requests
from dotenv import load_dotenv

from core.delivery.base import BaseEmailSender
from custom_types.exceptions import EmailDeliveryError
from constants import HEADER_CONTENT_TYPE, CONTENT_TYPE_JSON


load_dotenv()


class SMTP2GOEmailSender(BaseEmailSender):
    def __init__(self, sender_email_address: str):
        super().__init__(os.getenv("SMTP2GO_API_KEY"), sender_email_address)
        self.api_url = "https://api.smtp2go.com/v3/email/send"

    def _send(self, subject: str, html_content: str, recipient_emails: list[str]) -> None:
        try:
            headers = {
                HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
                "X-Smtp2go-Api-Key": self.api_key,
            }

            for recipient_email in recipient_emails:
                try:
                    payload = {
                        "sender": self.sender_email_address,
                        "to": recipient_email,
                        "subject": subject,
                        "html_body": html_content,
                    }

                    response = requests.post(self.api_url, json=payload, headers=headers)
                    response.raise_for_status()
                except requests.RequestException as e:
                    raise EmailDeliveryError(f"Failed to send email to {recipient_email}: {e}") from e
        except EmailDeliveryError:
            raise  # Re-raise email delivery errors as-is
        except Exception as e:
            raise EmailDeliveryError(f"Failed to send email: {e}") from e
