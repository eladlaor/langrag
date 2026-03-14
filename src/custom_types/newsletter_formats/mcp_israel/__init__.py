"""
MCP Israel Newsletter Format Plugin

Auto-discovered by the newsletter format registry.
"""

from .format import McpIsraelFormat

# This attribute is required for auto-discovery
FORMAT_CLASS = McpIsraelFormat

__all__ = ["McpIsraelFormat", "FORMAT_CLASS"]
