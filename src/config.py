"""
Application Configuration using Pydantic Settings

This module provides centralized configuration management for the LangRAG application.
All configurable values (environment variables, runtime settings) should be defined here.

Priority (highest to lowest):
1. Environment variables
2. .env file
3. Default values defined here

Usage:
    from config import load_environment, get_settings

    # Call once at startup, before other imports
    load_environment()

    # Then use settings
    settings = get_settings()
    model = settings.llm.default_model
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from constants import SimilarityThreshold, VisionDescribeScope


# ============================================================================
# ENVIRONMENT LOADING
# ============================================================================

_environment_loaded = False


def load_environment() -> None:
    """
    Load environment variables with proper fallback chain.

    Priority:
        1. ENV_FILE env var (explicit path)
        2. .env (production default)
        3. .env.dev (development fallback)
        4. System environment variables (Docker/containerized)

    Call this once at application startup, before importing other modules
    that depend on environment variables.

    Raises:
        RuntimeError: If ENV_FILE is specified but the file doesn't exist.
    """
    global _environment_loaded

    if _environment_loaded:
        return

    env_file = os.getenv("ENV_FILE")

    if env_file:
        # Explicit path provided
        if not os.path.exists(env_file):
            raise RuntimeError(f"ENV_FILE specified but not found: {env_file}")
        load_dotenv(env_file)
        _environment_loaded = True
        return

    # Auto-detect: prefer .env (production), fallback to .env.dev (development)
    for candidate in [".env", ".env.dev"]:
        if os.path.exists(candidate):
            load_dotenv(candidate)
            _environment_loaded = True
            return

    # No .env file found - rely on system environment variables (e.g., Docker)
    # This is valid in containerized environments
    _environment_loaded = True


# ============================================================================
# LLM CONFIGURATION
# ============================================================================


class LLMSettings(BaseSettings):
    """LLM model and parameter configuration.

    Provider selection is controlled by the `provider` field (env: LLM_PROVIDER).
    Each provider has its own model mapping. Helper methods return the correct
    model for the active provider.
    """

    # Provider selection
    provider: str = Field(default="openai", description="LLM provider: openai, anthropic, gemini")

    # =========================================================================
    # OpenAI models
    # =========================================================================
    openai_default_model: str = Field(default="gpt-4.1", description="OpenAI default model for structured output and complex tasks")
    openai_mini_model: str = Field(default="gpt-4.1-mini", description="OpenAI lightweight model for simple text generation")
    openai_ranking_model: str = Field(default="gpt-4o", description="OpenAI model used for discussion ranking")

    # =========================================================================
    # Anthropic models
    # =========================================================================
    anthropic_default_model: str = Field(default="claude-sonnet-4-20250514", description="Anthropic default model for structured output and complex tasks")
    anthropic_mini_model: str = Field(default="claude-haiku-4-5-20251001", description="Anthropic lightweight model for simple text generation")
    anthropic_ranking_model: str = Field(default="claude-sonnet-4-20250514", description="Anthropic model used for discussion ranking")
    anthropic_max_tokens: int = Field(default=16384, description="Max tokens for Anthropic responses")

    # =========================================================================
    # Gemini models
    # =========================================================================
    gemini_default_model: str = Field(default="gemini-2.5-flash", description="Gemini default model for structured output and complex tasks")
    gemini_mini_model: str = Field(default="gemini-2.5-flash", description="Gemini lightweight model for simple text generation")
    gemini_ranking_model: str = Field(default="gemini-2.5-flash", description="Gemini model used for discussion ranking")

    # =========================================================================
    # Shared temperature settings (provider-agnostic)
    # =========================================================================
    temperature_json: float = Field(default=0.2, description="Temperature for structured JSON output (lower = more deterministic)")
    temperature_simple: float = Field(default=0.3, description="Temperature for simple text generation")
    temperature_ranking: float = Field(default=0.3, description="Temperature for ranking analysis")
    temperature_link_enricher: float = Field(default=0.2, description="Temperature for link enrichment")
    temperature_web_search: float = Field(default=0.0, description="Temperature for web search (deterministic)")
    temperature_translation: float = Field(default=0.3, description="Temperature for translation tasks")
    temperature_discussion_separation: float = Field(default=0.2, description="Temperature for discussion separation")

    model_config = SettingsConfigDict(env_prefix="LLM_")

    # =========================================================================
    # Provider-aware model accessors
    # =========================================================================

    @property
    def default_model(self) -> str:
        """Return the default model for the configured provider."""
        return self._get_model_for_provider("default")

    @property
    def default_model_mini(self) -> str:
        """Return the lightweight model for the configured provider."""
        return self._get_model_for_provider("mini")

    @property
    def ranking_model(self) -> str:
        """Return the ranking model for the configured provider."""
        return self._get_model_for_provider("ranking")

    @property
    def link_enricher_model(self) -> str:
        """Return the link enricher model (uses ranking model tier)."""
        return self._get_model_for_provider("ranking")

    @property
    def web_search_model(self) -> str:
        """Return the web search model (uses ranking model tier)."""
        return self._get_model_for_provider("ranking")

    @property
    def merger_model(self) -> str:
        """Return the merger model (uses default model tier)."""
        return self._get_model_for_provider("default")

    @property
    def merger_model_mini(self) -> str:
        """Return the lightweight merger model."""
        return self._get_model_for_provider("mini")

    def _get_model_for_provider(self, tier: str) -> str:
        """Return the model name for a given tier and the active provider.

        Args:
            tier: Model tier — 'default', 'mini', or 'ranking'

        Returns:
            Model identifier string
        """
        model_map = {
            "openai": {
                "default": self.openai_default_model,
                "mini": self.openai_mini_model,
                "ranking": self.openai_ranking_model,
            },
            "anthropic": {
                "default": self.anthropic_default_model,
                "mini": self.anthropic_mini_model,
                "ranking": self.anthropic_ranking_model,
            },
            "gemini": {
                "default": self.gemini_default_model,
                "mini": self.gemini_mini_model,
                "ranking": self.gemini_ranking_model,
            },
        }
        provider_models = model_map.get(self.provider)
        if not provider_models:
            raise ValueError(f"Unknown LLM provider '{self.provider}'. " f"Available: {list(model_map.keys())}")
        return provider_models[tier]


# ============================================================================
# EMBEDDING CONFIGURATION
# ============================================================================


class EmbeddingSettings(BaseSettings):
    """Embedding model and parameter configuration."""

    default_model: str = Field(default="text-embedding-3-small", description="Default embedding model")
    max_text_length: int = Field(default=8000, description="Maximum text length for embedding")
    batch_size: int = Field(default=100, description="Batch size for embedding multiple texts")
    discussion_batch_size: int = Field(default=50, description="Batch size for embedding discussions")

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")


# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================


class DatabaseSettings(BaseSettings):
    """MongoDB connection configuration."""

    host: str = Field(default="localhost", description="MongoDB host")
    port: str = Field(default="27017", description="MongoDB port")
    database: str = Field(default="langrag", description="Database name")
    username: str = Field(default="", description="MongoDB username")
    password: str = Field(default="", description="MongoDB password")
    uri: str | None = Field(default=None, description="Full MongoDB URI (overrides host/port if set)")

    # Connection pool settings
    max_pool_size: int = Field(default=50, description="Maximum connection pool size")
    min_pool_size: int = Field(default=10, description="Minimum connection pool size")
    server_selection_timeout_ms: int = Field(default=5000, description="Server selection timeout in milliseconds")

    # Vector index settings
    vector_index_dimension: int = Field(default=1536, description="Dimension for vector indexes (must match embedding model)")

    # MongoDB-Only Migration Feature Flags
    # These flags enable phased migration from file-based to MongoDB-only persistence
    enable_file_outputs: bool = Field(default=False, description="Generate output files (rollback flag for Phase 1)")
    use_file_based_history: bool = Field(default=False, description="Use file-based history loader instead of MongoDB (rollback flag for Phase 2)")
    enable_file_cache: bool = Field(default=False, description="Use file-based extraction cache instead of MongoDB (rollback flag for Phase 3)")
    enable_room_id_file_cache: bool = Field(default=True, description="Use file-based room ID cache as fallback when MongoDB cache misses")
    legacy_file_path_support: bool = Field(default=False, description="Keep file path fields in state schemas (rollback flag for Phase 4)")

    # MongoDB-specific configuration
    extraction_cache_ttl_days: int = Field(default=30, description="Extraction cache expiration in days")
    translation_cache_ttl_days: int = Field(default=30, description="Translation cache expiration in days")
    newsletter_history_limit: int = Field(default=10, description="Maximum newsletters for anti-repetition context")
    query_timeout_ms: int = Field(default=5000, description="MongoDB query timeout in milliseconds")

    model_config = SettingsConfigDict(env_prefix="MONGODB_")


# ============================================================================
# API CONFIGURATION
# ============================================================================


class APISettings(BaseSettings):
    """FastAPI and HTTP configuration."""

    host: str = Field(default="::", description="FastAPI host")
    port: int = Field(default=8000, description="FastAPI port")

    # CORS settings
    cors_allowed_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:3001"], description="Allowed CORS origins")

    # SSE streaming settings
    keepalive_interval_seconds: int = Field(default=15, description="SSE keepalive interval in seconds")
    min_event_timeout_seconds: float = Field(default=0.5, description="Minimum event timeout for SSE streaming")

    # Pagination defaults
    runs_limit_default: int = Field(default=50, description="Default limit for runs list")
    runs_limit_max: int = Field(default=200, description="Maximum limit for runs list")
    discussions_limit_default: int = Field(default=100, description="Default limit for discussions list")
    discussions_limit_max: int = Field(default=500, description="Maximum limit for discussions list")
    analytics_limit_default: int = Field(default=20, description="Default limit for analytics")
    analytics_limit_max: int = Field(default=100, description="Maximum limit for analytics")

    model_config = SettingsConfigDict(env_prefix="API_")


# ============================================================================
# BEEPER/MATRIX CONFIGURATION
# ============================================================================


class BeeperSettings(BaseSettings):
    """Beeper/Matrix extraction configuration."""

    base_url: str = Field(default="https://matrix.beeper.com", description="Beeper Matrix homeserver URL")
    matrix_sync_timeout_ms: int = Field(default=30000, description="Matrix sync timeout in milliseconds")
    message_batch_size: int = Field(default=100, description="Batch size for message fetching")
    process_timeout_seconds: int = Field(default=600, description="Timeout for extraction process in seconds")
    async_sleep_delay_seconds: float = Field(default=0.2, description="Delay between async operations")

    model_config = SettingsConfigDict(env_prefix="BEEPER_")


# ============================================================================
# PROCESSING CONFIGURATION
# ============================================================================


class ProcessingSettings(BaseSettings):
    """Message processing and batch configuration."""

    # Batch sizes
    translation_batch_size: int = Field(default=100, description="Batch size for translation")
    chunk_size_processing: int = Field(default=1000, description="Chunk size for message processing")

    # Text limits
    large_message_threshold: int = Field(default=500, description="Character threshold for large messages")
    debug_response_preview_length: int = Field(default=500, description="Length of response preview in debug logs")
    debug_response_preview_length_short: int = Field(default=200, description="Short length of response preview in debug logs")
    link_context_snippet_length: int = Field(default=200, description="Length of context snippet for links")
    nutshell_snippet_length: int = Field(default=50, description="Length of nutshell snippet")
    nutshell_truncate_length: int = Field(default=200, description="Truncation length for nutshell")
    title_preview_length: int = Field(default=30, description="Length of title preview")

    # LinkedIn limits
    linkedin_content_max_length: int = Field(default=2997, description="Maximum length for LinkedIn content")

    # Cache settings
    cache_key_hash_length: int = Field(default=16, description="Length of hash for cache keys")

    # Sender ID offset
    sender_id_start_offset: int = Field(default=1000, description="Starting offset for sender IDs")

    model_config = SettingsConfigDict(env_prefix="PROCESSING_")


# ============================================================================
# SLM (SMALL LANGUAGE MODEL) CONFIGURATION
# ============================================================================


class SLMSettings(BaseSettings):
    """Small Language Model configuration for local inference via Ollama."""

    enabled: bool = Field(default=False, description="Enable SLM-based message pre-filtering. Set to false to disable.")
    classifier_mode: str = Field(default="ollama", description="Classifier mode: 'deberta' (HTTP sidecar) | 'ollama' | 'disabled'")
    classifier_url: str = Field(default="http://slm-classifier:8090", description="DeBERTa classifier sidecar URL")
    provider: str = Field(default="ollama", description="SLM provider (currently only 'ollama' supported)")
    base_url: str = Field(default="http://ollama:11434", description="Ollama API base URL (use http://localhost:11434 outside Docker)")
    model: str = Field(default="phi3:mini", description="Ollama model name for message classification")
    fallback_model: str = Field(default="gemma2:2b", description="Fallback model if primary is unavailable")
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Minimum confidence for classification (below this → UNCERTAIN)")
    request_timeout_seconds: int = Field(default=60, description="Timeout for individual SLM requests")
    max_retries: int = Field(default=2, description="Maximum retries for SLM requests")
    batch_size: int = Field(default=10, description="Batch size for parallel message classification")
    temperature: float = Field(default=0.1, description="Temperature for SLM inference (lower = more deterministic)")
    max_tokens: int = Field(default=50, description="Maximum tokens for classification response")

    model_config = SettingsConfigDict(env_prefix="SLM_")


# ============================================================================
# VISION (IMAGE UNDERSTANDING) CONFIGURATION
# ============================================================================


class VisionSettings(BaseSettings):
    """Vision LLM configuration for image understanding in WhatsApp messages."""

    enabled: bool = Field(default=False, description="Master toggle for image extraction and vision description")
    provider: str = Field(default="openai", description="Vision LLM provider")
    model: str = Field(default="gpt-4.1-mini", description="Vision model for image description")
    max_images_per_chat: int = Field(default=50, description="Maximum images to process per chat")
    max_image_size_bytes: int = Field(default=10_485_760, description="Maximum image size in bytes (10MB)")
    description_max_tokens: int = Field(default=300, description="Max tokens for vision description response")
    temperature: float = Field(default=0.2, description="Temperature for vision description")
    download_timeout_seconds: int = Field(default=30, description="Timeout for image download")
    download_concurrency: int = Field(default=5, description="Max parallel image downloads")
    cache_ttl_days: int = Field(default=30, description="Vision description cache TTL in days")
    describe_scope: VisionDescribeScope = Field(default=VisionDescribeScope.ALL, description="Which images to describe: 'all' or 'featured_only'")
    media_base_dir: str = Field(default="data/media/images", description="Base directory for persistent media storage")

    model_config = SettingsConfigDict(env_prefix="VISION_")


# ============================================================================
# RANKING CONFIGURATION
# ============================================================================


class RankingSettings(BaseSettings):
    """Discussion ranking configuration."""

    default_top_k_discussions: int = Field(default=5, description="Default number of top discussions to feature")
    default_previous_newsletters_to_consider: int = Field(default=8, description="Default number of previous newsletters to load for anti-repetition. " "Set to 0 to disable anti-repetition.")
    default_similarity_threshold: str = Field(default=SimilarityThreshold.MODERATE, description="Default similarity threshold for merging")
    max_discussions_per_merge: int = Field(default=5, description="Maximum discussions per merge group")

    # MMR Diversity Settings
    enable_mmr_diversity: bool = Field(default=True, description="Enable MMR (Maximal Marginal Relevance) diversity reranking. " "When enabled, top-K discussions are selected to balance quality and diversity, " "preventing redundant discussions about the same topic.")
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0, description="MMR diversity weight parameter (0-1). " "Higher values favor quality, lower favor diversity. " "0.7 (default) = 70% quality, 30% diversity. " "1.0 = pure quality (disable diversity). " "0.5 = equal weight.")

    model_config = SettingsConfigDict(env_prefix="RANKING_")


# ============================================================================
# MAIN SETTINGS CLASS
# ============================================================================


class Settings(BaseSettings):
    """
    Main application settings.

    Aggregates all configuration sections into a single settings object.
    Use get_settings() to access the cached singleton instance.
    """

    # App metadata
    app_name: str = Field(default="LangRAG Newsletter", description="Application name")
    app_version: str = Field(default="2.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode flag")

    # Nested settings
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: APISettings = Field(default_factory=APISettings)
    beeper: BeeperSettings = Field(default_factory=BeeperSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    ranking: RankingSettings = Field(default_factory=RankingSettings)
    slm: SLMSettings = Field(default_factory=SLMSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)

    # Output directories
    output_base_dir: str = Field(default="output", description="Base output directory")
    logs_dir: str = Field(default="logs", description="Logs directory")

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_mongodb_url(self) -> str:
        """
        Get MongoDB connection URL.

        Priority:
        1. MONGODB_URI environment variable
        2. Build from host/port/username/password
        """
        # Check for explicit URI first
        uri = os.getenv("MONGODB_URI") or self.database.uri
        if uri:
            return uri

        # Build from components
        if self.database.username and self.database.password:
            return f"mongodb://{self.database.username}:{self.database.password}" f"@{self.database.host}:{self.database.port}"
        return f"mongodb://{self.database.host}:{self.database.port}"


@lru_cache
def get_settings() -> Settings:
    """
    Get the cached settings instance.

    Returns:
        Settings singleton instance
    """
    return Settings()


# ============================================================================
# BACKWARD COMPATIBILITY EXPORTS
# ============================================================================


# Export commonly used values for direct import
def get_default_llm_model() -> str:
    """Get the default LLM model."""
    return get_settings().llm.default_model


def get_default_llm_temperature() -> float:
    """Get the default LLM temperature for JSON output."""
    return get_settings().llm.temperature_json
