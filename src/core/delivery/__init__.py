"""
Delivery Module

Contains delivery mechanisms for distributing newsletters:
- substack: Substack API integration
- sendgrid: SendGrid email delivery
- smtp2go: SMTP2GO email delivery
"""

from core.delivery.base import BaseEmailSender
from core.delivery.substack import SubstackSender
from core.delivery.sendgrid import SendGridEmailSender
from core.delivery.smtp2go import SMTP2GOEmailSender

__all__ = [
    "BaseEmailSender",
    "SubstackSender",
    "SendGridEmailSender",
    "SMTP2GOEmailSender",
]
