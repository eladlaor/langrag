"""
LangRAG Application Constants

This module defines all IMMUTABLE constants used throughout the application including:
- Community/chat name mappings
- Data source types
- Workflow names
- Operation types
- Summary formats
- Embedding model dimensions
- File naming patterns
- Algorithm parameters

All enums inherit from str for better JSON serialization and type safety.

NOTE: For CONFIGURABLE values (that may change per environment or user preference),
see config.py instead.
"""

from enum import StrEnum


# ============================================================================
# LLM MESSAGE ROLE CONSTANTS
# ============================================================================


class MessageRole(StrEnum):
    """Roles for LLM chat messages."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


# ============================================================================
# PROVIDER NAME CONSTANTS
# ============================================================================

DEFAULT_LLM_PROVIDER = "openai"
ANTHROPIC_LLM_PROVIDER = "anthropic"
GEMINI_LLM_PROVIDER = "gemini"


# ============================================================================
# WORKFLOW NAME CONSTANTS
# ============================================================================

WORKFLOW_NAME_NEWSLETTER_GENERATION = "newsletter_generation"


# ============================================================================
# OUTPUT PATH CONSTANTS
# ============================================================================

OUTPUT_BASE_DIR_NAME = "output"
OUTPUT_DIR_PERIODIC_NEWSLETTER = "generate_periodic_newsletter"


# ============================================================================
# FILE EXTENSION CONSTANTS
# ============================================================================

FILE_EXT_MD = ".md"
FILE_EXT_HTML = ".html"
FILE_EXT_JSON = ".json"


# ============================================================================
# AUTH CONSTANTS
# ============================================================================

AUTH_BEARER_PREFIX = "Bearer"


# ============================================================================
# BATCH TRANSLATION CONSTANTS
# ============================================================================

BATCH_TRANSLATE_CUSTOM_ID_PREFIX = "translate_batch_"
ANTHROPIC_TRANSLATION_TOOL_NAME = "translate_messages_response"


# ============================================================================
# LANGFUSE TAG CONSTANTS
# ============================================================================

TAG_NEWSLETTER = "newsletter"
TAG_PERIODIC = "periodic"
TAG_STREAMING = "streaming"


# ============================================================================
# BEEPER/WHATSAPP FILTER CONSTANTS
# ============================================================================

WHATSAPP_EVENT_TYPE_FILTERS = ["whatsapp", "beeper", "bridge"]

# Beeper/Bridge additional message event types
BEEPER_MESSAGE_EVENT_TYPE = "com.beeper.message"
BRIDGE_MESSAGE_EVENT_TYPE = "m.bridge.message"
WHATSAPP_MESSAGE_EVENT_TYPE = "m.whatsapp.message"
BRIDGE_MESSAGE_TYPES = [BEEPER_MESSAGE_EVENT_TYPE, BRIDGE_MESSAGE_EVENT_TYPE, WHATSAPP_MESSAGE_EVENT_TYPE]


# ============================================================================
# MATRIX PROTOCOL CONSTANTS
# ============================================================================

MATRIX_KEY_RELATES_TO = "m.relates_to"
MATRIX_KEY_IN_REPLY_TO = "m.in_reply_to"


# ============================================================================
# HTML LANGUAGE CONSTANTS
# ============================================================================

HTML_LANG_HEBREW = "he"
HTML_LANG_ENGLISH = "en"


# ============================================================================
# DIAGNOSTIC CATEGORY CONSTANTS
# ============================================================================

DIAGNOSTIC_CATEGORY_EXTRACTION = "extraction"
DIAGNOSTIC_CATEGORY_SLM_FILTER = "slm_filter"
DIAGNOSTIC_CATEGORY_LINK_ENRICHMENT = "link_enrichment"


# ============================================================================
# CONTENT TYPE CONSTANTS
# ============================================================================

CONTENT_TYPE_EVENT_STREAM = "text/event-stream"


# ============================================================================
# PLACEHOLDER CONSTANTS
# ============================================================================

OLDER_MESSAGE_PLACEHOLDER = "older-message"

DEFAULT_DATA_SOURCE_FALLBACK = "beeper"


# ============================================================================
# JINA API CONSTANTS
# ============================================================================

JINA_READER_URI_PREFIX = "https://r.jina.ai"
JINA_SEARCH_URI_PREFIX = "https://s.jina.ai"
JINA_RERANKER_URI = "https://api.jina.ai/v1/rerank"
JINA_RERANKER_MODEL = "jina-reranker-v2-base-multilingual"


# ============================================================================
# RENDERER CONSTANTS
# ============================================================================

LANGTALKS_DISPLAY_NAME = "LangTalks"
LANGTALKS_CHAT_NAME_DEFAULT = "LangTalks Community"
LANGTALKS_CHAT_PREFIX = "LangTalks - "
WHATSAPP_DISPLAY_NAME = "WhatsApp"
MCP_ISRAEL_DISPLAY_NAME = "MCP Israel"
MCP_ISRAEL_GROUP_NAME_DEFAULT = MCP_ISRAEL_DISPLAY_NAME

# LangTalks Newsletter Footer
LANGTALKS_WHATSAPP_JOIN_URL = "https://chat.whatsapp.com/ItqlTc288ulJSGKyWxrIck"
LANGTALKS_NEWSLETTER_SIGNUP_URL = "https://www.langtalks.ai/"
LANGTALKS_FOOTER_THANKS = "תודה שקראת!"
LANGTALKS_FOOTER_DESCRIPTION = "הניוזלטר מכיל סיכום של התוכן הכי מעניין מהדיונים בקבוצות הוואטסאפ השונות של LangTalks."
LANGTALKS_FOOTER_SHARE_CTA = "אפשר להעביר לחברים וחברות, ולהזמין אותם להצטרף לקהילה :)"
LANGTALKS_FOOTER_WHATSAPP_BUTTON = "הצטרפות לקבוצת הוואטסאפ"
LANGTALKS_FOOTER_SIGNUP_BUTTON = "הרשמה לניוזלטר"
LANGTALKS_WORTH_MENTIONING_HEADING = "🧰 נושאים נוספים שעלו"
LANGTALKS_ATTRIBUTION_PREFIX = "📅 הדיון המלא התחיל בתאריך:"


# LangTalks i18n strings for multilingual newsletter rendering
LANGTALKS_I18N = {
    "hebrew": {
        "footer_thanks": "תודה שקראת!",
        "footer_description": "הניוזלטר מכיל סיכום של התוכן הכי מעניין מהדיונים בקבוצות הוואטסאפ השונות של LangTalks.",
        "footer_share_cta": "אפשר להעביר לחברים וחברות, ולהזמין אותם להצטרף לקהילה :)",
        "footer_whatsapp_button": "הצטרפות לקבוצת הוואטסאפ",
        "footer_signup_button": "הרשמה לניוזלטר",
        "worth_mentioning_heading": "🧰 נושאים נוספים שעלו",
        "attribution_prefix": "📅 הדיון המלא התחיל בתאריך:",
        "merged_discussed_in": "📍 נדון ב-{count} קבוצות: {groups}",
        "merged_attribution_header": "📅 **נדון בקבוצות הבאות:**",
        "merged_started_at": "התחיל ב-{date}, {time}",
    },
    "english": {
        "footer_thanks": "Thanks for reading!",
        "footer_description": "This newsletter summarizes the most interesting discussions from the LangTalks WhatsApp groups.",
        "footer_share_cta": "Feel free to share with friends and invite them to join the community :)",
        "footer_whatsapp_button": "Join the WhatsApp group",
        "footer_signup_button": "Subscribe to the newsletter",
        "worth_mentioning_heading": "🧰 Additional Topics Worth Mentioning",
        "attribution_prefix": "📅 Full discussion started on:",
        "merged_discussed_in": "📍 Discussed in {count} groups: {groups}",
        "merged_attribution_header": "📅 **Discussed in the following groups:**",
        "merged_started_at": "started on {date}, {time}",
    },
}


def get_langtalks_i18n(desired_language: str) -> dict:
    """Get LangTalks i18n strings for the given language, defaulting to English."""
    if desired_language.lower() in HEBREW_LANGUAGE_CODES:
        return LANGTALKS_I18N["hebrew"]
    return LANGTALKS_I18N["english"]


# ============================================================================
# API ROUTE CONSTANTS
# ============================================================================

# API Prefixes
API_V1_PREFIX = "/api"
API_MONGODB_PREFIX = "/api/mongodb"

# Root Routes
ROUTE_ROOT = "/"
ROUTE_HEALTH = "/health"
ROUTE_DOCS = "/docs"
ROUTE_REDOC = "/redoc"

# Newsletter Routes (applied after /api prefix)
ROUTE_GENERATE_PERIODIC_NEWSLETTER = "/generate_periodic_newsletter"
ROUTE_GENERATE_PERIODIC_NEWSLETTER_STREAM = "/generate_periodic_newsletter/stream"
ROUTE_DISCUSSION_SELECTION = "/discussion_selection/{run_directory:path}"
ROUTE_SAVE_DISCUSSION_SELECTIONS = "/save_discussion_selections"
ROUTE_GENERATE_NEWSLETTER_PHASE2 = "/generate_newsletter_phase2"
ROUTE_NEWSLETTER_FILE_CONTENT = "/newsletter_file_content"
ROUTE_NEWSLETTER_HTML_VIEWER = "/newsletter_html_viewer"
ROUTE_BATCH_JOBS_BY_ID = "/batch_jobs/{job_id}"
ROUTE_BATCH_JOBS = "/batch_jobs"

# Runs Routes (applied after /api prefix)
ROUTE_RUNS = "/runs"
ROUTE_RUN_BY_ID = "/runs/{run_id}"
ROUTE_RUN_NEWSLETTER = "/runs/{run_id}/newsletter"
ROUTE_RUN_NEWSLETTER_RAW = "/runs/{run_id}/newsletter/raw"
ROUTE_RUN_DISCUSSIONS = "/runs/{run_id}/discussions"
ROUTE_RUN_POLLS = "/runs/{run_id}/polls"
ROUTE_SEARCH_DISCUSSIONS = "/search/discussions"
ROUTE_RUNS_STATS = "/runs/stats"

# MongoDB Routes (DEPRECATED - merged into observability/runs.py with standard routes)
# Keeping for backward compatibility during migration
ROUTE_MONGODB_RUNS = "/mongodb/runs"
ROUTE_MONGODB_RUN_BY_ID = "/mongodb/runs/{run_id}"
ROUTE_MONGODB_RUN_MESSAGES = "/mongodb/runs/{run_id}/messages"
ROUTE_MONGODB_RUN_DISCUSSIONS = "/mongodb/runs/{run_id}/discussions"
ROUTE_MONGODB_RUN_DIAGNOSTICS = "/mongodb/runs/{run_id}/diagnostics"
ROUTE_MONGODB_RUN_POLLS = "/mongodb/runs/{run_id}/polls"
ROUTE_MONGODB_STATS = "/mongodb/stats"

# RAG Routes (applied after /api prefix)
ROUTE_RAG_CHAT_STREAM = "/rag/chat/stream"
ROUTE_RAG_SESSIONS = "/rag/sessions"
ROUTE_RAG_SESSION_BY_ID = "/rag/sessions/{session_id}"
ROUTE_RAG_INGEST_PODCASTS = "/rag/ingest/podcasts"
ROUTE_RAG_INGEST_PODCASTS_SCAN = "/rag/ingest/podcasts/scan"
ROUTE_RAG_SOURCES_STATS = "/rag/sources/stats"
ROUTE_RAG_EVALUATIONS = "/rag/evaluations/{session_id}"

# Metrics Routes (no prefix)
ROUTE_METRICS = "/metrics"

# External Service URLs
N8N_LINKEDIN_WEBHOOK_URL = "http://n8n:5678/webhook/linkedin-draft"


# ============================================================================
# APPLICATION METADATA CONSTANTS
# ============================================================================

APP_NAME = "LangRAG API"
APP_DISPLAY_NAME = "LangRAG"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Newsletter generation from WhatsApp group chats using LangGraph workflows"


# ============================================================================
# HTTP STATUS CODE CONSTANTS
# ============================================================================

HTTP_STATUS_OK = 200
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_INTERNAL_SERVER_ERROR = 500


# ============================================================================
# MONGODB COLLECTION CONSTANTS
# ============================================================================

COLLECTION_RUNS = "runs"
COLLECTION_MESSAGES = "messages"
COLLECTION_DISCUSSIONS = "discussions"
COLLECTION_CACHE = "cache"
COLLECTION_BATCH_JOBS = "batch_jobs"
COLLECTION_NEWSLETTERS = "newsletters"
COLLECTION_SCHEDULED_NEWSLETTERS = "scheduled_newsletters"
COLLECTION_EXTRACTION_CACHE = "extraction_cache"
COLLECTION_ROOM_ID_CACHE = "room_id_cache"
COLLECTION_IMAGES = "images"
COLLECTION_TRANSLATION_CACHE = "translation_cache"
COLLECTION_SENDER_MAPS = "sender_maps"
COLLECTION_POLLS = "polls"
COLLECTION_RAG_CHUNKS = "rag_chunks"
COLLECTION_RAG_CONVERSATIONS = "rag_conversations"
COLLECTION_RAG_EVALUATIONS = "rag_evaluations"

# RAG Vector Search Index Name (must be created manually in MongoDB Atlas / mongot)
RAG_VECTOR_INDEX_NAME = "rag_chunk_embeddings"

# Default TTL for translation cache entries (days)
DEFAULT_TRANSLATION_CACHE_TTL_DAYS = 30


# ============================================================================
# TIMEOUT CONSTANTS (seconds)
# ============================================================================

TIMEOUT_HTTP_REQUEST = 30  # HTTP requests (n8n webhook, Beeper API)
TIMEOUT_CACHE_OPERATION = 10  # Cache get/set operations
TIMEOUT_PROGRESS_QUEUE = 1.0  # Progress queue operations
TIMEOUT_BATCH_WORKER = 30  # Batch worker HTTP client


# ============================================================================
# EMBEDDING MODEL CONSTANTS
# ============================================================================

# OpenAI embedding models and their dimensions
EMBEDDING_MODEL_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

# Default embedding model name
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Default embedding dimension (must match the default model in config.py)
DEFAULT_EMBEDDING_DIMENSION = 1536


# ============================================================================
# ENCODING CONSTANTS
# ============================================================================

# Tiktoken encoding for token counting
TIKTOKEN_ENCODING_NAME = "cl100k_base"


# ============================================================================
# FILE NAMING CONSTANTS
# ============================================================================

# Cache file names
CACHE_FILENAME_CHAT_ROOM_MAPPING = "chat_name_to_room_id_cache.json"

# Output file patterns
OUTPUT_FILESTEM_NEWSLETTER = "newsletter_summary"
OUTPUT_FILENAME_NEWSLETTER_JSON = f"{OUTPUT_FILESTEM_NEWSLETTER}{FILE_EXT_JSON}"
OUTPUT_FILENAME_NEWSLETTER_MD = f"{OUTPUT_FILESTEM_NEWSLETTER}{FILE_EXT_MD}"
OUTPUT_FILENAME_NEWSLETTER_HTML = f"{OUTPUT_FILESTEM_NEWSLETTER}{FILE_EXT_HTML}"
OUTPUT_FILESTEM_ENRICHED = "enriched_newsletter"
OUTPUT_FILESTEM_ENRICHED_SUMMARY = "enriched_newsletter_summary"
OUTPUT_FILENAME_ENRICHED_JSON = f"{OUTPUT_FILESTEM_ENRICHED}{FILE_EXT_JSON}"
OUTPUT_FILENAME_ENRICHED_MD = f"{OUTPUT_FILESTEM_ENRICHED}{FILE_EXT_MD}"
OUTPUT_FILENAME_ENRICHED_HTML = f"{OUTPUT_FILESTEM_ENRICHED}{FILE_EXT_HTML}"
OUTPUT_FILENAME_ENRICHED_SUMMARY_JSON = f"{OUTPUT_FILESTEM_ENRICHED_SUMMARY}{FILE_EXT_JSON}"
OUTPUT_FILENAME_ENRICHED_SUMMARY_MD = f"{OUTPUT_FILESTEM_ENRICHED_SUMMARY}{FILE_EXT_MD}"
OUTPUT_FILENAME_ENRICHED_SUMMARY_HTML = f"{OUTPUT_FILESTEM_ENRICHED_SUMMARY}{FILE_EXT_HTML}"
OUTPUT_FILENAME_RANKED_DISCUSSIONS = "ranked_discussions.json"
OUTPUT_FILENAME_USER_SELECTIONS = "user_selections.json"
OUTPUT_FILENAME_AGGREGATED_DISCUSSIONS = "all_chats_aggregated.json"
OUTPUT_FILENAME_MESSAGES_PROCESSED = "messages_processed.json"
OUTPUT_FILENAME_POLLS = "polls.json"
OUTPUT_FILENAME_MESSAGES_TRANSLATED = "messages_translated_to_english.json"
OUTPUT_FILENAME_SEPARATE_DISCUSSIONS = "separate_discussions.json"
OUTPUT_FILENAME_DISCUSSIONS_RANKING = "discussions_ranking.json"
OUTPUT_FILENAME_CROSS_CHAT_RANKING = "cross_chat_ranking.json"
OUTPUT_FILENAME_CONSOLIDATED_NEWSLETTER_JSON = "consolidated_newsletter.json"
OUTPUT_FILENAME_CONSOLIDATED_NEWSLETTER_MD = "consolidated_newsletter.md"
OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_JSON = "enriched_consolidated.json"
OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_MD = "enriched_consolidated.md"
OUTPUT_FILENAME_TRANSLATED_CONSOLIDATED_MD = "translated_consolidated.md"
OUTPUT_FILENAME_SENDER_MAP = "sender_map.json"
OUTPUT_FILENAME_MESSAGE_STATS = "message_stats.json"
OUTPUT_FILENAME_MESSAGES_PROCESSED_TEMP = "messages_processed_temp.json"
OUTPUT_FILENAME_SELECTED_DISCUSSIONS = "selected_discussions.json"
OUTPUT_FILENAME_MERGED_DISCUSSIONS = "merged_discussions.json"
OUTPUT_FILENAME_AGGREGATED_LINKS = "aggregated_links.json"
OUTPUT_FILENAME_IMAGE_MANIFEST = "image_manifest.json"

# Image-to-discussion association caps (prevent prompt bloat)
MAX_IMAGES_PER_DISCUSSION = 3
MAX_IMAGES_TOTAL = 15


# ============================================================================
# DIRECTORY CONSTANTS
# ============================================================================

# Output directory names
DIR_NAME_CONSOLIDATED = "consolidated"
DIR_NAME_PER_CHAT = "per_chat"
DIR_NAME_NEWSLETTER = "newsletter"
DIR_NAME_LINK_ENRICHMENT = "link_enrichment"
DIR_NAME_FINAL_TRANSLATION = "final_translation"
DIR_NAME_DISCUSSIONS_FOR_SELECTION = "discussions_for_selection"
DIR_NAME_AFTER_SELECTION = "after_selection"
DIR_NAME_AGGREGATED_DISCUSSIONS = "aggregated_discussions"
DIR_NAME_EXTRACTED = "extracted"
DIR_NAME_PREPROCESSED = "preprocessed"
DIR_NAME_TRANSLATED = "translated"
DIR_NAME_SEPARATE_DISCUSSIONS = "separate_discussions"
DIR_NAME_DISCUSSIONS_RANKING = "discussions_ranking"
DIR_NAME_IMAGES = "images"
DIR_NAME_PODCASTS = "podcasts"

# RAG citation snippet max length
RAG_CITATION_SNIPPET_MAX_LENGTH = 200

# RAG vector search score field (added by $vectorSearch $meta)
RAG_SEARCH_SCORE_FIELD = "search_score"


# ============================================================================
# TIMESTAMP CONSTANTS
# ============================================================================

# Milliseconds to seconds conversion factor
MS_TO_SECONDS_MULTIPLIER = 1000

# Display timezone for newsletter timestamps (Israel Standard/Daylight Time)
DISPLAY_TIMEZONE = "Asia/Jerusalem"


# ============================================================================
# PROGRESS TRACKING CONSTANTS
# ============================================================================

# Progress queue maximum size
PROGRESS_QUEUE_MAX_SIZE = 1000

# Community structure with grouped chats
COMMUNITY_STRUCTURE = {
    "langtalks": {"LangTalks Community": ["LangTalks Community", "LangTalks Community 2", "LangTalks Community 3", "LangTalks Community 4", "LangTalks - Code Generation Agents", "LangTalks - English", "LangTalks - AI driven coding", "LangTalks AI-SDLC"]},
    "mcp_israel": {"MCP Israel": ["MCP Israel", "MCP Israel #2", "A2A Israel", "MCP-UI"]},
    "n8n_israel": {"n8n Israel": ["n8n israel - Main 1", "n8n israel - Main 2", "n8n Israel - Main 3"]},
    "ai_transformation_guild": {"AI Transformation Guild": ["AI Transformation Guild"]},
    "ail": {"AIL - AI Leaders Community": ["AIL - AI Leaders Community"]},
}

# Flattened version for backward compatibility
KNOWN_WHATSAPP_CHAT_NAMES = {community_key: [chat for group_chats in community_groups.values() for chat in group_chats] for community_key, community_groups in COMMUNITY_STRUCTURE.items()}

# All known chat names as a flat set (for factory registrations, validation, etc.)
ALL_KNOWN_CHAT_NAMES: set[str] = {chat for community_chats in KNOWN_WHATSAPP_CHAT_NAMES.values() for chat in community_chats}


class DataSources(StrEnum):
    WHATSAPP_GROUP_CHAT_MESSAGES = "whatsapp_group_chat_messages"


class WorkflowNames(StrEnum):
    PERIODIC_NEWSLETTER = "periodic_newsletter"


class PreprocessingOperations(StrEnum):
    PARSE_AND_STANDARDIZE_RAW_WHATSAPP_MESSAGES_WITH_STATS = "parse_and_standardize_raw_whatsapp_messages_with_stats"
    TRANSLATE_WHATSAPP_GROUP_CHAT_MESSAGES = "translate_whatsapp_group_chat_messages"
    SEPARATE_WHATSAPP_GROUP_MESSAGE_DISCUSSIONS = "separate_whatsapp_group_message_discussions"


class ContentGenerationOperations(StrEnum):
    GENERATE_NEWSLETTER_SUMMARY = "generate_newsletter_summary"
    TRANSLATE_SUMMARY = "translate_summary"


class SummaryFormats(StrEnum):
    MCP_ISRAEL_FORMAT = "mcp_israel_format"
    LANGTALKS_FORMAT = "langtalks_format"
    WHATSAPP_FORMAT = "whatsapp_format"


class LlmInputPurposes(StrEnum):
    SEPARATE_DISCUSSIONS = "separate_whatsapp_group_message_discussions"
    TRANSLATE_WHATSAPP_GROUP_MESSAGES = "translate_whatsapp_group_messages"
    TRANSLATE_SUMMARY = "translate_summary"
    GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER = "generate_content_wa_community_langtalks_newsletter"

    # Anti-repetition validation
    CHECK_REPETITION = "check_repetition"

    # Vision purposes
    DESCRIBE_IMAGE = "describe_image"

    # Discussion merging purposes
    MERGE_SIMILAR_DISCUSSIONS = "merge_similar_discussions"
    GENERATE_MERGED_TITLE = "generate_merged_title"
    SYNTHESIZE_MERGED_NUTSHELL = "synthesize_merged_nutshell"


class NodeNames:
    class SingleChatAnalyzer(StrEnum):
        SETUP_DIRECTORIES = "setup_directories"
        EXTRACT_MESSAGES = "extract_messages"
        SLM_PREFILTER = "slm_prefilter"
        EXTRACT_IMAGES = "extract_images"
        PREPROCESS_MESSAGES = "preprocess_messages"
        TRANSLATE_MESSAGES = "translate_messages"
        SEPARATE_DISCUSSIONS = "separate_discussions"
        SLM_ENRICHMENT = "slm_enrichment"
        RANK_DISCUSSIONS = "rank_discussions"
        ASSOCIATE_IMAGES = "associate_images"
        GENERATE_CONTENT = "generate_content"
        ENRICH_WITH_LINKS = "enrich_with_links"
        TRANSLATE_FINAL_SUMMARY = "translate_final_summary"

    class MultiChatConsolidator(StrEnum):
        ENSURE_VALID_SESSION = "ensure_valid_session"
        DISPATCH_CHATS = "dispatch_chats"
        CHAT_WORKER = "chat_worker"
        AGGREGATE_RESULTS = "aggregate_results"
        OUTPUT_HANDLER = "output_handler"
        SETUP_CONSOLIDATED_DIRECTORIES = "setup_consolidated_directories"
        CONSOLIDATE_DISCUSSIONS = "consolidate_discussions"
        MERGE_SIMILAR_DISCUSSIONS = "merge_similar_discussions"
        RANK_CONSOLIDATED_DISCUSSIONS = "rank_consolidated_discussions"
        SET_FOR_HUMAN_IN_THE_LOOP = "set_for_human_in_the_loop"
        GENERATE_CONSOLIDATED_NEWSLETTER = "generate_consolidated_newsletter"
        RELATED_LINKS_ENRICHMENT = "related_links_enrichment"
        TRANSLATE_CONSOLIDATED_NEWSLETTER = "translate_consolidated_newsletter"

    class DiscussionsRanker(StrEnum):
        ANALYZE_DISCUSSIONS = "analyze_discussions"

    class LinkEnricher(StrEnum):
        EXTRACT_LINKS_FROM_MESSAGES = "extract_links_from_messages"
        SEARCH_WEB_FOR_TOPICS = "search_web_for_topics"
        AGGREGATE_LINKS = "aggregate_links"
        INSERT_LINKS_INTO_CONTENT = "insert_links_into_content"

    class RAGConversation(StrEnum):
        RETRIEVE = "retrieve"
        GENERATE = "generate"
        EVALUATE = "evaluate"


class GenericEdgeResolutions(StrEnum):
    RESOLVED = "resolved"
    NOT_RESOLVED = "not_resolved"


# ============================================================================
# MATRIX/BEEPER EVENT TYPE CONSTANTS
# ============================================================================


class MatrixEventType(StrEnum):
    """Matrix protocol event types used in message decryption."""

    ROOM_ENCRYPTED = "m.room.encrypted"
    ROOM_MESSAGE = "m.room.message"
    ROOM_NAME = "m.room.name"
    POLL_RESPONSE = "org.matrix.msc3381.poll.response"


# ============================================================================
# POLL CONTENT CONSTANTS
# ============================================================================

POLL_START_CONTENT_KEY = "org.matrix.msc3381.poll.start"
POLL_RESPONSE_CONTENT_KEY = "org.matrix.msc3381.poll.response"
POLL_WHATSAPP_CONTENT_KEY = "fi.mau.whatsapp.poll"
POLL_TEXT_KEY = "org.matrix.msc1767.text"
POLL_FALLBACK_SUFFIX = "(This message is a poll. Please open WhatsApp to vote.)"


class MatrixMessageType(StrEnum):
    """Matrix content.msgtype values for different media types."""

    TEXT = "m.text"
    IMAGE = "m.image"
    VIDEO = "m.video"
    FILE = "m.file"
    AUDIO = "m.audio"


class VisionDescribeScope(StrEnum):
    """Scope for vision image description."""

    ALL = "all"
    FEATURED_ONLY = "featured_only"


# Vision cache namespace
VISION_CACHE_PREFIX = "vision_describe"

# OpenAI vision detail level (controls token usage per image)
OPENAI_VISION_DETAIL_LOW = "low"

# MIME type to file extension mapping for images
MIME_TO_EXTENSION: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}
DEFAULT_IMAGE_EXTENSION = ".bin"


class MatrixEncryptionAlgorithm(StrEnum):
    """Matrix encryption algorithms."""

    MEGOLM_V1_AES_SHA2 = "m.megolm.v1.aes-sha2"


class DecryptionMethod(StrEnum):
    """Decryption methods for encrypted Matrix messages."""

    SERVER_BACKUP = "server_backup"
    PERSISTENT_SESSION = "persistent_session"
    MANUAL_EXPORT = "manual_export"
    HYBRID = "hybrid"


# Matrix content format
MATRIX_CONTENT_FORMAT_HTML = "org.matrix.custom.html"


# ============================================================================
# OUTPUT ACTION CONSTANTS
# ============================================================================


class OutputAction(StrEnum):
    """Output actions for newsletter delivery."""

    SAVE_LOCAL = "save_local"
    WEBHOOK = "webhook"
    SEND_EMAIL = "send_email"
    SEND_SUBSTACK = "send_substack"
    SEND_LINKEDIN = "send_linkedin"


# Universal output actions allowed for all communities
UNIVERSAL_OUTPUT_ACTIONS = [
    OutputAction.SAVE_LOCAL,
    OutputAction.WEBHOOK,
    OutputAction.SEND_EMAIL,
]

# Community-specific publishing platform actions.
# Only these communities can use these output actions beyond the universal ones.
COMMUNITY_ALLOWED_OUTPUT_ACTIONS = {
    "langtalks": [OutputAction.SEND_SUBSTACK],
    "mcp_israel": [OutputAction.SEND_LINKEDIN],
    "n8n_israel": [],
    "ai_transformation_guild": [],
}


# ============================================================================
# HTTP CONSTANTS
# ============================================================================

# Header names
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_CONTENT_LENGTH = "content-length"
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"

# Content types
CONTENT_TYPE_JSON = "application/json"


# ============================================================================
# ENVIRONMENT VARIABLE NAME CONSTANTS
# ============================================================================

ENV_APP_BASE_URL = "APP_BASE_URL"
ENV_DEFAULT_EMAIL_RECIPIENT = "DEFAULT_EMAIL_RECIPIENT"
ENV_BEEPER_ACCESS_TOKEN = "BEEPER_ACCESS_TOKEN"


# ============================================================================
# LANGUAGE CONSTANTS
# ============================================================================

# Default languages
DEFAULT_LANGUAGE = "english"
DEFAULT_HTML_LANGUAGE = "hebrew"

# Language codes for comparison
ENGLISH_LANGUAGE_CODES = ["english", "en"]
HEBREW_LANGUAGE_CODES = ["hebrew", "עברית"]


# ============================================================================
# FILE PATH CONSTANTS (SECRETS)
# ============================================================================

# Default secret file paths (can be overridden via environment variables)
DEFAULT_BEEPER_MATRIX_STORE_PATH = "./secrets/beeper_matrix_store"
DEFAULT_SERVER_BACKUP_KEYS_PATH = "./secrets/server_backup_keys.json"
DEFAULT_EXPORTED_KEYS_PATH = "./secrets/exported_keys/element-keys.txt"
DEFAULT_DECRYPTED_KEYS_PATH = "./secrets/decrypted-keys.json"

# Docker data mount path
DOCKER_DATA_MOUNT_PATH = "/app/data"


# ============================================================================
# MESSAGE EXTRACTION CONSTANTS
# ============================================================================

# Directory names for message storage
DIR_NAME_ENCRYPTED_MESSAGES = "encrypted_messages"
DIR_NAME_DECRYPTED_MESSAGES = "decrypted_messages"

# Anonymization prefix
ANONYMIZED_USER_ID_PREFIX = "user_"


# ============================================================================
# LLM CALL TYPE ENUMS
# ============================================================================


class LLMCallType(StrEnum):
    """Types of LLM calls for method dispatch."""

    BASIC = "basic"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    JSON_OUTPUT = "json_output"


# ============================================================================
# PROGRESS TRACKING ENUMS
# ============================================================================


class ProgressEventType(StrEnum):
    """Event types for SSE progress streaming."""

    WORKFLOW_STARTED = "workflow_started"
    CHAT_STARTED = "chat_started"
    STAGE_PROGRESS = "stage_progress"
    CHAT_COMPLETED = "chat_completed"
    CHAT_FAILED = "chat_failed"
    CONSOLIDATION_STARTED = "consolidation_started"
    CONSOLIDATION_COMPLETED = "consolidation_completed"
    HITL_SELECTION_READY = "hitl_selection_ready"
    WORKFLOW_COMPLETED = "workflow_completed"
    ERROR = "error"


class StageStatus(StrEnum):
    """Status values for workflow stages."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStage(StrEnum):
    """Pipeline stages for newsletter generation."""

    EXTRACT_MESSAGES = "extract_messages"
    EXTRACT_IMAGES = "extract_images"
    PREPROCESS_MESSAGES = "preprocess_messages"
    TRANSLATE_MESSAGES = "translate_messages"
    SEPARATE_DISCUSSIONS = "separate_discussions"
    RANK_DISCUSSIONS = "rank_discussions"
    GENERATE_CONTENT = "generate_content"
    ENRICH_WITH_LINKS = "enrich_with_links"
    TRANSLATE_FINAL_SUMMARY = "translate_final_summary"

    # Consolidation stages
    SETUP_CONSOLIDATED_DIRECTORIES = "setup_consolidated_directories"
    CONSOLIDATE_DISCUSSIONS = "consolidate_discussions"
    RANK_CONSOLIDATED_DISCUSSIONS = "rank_consolidated_discussions"
    GENERATE_CONSOLIDATED_NEWSLETTER = "generate_consolidated_newsletter"
    ENRICH_CONSOLIDATED_NEWSLETTER = "enrich_consolidated_newsletter"
    TRANSLATE_CONSOLIDATED_NEWSLETTER = "translate_consolidated_newsletter"


