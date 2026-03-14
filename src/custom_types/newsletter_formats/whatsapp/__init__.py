"""
WhatsApp Newsletter Format Plugin

Auto-discovered by the newsletter format registry.
"""

from .format import WhatsAppFormat

# This attribute is required for auto-discovery
FORMAT_CLASS = WhatsAppFormat

__all__ = ["WhatsAppFormat", "FORMAT_CLASS"]
