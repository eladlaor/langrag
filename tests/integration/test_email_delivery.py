"""
Integration test for email delivery.

Sends a real email with mock newsletter HTML to verify Gmail SMTP
credentials and HTML formatting. Check your inbox for the result.

Run:
    pytest tests/integration/test_email_delivery.py -v
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env before any src imports
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Ensure src is on path
src_path = Path(__file__).parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


pytestmark = pytest.mark.skipif(
    not (os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD")),
    reason="Gmail credentials not set in .env (GMAIL_ADDRESS, GMAIL_APP_PASSWORD)",
)

MOCK_NEWSLETTER_HTML = """\
<!DOCTYPE html>
<html dir="ltr" lang="en">
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; background: #f9f9f9; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 24px; border-radius: 8px; margin-bottom: 24px; }
        .header h1 { margin: 0; font-size: 22px; }
        .header p { margin: 8px 0 0; opacity: 0.9; font-size: 14px; }
        .discussion { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .discussion h2 { color: #333; font-size: 18px; margin-top: 0; }
        .discussion ul { padding-left: 20px; }
        .discussion li { margin-bottom: 8px; line-height: 1.5; color: #555; }
        .metadata { font-size: 12px; color: #999; margin-top: 12px; padding-top: 12px; border-top: 1px solid #eee; }
        .links { margin-top: 12px; }
        .links a { color: #667eea; text-decoration: none; }
        .links a:hover { text-decoration: underline; }
        .footer { text-align: center; color: #999; font-size: 12px; margin-top: 24px; }
        .badge { display: inline-block; background: #667eea; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 8px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>LangTalks Weekly Newsletter</h1>
        <p>Smoke Test Edition &mdash; Verifying Email Delivery Pipeline</p>
    </div>

    <div class="discussion">
        <h2>🚀 New RAG Architecture Patterns <span class="badge">Featured</span></h2>
        <ul>
            <li><strong>Agentic RAG</strong> is gaining traction &mdash; multiple community members shared production experiences with tool-calling retrieval agents.</li>
            <li>A comparison of <strong>ColBERT v2 vs dense retrieval</strong> showed 15% improvement on domain-specific benchmarks.</li>
            <li>Discussion around <strong>hybrid search</strong> combining BM25 + vector for better recall in multilingual corpora.</li>
        </ul>
        <div class="links">
            <strong>Links:</strong>
            <a href="https://example.com/rag-patterns">RAG Patterns Guide</a> |
            <a href="https://example.com/colbert">ColBERT v2 Paper</a>
        </div>
        <div class="metadata">💬 42 messages &bull; 👥 12 participants</div>
    </div>

    <div class="discussion">
        <h2>🔧 LangGraph State Management Tips</h2>
        <ul>
            <li>Best practices for <strong>TypedDict state schemas</strong> with annotated reducers were shared.</li>
            <li>Several members reported issues with <strong>checkpoint serialization</strong> when using complex Pydantic models in state.</li>
            <li>A working example of <strong>human-in-the-loop</strong> with interrupt_before was contributed.</li>
        </ul>
        <div class="metadata">💬 28 messages &bull; 👥 8 participants</div>
    </div>

    <div class="discussion">
        <h2>💡 Worth Mentioning</h2>
        <ul>
            <li>Claude 4 benchmarks discussed &mdash; impressive coding performance noted.</li>
            <li>New Ollama release supports structured output natively.</li>
        </ul>
    </div>

    <div class="footer">
        <p>This is a <strong>smoke test email</strong> from the LangRAG pipeline integration tests.</p>
        <p>If you can read this with proper formatting, the email delivery pipeline is working correctly.</p>
    </div>
</body>
</html>
"""


class TestEmailDelivery:
    """Test real email delivery via Gmail SMTP."""

    def test_send_html_email(self):
        """Send a formatted HTML newsletter email and verify no errors.

        SUCCESS = email sent without exceptions.
        Then manually check your inbox for proper formatting.
        """
        from core.delivery.email_factory import send_email

        recipient = os.getenv("DEFAULT_EMAIL_RECIPIENT", os.getenv("GMAIL_ADDRESS"))

        send_email(
            subject="[SMOKE TEST] LangRAG Email Delivery Integration Test",
            html_content=MOCK_NEWSLETTER_HTML,
            recipient_emails=[recipient],
        )

        # If we get here without an exception, the email was sent.
        # Check your inbox to verify formatting.

    def test_gmail_sender_initialization(self):
        """Verify GmailSMTPEmailSender initializes with .env credentials."""
        from core.delivery.gmail_smtp import GmailSMTPEmailSender

        sender = GmailSMTPEmailSender()
        assert sender.sender_email_address == os.getenv("GMAIL_ADDRESS")
        assert sender.app_password is not None
        assert len(sender.app_password) > 0