# ============================================================================
# MESSAGING PLATFORM CONSTANTS
# ============================================================================

# Messaging platforms
MESSAGING_PLATFORM_WHATSAPP = "whatsapp"

# Extraction strategies
EXTRACTION_STRATEGY_GROUP_CHAT = "group_chat_summary"


# ============================================================================
# SIMILARITY THRESHOLD ENUMS
# ============================================================================


class SimilarityThreshold(StrEnum):
    """Thresholds for discussion merging similarity."""

    STRICT = "strict"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


# ============================================================================
# FILE FORMAT CONSTANTS
# ============================================================================


class FileFormat(StrEnum):
    """File format types for content export."""

    JSON = "json"
    MARKDOWN = "markdown"
    HTML = "html"


class LogFormat(StrEnum):
    """Log format types for output configuration."""

    JSON = "json"
    PRETTY = "pretty"


# ============================================================================
# EMAIL PROVIDER CONSTANTS
# ============================================================================


class EmailProvider(StrEnum):
    """Email service providers."""

    GMAIL = "gmail"
    SENDGRID = "sendgrid"


# ============================================================================
# EXTRACTION CONSTANTS
# ============================================================================


class DayBoundary(StrEnum):
    """Day boundary types for message extraction."""

    START = "start"
    END = "end"


