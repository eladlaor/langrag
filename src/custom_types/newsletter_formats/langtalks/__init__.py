"""
LangTalks Newsletter Format Plugin

Auto-discovered by the newsletter format registry.
"""

from .format import LangTalksFormat

# This attribute is required for auto-discovery
FORMAT_CLASS = LangTalksFormat

__all__ = ["LangTalksFormat", "FORMAT_CLASS"]
