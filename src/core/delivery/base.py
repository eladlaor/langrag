from abc import ABC, abstractmethod
from html import escape

from custom_types.exceptions import EmailDeliveryError, ValidationError
from custom_types.field_keys import DiscussionKeys


class BaseEmailSender(ABC):
    """
    Abstract base class for email delivery providers.

    Subclasses must implement _send() for provider-specific delivery logic.
    """

    def __init__(self, api_key: str, sender_email_address: str) -> None:
        if not api_key:
            raise ValidationError("API key is required")

        if not sender_email_address:
            raise ValidationError("Sender email address is required")

        self.api_key = api_key
        self.sender_email_address = sender_email_address

    @abstractmethod
    def _send(self, subject: str, html_content: str, recipient_emails: list[str]) -> None:
        """
        Send email via provider-specific implementation.

        Args:
            subject: Email subject line
            html_content: HTML body content
            recipient_emails: List of recipient email addresses

        Raises:
            EmailDeliveryError: When sending fails
        """
        pass

    def publish_newsletter(self, content: dict, recipient_emails: list[str]) -> tuple[bool, str]:
        """
        Publish newsletter to recipients via email.

        Args:
            content: Newsletter content dict with group_name and discussions
            recipient_emails: List of recipient email addresses

        Returns:
            Tuple of (success: bool, message: str)
        """
        html_content, error = self._convert_to_html(content)
        if error:
            return False, error

        try:
            self._send(
                subject="this week's newsletter",
                html_content=html_content,
                recipient_emails=recipient_emails,
            )
            return True, "Email sent successfully"
        except EmailDeliveryError as e:
            return False, f"Failed to send email: {str(e)}"
        except Exception as e:
            # Unexpected error - wrap in EmailDeliveryError for consistency
            return False, f"Unexpected error sending email: {str(e)}"

    def _convert_to_html(self, content: dict) -> tuple[str, None]:
        """
        Convert newsletter content to HTML with proper escaping.

        Args:
            content: Newsletter content dict

        Returns:
            Tuple of (html_content, None) - error is always None for now
        """
        # Escape user content to prevent XSS
        group_name = escape(content.get(DiscussionKeys.GROUP_NAME, "הקבוצה שלך"))
        discussions = content.get(DiscussionKeys.DISCUSSIONS, [])

        html_content = f"""
        <div dir="rtl" style="text-align: right; direction: rtl;">
            <h1 style="text-align: right;">סיכום שבועי של {group_name}</h1>
        """

        for discussion in discussions:
            # Escape title to prevent XSS
            title = escape(discussion.get("title", ""))
            html_content += f"""
                <h2 style="text-align: right;">{title}</h2>
            """

            # Add detailed summary as bullet points
            if DiscussionKeys.DETAILED_SUMMARY in discussion:
                html_content += '<ul style="text-align: right; direction: rtl;">'
                for bullet in discussion[DiscussionKeys.DETAILED_SUMMARY]:
                    # Escape content to prevent XSS
                    emoji = escape(bullet.get("emoji", ""))
                    point = escape(bullet.get("point", ""))
                    html_content += f'<li style="text-align: right; direction: rtl;">{emoji} {point}</li>'
                html_content += "</ul>"

            # Add relevant links section
            if DiscussionKeys.RELEVANT_LINKS in discussion and len(discussion[DiscussionKeys.RELEVANT_LINKS]) > 0:
                html_content += '<h3 style="text-align: right;">קישורים רלוונטיים:</h3><ul style="text-align: right; direction: rtl;">'
                for link in discussion[DiscussionKeys.RELEVANT_LINKS]:
                    # Escape title and URL to prevent XSS
                    link_title = escape(link.get("title", ""))
                    url = escape(link.get("link", ""))
                    html_content += f'<li style="text-align: right;"><a href="{url}" style="text-align: right;">{link_title}</a></li>'
                html_content += "</ul>"

            # Add metadata information
            if DiscussionKeys.METADATA in discussion:
                messages_n = int(discussion[DiscussionKeys.METADATA].get("messages_n", 0))
                participants_n = int(discussion[DiscussionKeys.METADATA].get("participants_n", 0))
                html_content += f"<p style='text-align: right;'><strong>מספר הודעות:</strong> {messages_n} | " f"<strong>משתתפים:</strong> {participants_n}</p>"

        html_content += """
            <p style="text-align: right;">תודה שקראת את הסיכום השבועי שלנו! נתראה בשבוע הבא.</p>
        </div>
        """
        return html_content, None