# Standard date format for consistency
DATE_FORMAT_ISO = "%Y-%m-%d"


# ============================================================================
# NEWSLETTER VERSION & TYPE CONSTANTS
# ============================================================================


class NewsletterVersionType(StrEnum):
    """Newsletter version types for MongoDB storage."""

    ORIGINAL = "original"
    ENRICHED = "enriched"
    TRANSLATED = "translated"


class NewsletterType(StrEnum):
    """Newsletter types (single chat vs consolidated)."""

    PER_CHAT = "per_chat"
    CONSOLIDATED = "consolidated"


class DiscussionCategory(StrEnum):
    """Discussion ranking categories."""

    FEATURED = "featured"
    BRIEF_MENTION = "brief_mention"
    SKIP = "skip"


class RepetitionScore(StrEnum):
    """Repetition detection scores."""

    NONE = "none"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ============================================================================
# RUN STATUS ENUMS
# ============================================================================


class RunStatus(StrEnum):
    """Status values for pipeline runs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BatchJobStatus(StrEnum):
    """Status values for batch processing jobs."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NewsletterStatus(StrEnum):
    """Status values for newsletter documents."""

    DRAFT = "draft"
    ENRICHED = "enriched"
    COMPLETED = "completed"


class ScheduleRunStatus(StrEnum):
    """Status values for scheduled newsletter runs."""

    SUCCESS = "success"
    FAILED = "failed"


