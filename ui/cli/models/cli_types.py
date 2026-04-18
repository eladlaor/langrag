"""
CLI-specific type definitions and enums.

Defines enums for data sources, languages, formats, and chat name mappings.
"""

from enum import Enum


class DataSource(str, Enum):
    """Available data sources for newsletter generation."""

    LANGTALKS = "langtalks"
    MCP_ISRAEL = "mcp_israel"
    N8N_ISRAEL = "n8n_israel"


class Language(str, Enum):
    """Supported target languages for newsletter summaries."""

    ENGLISH = "english"
    HEBREW = "hebrew"
    SPANISH = "spanish"
    FRENCH = "french"


class SummaryFormat(str, Enum):
    """Newsletter format templates."""

    LANGTALKS = "langtalks_format"
    MCP_ISRAEL = "mcp_israel_format"


class SimilarityThreshold(str, Enum):
    """Discussion merging threshold levels."""

    STRICT = "strict"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class OutputAction(str, Enum):
    """Available output actions for newsletter delivery."""

    SAVE_LOCAL = "save_local"
    WEBHOOK = "webhook"
    SEND_EMAIL = "send_email"
    SEND_SUBSTACK = "send_substack"
    SEND_LINKEDIN = "send_linkedin"


# Chat name mappings by data source (case-sensitive)
# Source of Truth: frontend/src/constants/index.ts
CHAT_NAMES: dict[DataSource, list[str]] = {
    DataSource.LANGTALKS: [
        "LangTalks Community",
        "LangTalks Community 2",
        "LangTalks Community 3",
        "LangTalks Community 4",
        "LangTalks - Code Generation Agents",
        "LangTalks - English",
        "LangTalks - AI driven coding",
        "LangTalks AI-SDLC",
    ],
    DataSource.MCP_ISRAEL: [
        "MCP Israel",
        "MCP Israel #2",
        "A2A Israel",
    ],
    DataSource.N8N_ISRAEL: [
        "n8n israel",
        "n8n israel 2",
        "n8n israel - Main 1",
        "n8n israel - Main 2",
        "n8n Israel - Main 3",
    ],
}


# HITL timeout presets (minutes)
HITL_TIMEOUT_PRESETS = [0, 15, 30, 60, 120, 240, 480, 1440]  # 0 = disabled, max = 24 hours