class TextDirection(StrEnum):
    """Text direction for HTML rendering."""

    RTL = "rtl"
    LTR = "ltr"


class SearchMethod(StrEnum):
    """Search methods for discussion search."""

    VECTOR = "vector_search"
    FULL_TEXT = "text_search"


# ============================================================================
# RAG (Retrieval-Augmented Generation) CONSTANTS
# ============================================================================


class ContentSourceType(StrEnum):
    """Content source types for RAG ingestion."""

    PODCAST = "podcast"
    NEWSLETTER = "newsletter"
    CHAT_MESSAGE = "chat_message"


class RAGEventType(StrEnum):
    """SSE event types for RAG chat streaming."""

    TOKEN = "token"
    CITATION = "citation"
    DONE = "done"
    ERROR = "error"
    EVALUATION_SCORE = "evaluation_score"


class EvaluationMetric(StrEnum):
    """DeepEval metric types for RAG evaluation."""

    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCY = "answer_relevancy"
    CONTEXTUAL_RELEVANCY = "contextual_relevancy"
    HALLUCINATION = "hallucination"


class EvaluationStatus(StrEnum):
    """Status values for RAG evaluation runs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TranscriptionProvider(StrEnum):
    """Transcription provider types for RAG audio processing."""

    OPENAI = "openai"
    LOCAL = "local"


class RunType(StrEnum):
    """Types of newsletter generation runs."""

    PERIODIC = "periodic"


# ============================================================================
# CONTENT GENERATOR RESULT KEY CONSTANTS
# ============================================================================

RESULT_KEY_NEWSLETTER_SUMMARY_PATH = "newsletter_summary_path"
RESULT_KEY_MARKDOWN_PATH = "markdown_path"
RESULT_KEY_HTML_PATH = "html_path"


# ============================================================================
# SCHEDULE FIELD CONSTANTS
# ============================================================================

SCHEDULE_FIELD_RUN_TIME = "run_time"
SCHEDULE_FIELD_INTERVAL_DAYS = "interval_days"
SCHEDULE_DEFAULT_RUN_TIME = "08:00"


# ============================================================================
# HITL KEY CONSTANTS
# ============================================================================

HITL_KEY_PHASE_1_COMPLETE = "phase_1_complete"
HITL_KEY_PHASE_2_READY = "phase_2_ready"
HITL_KEY_TIMEOUT_DEADLINE = "timeout_deadline"
HITL_SUPPORTED_FORMATS = [SummaryFormats.LANGTALKS_FORMAT, SummaryFormats.MCP_ISRAEL_FORMAT, SummaryFormats.WHATSAPP_FORMAT]


# ============================================================================
# SENTINEL CONSTANTS
# ============================================================================

CONSOLIDATED_CHAT_SENTINEL = "__consolidated__"
UNKNOWN_CHAT_NAME = "unknown"
NO_CONTENT_FOR_SECTION = "No content for this section"
