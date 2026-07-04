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

from datetime import UTC, datetime
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

# Bare (dot-less) newsletter output extensions, used to probe for generated
# newsletter files on disk via f"{stem}.{ext}". Order is the lookup preference.
NEWSLETTER_OUTPUT_EXTENSIONS = ["json", "md", "html"]


# ============================================================================
# AUTH CONSTANTS
# ============================================================================

AUTH_BEARER_PREFIX = "Bearer"

# --- Shared-password UI login gate (Fernet session cookie) ---
# These are a SEPARATE auth surface from the RAG_API_KEY_* public-API keys.
# Route paths are applied AFTER the API_V1_PREFIX ("/api") when mounted.
ROUTE_AUTH_PREFIX = "/auth"
ROUTE_AUTH_LOGIN = "/auth/login"
ROUTE_AUTH_LOGOUT = "/auth/logout"
ROUTE_AUTH_SESSION = "/auth/session"

# Admin-only user management routes (mounted after API_V1_PREFIX, like the
# auth routes above). Every route on this surface requires an ADMIN session.
ROUTE_AUTH_USERS = "/auth/users"
ROUTE_AUTH_USER_BY_ID = "/auth/users/{user_id}"
ROUTE_AUTH_USER_PASSWORD = "/auth/users/{user_id}/password"
ROUTE_AUTH_USER_DISABLE = "/auth/users/{user_id}/disable"

# Public podcast-MCP key self-service routes (mounted after API_V1_PREFIX).
# BOTH are fully PUBLIC (no session cookie, no API key): they are how a stranger
# obtains a key in the first place. request-key always returns 202 with a generic
# message (no email enumeration); verify exchanges a valid token for a freshly
# minted PODCAST_QUERY-scoped key (shown once). These MUST stay outside any
# session-auth gate. Contract is frozen against the langrag.ai/podcasts frontend.
ROUTE_PODCAST_CONSUMER_REQUEST_KEY = "/podcasts/consumers/request-key"
ROUTE_PODCAST_CONSUMER_VERIFY = "/podcasts/consumers/verify"

# Self-signup + access-request + Google OAuth routes (mounted after
# API_V1_PREFIX). The signup, access-request POST, config, and Google routes
# are PUBLIC (unauthenticated); the access-request GET is ADMIN-only. The
# Google login/callback constants are defined now even though the OAuth
# endpoints are wired in a later slice (deferred until a Google client exists).
ROUTE_AUTH_SIGNUP = "/auth/signup"
ROUTE_AUTH_GOOGLE_LOGIN = "/auth/google/login"
ROUTE_AUTH_GOOGLE_CALLBACK = "/auth/google/callback"
ROUTE_AUTH_ACCESS_REQUESTS = "/auth/access-requests"
ROUTE_AUTH_CONFIG = "/auth/config"

# Per-user RAG preferences (saved MMR diversity setting). GET resolves the
# saved value (or config default when unset); PUT persists a new value.
ROUTE_USER_RAG_PREFERENCES = "/users/me/rag-preferences"

# Per-user agent API key management. Cookie-session gated (a user has no agent
# API key before minting one), distinct from the X-API-Key gate on /api/agent/*.
ROUTE_USER_AGENT_KEYS = "/users/me/agent-keys"

# Structured machine-readable code returned in the signup 403 body when the
# email is not on the allowlist. The frontend branches on this to show the
# invite-only rejection screen.
SIGNUP_CODE_NOT_ALLOWLISTED = "not_allowlisted"

# Google OAuth / OIDC wiring constants consumed by api.google_oauth. The client
# name is the Authlib registry key; the discovery URL is Google's OIDC metadata
# document (Authlib derives the authorize/token/jwks endpoints from it); the
# scope string requests the OIDC id_token plus the email/profile claims.
GOOGLE_OAUTH_CLIENT_NAME = "google"
GOOGLE_OIDC_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_OAUTH_SCOPE = "openid email profile"

# Keys in the userinfo claims returned alongside the validated id_token.
GOOGLE_CLAIM_SUB = "sub"
GOOGLE_CLAIM_EMAIL = "email"
GOOGLE_CLAIM_EMAIL_VERIFIED = "email_verified"
# Key under which authorize_access_token() exposes the parsed OIDC userinfo.
GOOGLE_TOKEN_USERINFO_KEY = "userinfo"

# Query-param names used on the Google login + callback round-trip. `next` is
# the optional post-login relative redirect; `signup`/`rejected`/`email` drive
# the SPA invite-only rejection screen on a brand-new, non-allowlisted identity.
QUERY_PARAM_NEXT = "next"
QUERY_PARAM_SIGNUP = "signup"
QUERY_PARAM_EMAIL = "email"
SIGNUP_STATUS_REJECTED = "rejected"

# Server-side key under which the Google login route stashes the validated
# `next` path in the transient Starlette session for the callback to read.
OAUTH_SESSION_NEXT_KEY = "oauth_next"

# Name of the HttpOnly cookie carrying the Fernet-encrypted session token.
SESSION_COOKIE_NAME = "langrag_session"

# Fernet payload (JSON) keys/values. The cookie carries ONLY these opaque
# claims, never the password itself.
SESSION_SUBJECT_CLAIM = "sub"
SESSION_SUBJECT_VALUE = "langrag-ui"
# Per-user session claims (individual-account login). SESSION_SUBJECT_CLAIM now
# carries the user_id; these add the role and the revocation epoch so a session
# can be invalidated server-side by bumping the user's stored epoch.
SESSION_ROLE_CLAIM = "role"
SESSION_EPOCH_CLAIM = "epoch"

# Internal machine-to-machine auth on session-gated routes. A request presenting
# the configured shared secret (LANGRAG_LOGIN_INTERNAL_API_KEY) in this header
# resolves to the admin-equivalent service principal below, bypassing the cookie.
INTERNAL_API_KEY_HEADER = "X-Internal-Key"
# user_id/email assigned to the resolved service principal. Distinct from the
# dev sentinel's SESSION_SUBJECT_VALUE so the two are unambiguous in logs/audits.
SERVICE_PRINCIPAL_SUBJECT = "langrag-internal-service"


class CookieSameSite(StrEnum):
    """SameSite policy values for the session cookie."""

    LAX = "lax"
    STRICT = "strict"
    NONE = "none"


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
        "merged_discussed_in": "📍 דובר ב-{count} קבוצות: {groups}",
        "merged_attribution_header": "📅 **נדון בקבוצות הבאות:**",
        "merged_started_at": "התחיל ב-{date}, {time}",
        "engagement_stats": "💬 {messages} הודעות | 👥 {participants} משתתפים",
        "images_shared_heading": "🖼️ תמונות ששותפו",
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
        "engagement_stats": "💬 {messages} messages | 👥 {participants} participants",
        "images_shared_heading": "🖼️ Images shared",
    },
}


def get_langtalks_i18n(desired_language: str | None) -> dict:
    """Get LangTalks i18n strings for the given language, defaulting to English.

    Null-safe: a None/empty language (which can reach this shared sink from the
    empty-newsletter render path) resolves to the English default rather than
    raising on ``.lower()``.
    """
    if desired_language and desired_language.lower() in HEBREW_LANGUAGE_CODES:
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
ROUTE_RAG_CHAT = "/rag/chat"
ROUTE_RAG_INGEST_NEWSLETTERS = "/rag/ingest/newsletters"
ROUTE_RAG_SOURCES_NEWSLETTERS = "/rag/sources/newsletters"

# RAG refusal messages — single source of truth.
# Consumed by the shared refusal helper (rag.generation.rag_chain.refusal_for_empty_context),
# the MCP rag_query tool, the REST chat handlers, and the eval RefusalComplianceMetric
# pattern set. Keep these in sync with custom_metrics._REFUSAL_PATTERNS (the metric
# derives its match set from them, with a coupling test in test_custom_metrics.py).
RAG_REFUSAL_OUT_OF_RANGE = "No content was found within the requested date range. Broaden the window or rephrase the question."
RAG_REFUSAL_NO_CONTENT = "No relevant content found in the indexed sources."
RAG_REFUSAL_INSUFFICIENT_EVIDENCE = "The indexed sources do not contain enough relevant content to answer this question reliably."

# RAG eval metric identifiers. The legacy three metric keys remain inline string
# literals in gate.py for historical continuity; new metric keys are defined here.
RAG_METRIC_DATE_GROUNDING = "date_grounding"
# A chunk's stored source_date_start is considered correctly grounded when it lands
# within this many days of the independently-derived true source date. Newsletters
# cover a multi-day window, so an exact-equality check would false-fail; the tolerance
# absorbs the legitimate start..end spread without admitting a genuinely wrong date.
RAG_DATE_GROUNDING_TOLERANCE_DAYS = 1

# Metrics Routes (no prefix)
ROUTE_METRICS = "/metrics"

# Extracted Images Routes (admin-only gallery + media serving)
ROUTE_IMAGES = "/images"
ROUTE_IMAGE_BY_ID = "/images/{image_id}"
ROUTE_MEDIA_IMAGE = "/media/images/{image_id}"

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
HTTP_STATUS_NO_CONTENT = 204
HTTP_STATUS_FOUND = 302
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_FORBIDDEN = 403
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_CONFLICT = 409
HTTP_STATUS_GONE = 410
HTTP_STATUS_TOO_MANY_REQUESTS = 429
HTTP_STATUS_UNPROCESSABLE_ENTITY = 422
HTTP_STATUS_INTERNAL_SERVER_ERROR = 500
HTTP_STATUS_SERVICE_UNAVAILABLE = 503

# Generic client-facing detail for 5xx responses. Internal exception text
# (paths, driver errors, stack context) MUST be logged server-side, never
# returned in the HTTP body where it leaks implementation detail to callers.
HTTP_DETAIL_INTERNAL_ERROR = "Internal server error"

# Client-facing 503 detail emitted when the RAG concurrency cap is hit.
HTTP_DETAIL_RAG_OVERLOADED = "RAG service is at capacity. Please retry shortly."
# Response header name carrying the retry backoff (seconds) on a 503 shed.
HTTP_HEADER_RETRY_AFTER = "Retry-After"


# ============================================================================
# MONGODB COLLECTION CONSTANTS
# ============================================================================

COLLECTION_RUNS = "runs"
COLLECTION_MESSAGES = "messages"
COLLECTION_DISCUSSIONS = "discussions"
# Raw, pre-rank/pre-merge per-chat discussions (output of separate_discussions),
# persisted separately from the ranked `discussions` collection. Each doc is
# stamped with data_source_name (community) + chat_name (exact group).
COLLECTION_RAW_DISCUSSIONS = "raw_discussions"
COLLECTION_LLM_RESPONSE_CACHE = "llm_response_cache"
COLLECTION_BATCH_JOBS = "batch_jobs"
COLLECTION_NEWSLETTERS = "newsletters"
COLLECTION_SCHEDULED_NEWSLETTERS = "scheduled_newsletters"
COLLECTION_EXTRACTION_CACHE = "extraction_cache"
# Companion collection holding the message arrays for extraction-cache entries,
# sharded across chunk documents. The parent extraction_cache doc holds only
# metadata + a chunk_count; messages live here so a wide date range over a busy
# chat can never push a single document toward the 16MB BSON ceiling.
COLLECTION_EXTRACTION_CACHE_CHUNKS = "extraction_cache_chunks"
# Number of messages per extraction-cache chunk document. Sized well under the
# 16MB BSON limit even for large messages (media metadata, long content).
EXTRACTION_CACHE_CHUNK_SIZE = 2000
COLLECTION_ROOM_ID_MAP = "room_id_map"
COLLECTION_IMAGES = "images"
COLLECTION_TRANSLATION_CACHE = "translation_cache"
COLLECTION_SENDER_MAPS = "sender_maps"
COLLECTION_POLLS = "polls"
COLLECTION_RAG_CHUNKS = "rag_chunks"
COLLECTION_RAG_CONVERSATIONS = "rag_conversations"
COLLECTION_RAG_MESSAGES = "rag_messages"
COLLECTION_RAG_EVALUATIONS = "rag_evaluations"
COLLECTION_RAG_API_KEYS = "rag_api_keys"
# Podcast catalog (multi-podcast platform). One row per podcast/tenant; read by
# list_podcasts() and used to resolve the public `podcast` slug filter.
COLLECTION_PODCASTS = "podcasts"
# Public podcast-MCP consumers (external AI engineers who requested an API key
# for mcp.langrag.ai). A SEPARATE lane from `users`: no app account, no session,
# no app authorization — the minted PODCAST_QUERY-scoped key IS the identity.
# These records must NEVER be written to the `users` collection.
COLLECTION_PODCAST_API_CONSUMERS = "podcast_api_consumers"
# Per-key daily query-quota counters for the public podcast-MCP search surface.
# One row per (key_id, UTC day); an atomic increment records each admitted
# search and is enforced BEFORE the owner-paid embedding call (COST-1). A global
# per-day row (key_id == the global sentinel) backs the daily embedding circuit
# breaker (COST-4b). Rows carry a per-day expiry so the collection stays bounded.
COLLECTION_RAG_QUERY_QUOTA = "rag_query_quota"
# Agentic chatbot layer (v1.13.0+). See knowledge/plans/AGENTIC_CHATBOT_LAYER.md.
COLLECTION_USERS = "users"
COLLECTION_USER_API_KEYS = "user_api_keys"
COLLECTION_AGENT_SESSIONS = "agent_sessions"
COLLECTION_AGENT_MEMORIES = "agent_memories"
# Self-signup access requests: persisted contact-form submissions from users who
# are not on the allowlist, for later admin review.
COLLECTION_ACCESS_REQUESTS = "access_requests"

# Safety ceiling for queries that would otherwise materialize an unbounded result
# set into memory (Motor's cursor.to_list()). Callers that legitimately
# want everything still pass an explicit limit; this only guards the "no limit"
# default so a single query can never OOM the process. When the cap is hit the
# repository logs a warning so the truncation is never silent.
DEFAULT_MAX_QUERY_RESULTS = 10000

# Default page bound for get_messages_by_run when the caller does not pass an
# explicit limit. Kept deliberately small (matches get_messages_page's page_size)
# so the convenience default cannot silently materialize tens of MB of message
# docs into a list. Callers that genuinely need the full run must page through
# get_messages_page (keyset pagination), not raise this default.
DEFAULT_MESSAGES_QUERY_LIMIT = 1000

# Write concern for durable records that MUST survive a primary failover on a
# multi-node Atlas/replica-set deployment: the write is acknowledged only once a
# majority of voting members have it. Applied per-collection to runs,
# newsletters, and users. Caches and ephemeral/derivable state (extraction_cache,
# translation_cache, room_id_map, llm_response_cache) deliberately stay on the
# driver default (w:1): losing a cache entry on failover is cheap and
# regenerable, and majority acks would add latency to hot write paths.
WRITE_CONCERN_MAJORITY = "majority"

# Schema version stamps written on every persisted document. Per-collection so
# each document type can evolve its schema independently.
#
# Migration model: there is NO read-path upgrade ladder. Any schema migration is
# performed OFFLINE/EAGER by an explicit one-time script (see scripts/), not
# rewritten lazily on read. The startup guard (ensure_schema_versions, called
# from ensure_indexes) enforces this contract: it refuses to start if any stored
# document carries an EXPLICIT schema_version BELOW the current constant, so a
# stale document can never be silently misread. A document missing the field is
# treated as pre-versioning (reads fine via model defaults), not stale. Bump the
# matching constant when a doc type's shape changes in a non-additive way, and
# ship the migration script alongside it.
SCHEMA_VERSION_FIELD = "schema_version"
CURRENT_SCHEMA_VERSION_RUN = 1
CURRENT_SCHEMA_VERSION_DISCUSSION = 1
CURRENT_SCHEMA_VERSION_MESSAGE = 1
CURRENT_SCHEMA_VERSION_NEWSLETTER = 1
CURRENT_SCHEMA_VERSION_RAG_CHUNK = 1
# v2 adds individual-account login fields (password_hash, session_epoch,
# disabled). v3 adds self-signup external-identity fields (auth_provider,
# google_sub). Additive with defaults, so old v1/v2 docs read back cleanly.
CURRENT_SCHEMA_VERSION_USER = 3
CURRENT_SCHEMA_VERSION_USER_API_KEY = 1
CURRENT_SCHEMA_VERSION_AGENT_SESSION = 1
CURRENT_SCHEMA_VERSION_AGENT_MEMORY = 1
CURRENT_SCHEMA_VERSION_ACCESS_REQUEST = 1

# Minimum supported schema_version per collection, enforced at startup by
# ensure_schema_versions(). With no read-path migration ladder, the minimum
# supported version equals the current version for every collection: a document
# below it cannot be safely read and must be migrated offline first. Only
# collections that actually stamp schema_version are listed.
MIN_SUPPORTED_SCHEMA_VERSIONS: dict[str, int] = {
    COLLECTION_RUNS: CURRENT_SCHEMA_VERSION_RUN,
    COLLECTION_DISCUSSIONS: CURRENT_SCHEMA_VERSION_DISCUSSION,
    COLLECTION_MESSAGES: CURRENT_SCHEMA_VERSION_MESSAGE,
    COLLECTION_NEWSLETTERS: CURRENT_SCHEMA_VERSION_NEWSLETTER,
    COLLECTION_RAG_CHUNKS: CURRENT_SCHEMA_VERSION_RAG_CHUNK,
    COLLECTION_USERS: CURRENT_SCHEMA_VERSION_USER,
    COLLECTION_USER_API_KEYS: CURRENT_SCHEMA_VERSION_USER_API_KEY,
    COLLECTION_AGENT_SESSIONS: CURRENT_SCHEMA_VERSION_AGENT_SESSION,
    COLLECTION_AGENT_MEMORIES: CURRENT_SCHEMA_VERSION_AGENT_MEMORY,
}

# Agent memory Atlas Search indexes (paired via $rankFusion).
AGENT_MEMORY_VECTOR_INDEX_NAME = "agent_memory_embeddings"
AGENT_MEMORY_LEXICAL_INDEX_NAME = "agent_memory_lexical"
# Default RRF weights for the agent memory hybrid retriever.
AGENT_MEMORY_HYBRID_VECTOR_WEIGHT = 0.7
AGENT_MEMORY_HYBRID_LEXICAL_WEIGHT = 0.3
# Episodic memories expire automatically after 30 days; semantic + procedural
# memories are permanent until the owning user deletes them.
AGENT_EPISODIC_MEMORY_TTL_DAYS = 30
# Default API key prefix for user-scoped agent keys. Distinct from the public
# RAG prefix so an operator can tell at a glance which surface a leaked key
# belongs to.
AGENT_USER_API_KEY_PREFIX = "lk_user_"

# RAG Vector Search Index Name (created on startup against MongoDB Atlas / mongot)
# v2 carries scalar quantization (MongoDB 8.0.4+) on BinData (subtype 9) embeddings.
RAG_VECTOR_INDEX_NAME = "rag_chunk_embeddings_v2"
# Legacy index name kept for migration / dual-name cutover.
RAG_VECTOR_INDEX_NAME_LEGACY = "rag_chunk_embeddings"

# RAG lexical (Atlas Search) index over rag_chunks.content for hybrid retrieval
# via $rankFusion (MongoDB 8.1+).
RAG_LEXICAL_INDEX_NAME = "rag_chunks_lexical"

# $vectorSearch numCandidates bounds, shared by the vector-only and hybrid RAG
# retrieval paths so they stay symmetric. The floor keeps HNSW recall stable
# for small top_k (MongoDB guidance: numCandidates >= ~10-20x limit AND a
# practical minimum of ~100-200); the ceiling is a latency guardrail so a large
# top_k can't blow up the mongot scan.
RAG_VECTOR_SEARCH_MIN_NUM_CANDIDATES = 150
RAG_VECTOR_SEARCH_MAX_NUM_CANDIDATES = 1000

# Vector search index on the discussions collection, created on startup (same
# modern vectorSearch syntax + scalar quantization as the RAG chunk index).
# Used by anti-repetition similarity and the discussion-search endpoint.
DISCUSSION_VECTOR_INDEX_NAME = "discussion_embeddings"

# Default weights for $rankFusion hybrid retrieval (vector + lexical).
RAG_HYBRID_VECTOR_WEIGHT = 0.7
RAG_HYBRID_LEXICAL_WEIGHT = 0.3

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
# Final newsletter deliverable triplet (the actual emailed/delivered output).
# Rendered ONLY at the final stage from the translated structured dict.
OUTPUT_FILESTEM_FINAL_NEWSLETTER = "final_newsletter"
OUTPUT_FILENAME_FINAL_NEWSLETTER_JSON = f"{OUTPUT_FILESTEM_FINAL_NEWSLETTER}{FILE_EXT_JSON}"
OUTPUT_FILENAME_FINAL_NEWSLETTER_MD = f"{OUTPUT_FILESTEM_FINAL_NEWSLETTER}{FILE_EXT_MD}"
OUTPUT_FILENAME_FINAL_NEWSLETTER_HTML = f"{OUTPUT_FILESTEM_FINAL_NEWSLETTER}{FILE_EXT_HTML}"
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

# Output directory names.
#
# Two families of stage-dir names coexist:
#   * NUMBERED stage dirs (below) are what NEW runs WRITE. Each value is prefixed
#     with its zero-padded pipeline order so a directory listing reads in
#     pipeline order. Numbers are static, with gaps for optional stages (e.g. the
#     per-chat images stage is 02 and simply absent when image extraction is off);
#     no dynamic renumbering.
#   * The un-numbered LEGACY_* names capture the pre-numbering layout so readers
#     can still resolve HISTORICAL on-disk runs (Decision 3: reader fallback, no
#     migration). The same short constant (e.g. DIR_NAME_NEWSLETTER) is shared by
#     both pipelines at DIFFERENT numbered positions, so it cannot carry a single
#     numbered value; the numbered writer dirs are therefore SEPARATE per-pipeline
#     constants and the short names retain their legacy un-numbered values for
#     backward-compatible READS.
DIR_NAME_CONSOLIDATED = "consolidated"
DIR_NAME_PER_CHAT = "per_chat"
DIR_NAME_DISCUSSIONS_FOR_SELECTION = "discussions_for_selection"
DIR_NAME_AFTER_SELECTION = "after_selection"
DIR_NAME_PODCASTS = "podcasts"

# Legacy (pre-numbering) stage-dir names. Values unchanged so readers can still
# find historical runs written before the numbering scheme.
DIR_NAME_NEWSLETTER = "newsletter"
DIR_NAME_LINK_ENRICHMENT = "link_enrichment"
DIR_NAME_FINAL_TRANSLATION = "final_translation"
DIR_NAME_FINAL_NEWSLETTER = "final_newsletter"
DIR_NAME_AGGREGATED_DISCUSSIONS = "aggregated_discussions"
DIR_NAME_EXTRACTED = "extracted"
DIR_NAME_PREPROCESSED = "preprocessed"
DIR_NAME_TRANSLATED = "translated"
DIR_NAME_SEPARATE_DISCUSSIONS = "separate_discussions"
DIR_NAME_DISCUSSIONS_RANKING = "discussions_ranking"
DIR_NAME_IMAGES = "images"

# Numbered CONSOLIDATED stage dirs (what new consolidated runs write).
DIR_NAME_CONSOLIDATED_AGGREGATED_DISCUSSIONS = "01_aggregated_discussions"
DIR_NAME_CONSOLIDATED_DISCUSSIONS_RANKING = "02_discussions_ranking"
DIR_NAME_CONSOLIDATED_NEWSLETTER = "03_newsletter"
DIR_NAME_CONSOLIDATED_LINK_ENRICHMENT = "04_link_enrichment"
DIR_NAME_CONSOLIDATED_FINAL_NEWSLETTER = "05_final_newsletter"

# Numbered PER-CHAT stage dirs (what new per-chat runs write). 02_images is
# optional and only created when image extraction is enabled.
DIR_NAME_PERCHAT_EXTRACTED = "01_extracted"
DIR_NAME_PERCHAT_IMAGES = "02_images"
DIR_NAME_PERCHAT_PREPROCESSED = "03_preprocessed"
DIR_NAME_PERCHAT_TRANSLATED = "04_translated"
DIR_NAME_PERCHAT_SEPARATE_DISCUSSIONS = "05_separate_discussions"
DIR_NAME_PERCHAT_DISCUSSIONS_RANKING = "06_discussions_ranking"
DIR_NAME_PERCHAT_NEWSLETTER = "07_newsletter"
DIR_NAME_PERCHAT_LINK_ENRICHMENT = "08_link_enrichment"
DIR_NAME_PERCHAT_FINAL_NEWSLETTER = "09_final_newsletter"

# Candidate dir-name lists for backward-compatible reads: probe the new numbered
# name first, then the legacy un-numbered name, and use whichever exists on disk.
# Consolidated final-newsletter stage (numbered -> legacy final_newsletter ->
# legacy final_translation).
CONSOLIDATED_FINAL_NEWSLETTER_DIR_CANDIDATES = (
    DIR_NAME_CONSOLIDATED_FINAL_NEWSLETTER,
    DIR_NAME_FINAL_NEWSLETTER,
    DIR_NAME_FINAL_TRANSLATION,
)
CONSOLIDATED_NEWSLETTER_DIR_CANDIDATES = (
    DIR_NAME_CONSOLIDATED_NEWSLETTER,
    DIR_NAME_NEWSLETTER,
)
CONSOLIDATED_LINK_ENRICHMENT_DIR_CANDIDATES = (
    DIR_NAME_CONSOLIDATED_LINK_ENRICHMENT,
    DIR_NAME_LINK_ENRICHMENT,
)
PERCHAT_NEWSLETTER_DIR_CANDIDATES = (
    DIR_NAME_PERCHAT_NEWSLETTER,
    DIR_NAME_NEWSLETTER,
)
PERCHAT_LINK_ENRICHMENT_DIR_CANDIDATES = (
    DIR_NAME_PERCHAT_LINK_ENRICHMENT,
    DIR_NAME_LINK_ENRICHMENT,
)

# RAG citation snippet max length
RAG_CITATION_SNIPPET_MAX_LENGTH = 200

# API key prefix for langrag.ai issued keys (helps log triage and key rotation)
RAG_API_KEY_PREFIX = "lrag_"
RAG_API_KEY_HEADER = "X-API-Key"
RAG_API_KEY_BEARER_SCHEME = "Bearer"
# Proxy headers used to resolve the real client IP for per-IP rate limiting.
# CF-Connecting-IP is set by Cloudflare (and stripped from client input by it);
# X-Forwarded-For is honored only from a trusted proxy peer. See rate_limiting.
HEADER_CF_CONNECTING_IP = "CF-Connecting-IP"
HEADER_X_FORWARDED_FOR = "X-Forwarded-For"
# Deny-by-default cutoff for empty-scope key resolution (see rag.auth.scopes).
# A key with an empty/missing scopes list resolves to FULL only if it was created
# BEFORE this instant (legacy keys minted before scopes existed); an empty-scope
# key created at/after it resolves to NO scopes. Set to the scopes-enforcement
# deploy date; do not move it backward (would re-open the legacy carve-out) nor
# forward (would strip legitimately-legacy keys of FULL).
RAG_API_KEY_EMPTY_SCOPE_FULL_CUTOFF = datetime(2026, 7, 2, tzinfo=UTC)

# Seed podcast (podcast #1 of the multi-podcast platform). The catalog is seeded
# idempotently with this slug so `list_podcasts()` and the `podcast` filter work
# against the existing LangTalks corpus.
PODCAST_SLUG_LANGTALKS = "langtalks"
PODCAST_TITLE_LANGTALKS = "LangTalks"
PODCAST_DESCRIPTION_LANGTALKS = "The LangTalks GenAI podcast: conversations on LLMs, agents, RAG, and applied AI engineering."

# Public MCP tool names — the FROZEN public contract. These names live in every
# consumer's client config, so renaming them is a breaking change. Do NOT ship
# LangTalks-specific names (e.g. search_langtalks); the podcast is an argument.
MCP_TOOL_SEARCH_PODCASTS = "search_podcasts"
MCP_TOOL_LIST_PODCASTS = "list_podcasts"
# Internal-only MCP tool names (never exposed in public mode).
MCP_TOOL_RAG_QUERY = "rag_query"
MCP_TOOL_RAG_SEARCH = "rag_search"
MCP_TOOL_LIST_RAG_SOURCES = "list_rag_sources"

# Tool-boundary security bounds for the MCP search surface (resource-exhaustion
# guards). Applied at the tool boundary before any expensive work (embedding,
# vector search) so an adversarial caller cannot use tool inputs as a DoS lever.
MCP_TOP_K_HARD_MAX = 20
MCP_QUERY_MAX_LENGTH = 8000
# Latest plausible source date; anything past this is an absurd/garbage range and
# is rejected at parse time rather than driving a pointless retrieval.
MCP_DATE_MAX_YEAR = 2100

# Public podcast-MCP consumer key issuance (langrag.ai/podcasts self-service).
# The verification email links to this page with the single-use token as a query
# param; the frontend POSTs it back to the verify endpoint. Host is a config
# value (RAG_PODCAST_CONSUMER_VERIFY_BASE_URL) so it is not hardcoded per-env.
PODCAST_CONSUMER_TOKEN_QUERY_PARAM = "token"
# mcp_url returned to the consumer on successful verify — the SSE endpoint they
# add to their MCP client. Sourced from config (RAG_MCP_PUBLIC_URL) so staging
# and prod differ without a code change; this is the documented default.
PODCAST_CONSUMER_MCP_URL_DEFAULT = "https://mcp.langrag.ai/mcp"
# rag_api_keys.name / owner stamped on a consumer-minted key so key listings and
# Langfuse per-key analytics can distinguish the public lane from internal keys.
PODCAST_CONSUMER_KEY_NAME = "podcast-consumer"
PODCAST_CONSUMER_KEY_OWNER_PREFIX = "podcast-consumer:"
# Generic, byte-identical acknowledgement for EVERY request-key call — new email,
# already-registered email, per-email rate-limit hit, or a delivery failure. The
# opaque response is what prevents email enumeration on this public surface.
PODCAST_CONSUMER_REQUEST_ACK_MESSAGE = "If that email is eligible, a verification link has been sent. Check your inbox."
# Explicit, distinguishable errors on the verify path (the frontend maps 400 vs
# 410 to different UX). Verify is NOT anti-enumeration: the caller already holds
# a token, so a precise error leaks nothing about other emails.
PODCAST_CONSUMER_TOKEN_INVALID_MESSAGE = "Invalid or already-used verification token."
PODCAST_CONSUMER_TOKEN_EXPIRED_MESSAGE = "Verification token has expired. Request a new one."
# Cap on the persisted request_timestamps array (create_or_refresh_pending uses a
# $slice push to keep only the last N). N must comfortably exceed the per-email
# daily cap so the rolling-window count is never under-reported, while bounding
# the array so a persistent abuser (who still gets a 202 while rate-limited)
# cannot grow the document without limit.
PODCAST_CONSUMER_REQUEST_TIMESTAMPS_MAX = 50
# Email-canonicalization inputs for the podcast-consumer anti-abuse bucket
# (canonicalize_email_for_dedup). The `+` sub-address separator is stripped from
# every provider's local part; dots are additionally stripped for providers that
# ignore them (Gmail and its googlemail alias).
EMAIL_PLUS_TAG_SEPARATOR = "+"
EMAIL_DOT_IGNORING_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
# Bounds for the optional `podcast` slug filter on the public search tool. The
# slug goes into a Mongo equality filter, so it is validated at the tool boundary
# (length + charset) like every other public input rather than trusted as free
# text. Slugs are lowercase kebab-case identifiers.
MCP_PODCAST_SLUG_MAX_LENGTH = 64
MCP_PODCAST_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

# Rate limits for the public RAG API (per API key)
RAG_RATE_LIMIT_CHAT = "60/minute"
RAG_RATE_LIMIT_INGEST = "10/minute"
RAG_RATE_LIMIT_DEFAULT = "120/minute"


class RagAdmissionError(StrEnum):
    """Machine-readable outcome codes for RAG concurrency admission control.

    Distinct from slowapi rate limiting: this is a hard in-flight concurrency
    cap, not a requests-per-minute limit. Referenced directly (never via .value).
    """

    OVERLOADED = "rag_overloaded"


# RAG vector search score field (added by $vectorSearch $meta)
RAG_SEARCH_SCORE_FIELD = "search_score"

# Per-chunk cosine similarity captured inside the hybrid retrieval vector leg
# (via $meta:"vectorSearchScore"). $rankFusion fuses RANKS, not scores, so the
# fused RRF value cannot express "everything is irrelevant" — a junk top hit
# still ranks #1. The vector cosine is the only absolute relevance signal, so we
# preserve it on each fused chunk to apply a relevance floor on the hybrid path.
RAG_HYBRID_VECTOR_COSINE_FIELD = "_vector_cosine_score"

# Absolute per-citation relevance surfaced to callers and the answer evidence
# gate. On the hybrid path this is the preserved vector cosine (see above); on
# the vector-only path it equals the normalized vectorSearchScore. Unlike
# `search_score` (page-normalized on the hybrid path), this value is comparable
# against a fixed threshold across queries.
RAG_EVIDENCE_SCORE_FIELD = "evidence_score"


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
    "langtalks": {"LangTalks Community": ["LangTalks Community", "LangTalks Community 2", "LangTalks Community 3", "LangTalks Community 4", "LangTalks Community 5", "LangTalks - Code Generation Agents", "LangTalks - English", "LangTalks - AI driven coding", "LangTalks AI-SDLC"]},
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


class LinkEnrichmentStatus(StrEnum):
    """Outcome of the optional Phase-2 link-enrichment step."""

    SUCCEEDED = "succeeded"  # Enriched newsletter produced
    SKIPPED = "skipped"  # Enrichment ran but produced no enriched files
    FAILED = "failed"  # Enrichment raised; base newsletter returned instead


class PreprocessingOperations(StrEnum):
    PARSE_AND_STANDARDIZE_RAW_WHATSAPP_MESSAGES_WITH_STATS = "parse_and_standardize_raw_whatsapp_messages_with_stats"
    TRANSLATE_WHATSAPP_GROUP_CHAT_MESSAGES = "translate_whatsapp_group_chat_messages"
    SEPARATE_WHATSAPP_GROUP_MESSAGE_DISCUSSIONS = "separate_whatsapp_group_message_discussions"


class ContentGenerationOperations(StrEnum):
    GENERATE_NEWSLETTER_SUMMARY = "generate_newsletter_summary"
    TRANSLATE_SUMMARY = "translate_summary"
    # Structured translation of the enriched newsletter dict: translate human-text
    # field values, preserve JSON keys/structure and every URL verbatim, and return
    # a same-shaped dict renderable by the format plugins (md/html/json).
    TRANSLATE_NEWSLETTER_STRUCTURED = "translate_newsletter_structured"


class SummaryFormats(StrEnum):
    MCP_ISRAEL_FORMAT = "mcp_israel_format"
    LANGTALKS_FORMAT = "langtalks_format"
    WHATSAPP_FORMAT = "whatsapp_format"


class LlmInputPurposes(StrEnum):
    SEPARATE_DISCUSSIONS = "separate_whatsapp_group_message_discussions"
    TRANSLATE_WHATSAPP_GROUP_MESSAGES = "translate_whatsapp_group_messages"
    TRANSLATE_SUMMARY = "translate_summary"
    TRANSLATE_NEWSLETTER_STRUCTURED = "translate_newsletter_structured"
    GENERATE_CONTENT_WA_COMMUNITY_LANGTALKS_NEWSLETTER = "generate_content_wa_community_langtalks_newsletter"

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
# WEBHOOK EVENT TYPE CONSTANTS
# ============================================================================

# `event` field on the webhook payload the batch worker POSTs on job completion
# (background_jobs.batch_worker.send_webhook_notification).
WEBHOOK_EVENT_BATCH_JOB_COMPLETED = "batch_job_completed"


# ============================================================================
# TIMESTAMP FORMAT CONSTANTS
# ============================================================================

# strftime patterns for the HITL selection UI (date/time of first message in a
# discussion). DD.MM.YY and HH:MM, matching the RankedDiscussionItem schema.
TIMESTAMP_DATE_FORMAT = "%d.%m.%y"
TIMESTAMP_TIME_FORMAT = "%H:%M"


# ============================================================================
# ENVIRONMENT VARIABLE NAME CONSTANTS
# ============================================================================

ENV_APP_BASE_URL = "APP_BASE_URL"
ENV_DEFAULT_EMAIL_RECIPIENT = "DEFAULT_EMAIL_RECIPIENT"
ENV_BEEPER_ACCESS_TOKEN = "BEEPER_ACCESS_TOKEN"

# LLM provider API keys (fail-fast required at startup; see main.py).
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"

# Deployment environment selector (e.g. "development", "production"). Compared
# against ENVIRONMENT_PRODUCTION to gate HSTS and other prod-only behavior.
ENV_ENVIRONMENT = "ENVIRONMENT"
ENVIRONMENT_PRODUCTION = "production"

# UI login gate (resolved via the LANGRAG_LOGIN_ prefix in config).
# ENV_LOGIN_PASSWORD is deprecated: individual email+password accounts replaced
# the single shared password. The Fernet session key MUST stay stable across
# deploys or every live session is invalidated on restart.
ENV_LOGIN_PASSWORD = "LANGRAG_LOGIN_PASSWORD"
ENV_LOGIN_SESSION_KEY = "LANGRAG_LOGIN_SESSION_KEY"

# Bootstrap-admin seeding (resolved via the LANGRAG_LOGIN_ prefix in config).
# When the users collection is empty at startup, exactly one admin is seeded
# from these two values. Required only for that first-boot path.
ENV_BOOTSTRAP_ADMIN_EMAIL = "LANGRAG_BOOTSTRAP_ADMIN_EMAIL"
ENV_BOOTSTRAP_ADMIN_PASSWORD = "LANGRAG_BOOTSTRAP_ADMIN_PASSWORD"

# Self-signup gate (resolved via the LANGRAG_SIGNUP_ prefix in config).
# The allowlist is a JSON/CSV list of emails permitted to self-register; the
# OAuth state secret signs the transient Starlette session used by Authlib's
# state+nonce round-trip (wired in a later slice).
ENV_SIGNUP_ENABLED = "LANGRAG_SIGNUP_ENABLED"
ENV_SIGNUP_ALLOWLIST = "LANGRAG_SIGNUP_ALLOWLIST"
ENV_SIGNUP_OAUTH_STATE_SECRET = "LANGRAG_SIGNUP_OAUTH_STATE_SECRET"

# Google OAuth / OIDC (resolved via the LANGRAG_GOOGLE_ prefix in config). The
# fields exist now; the OAuth endpoints that consume them are wired in a later
# slice once a Google client is registered.
ENV_GOOGLE_ENABLED = "LANGRAG_GOOGLE_ENABLED"
ENV_GOOGLE_CLIENT_ID = "LANGRAG_GOOGLE_CLIENT_ID"
ENV_GOOGLE_CLIENT_SECRET = "LANGRAG_GOOGLE_CLIENT_SECRET"
ENV_GOOGLE_REDIRECT_URI = "LANGRAG_GOOGLE_REDIRECT_URI"


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


class DiagnosticReportStatus(StrEnum):
    """Status of a run's diagnostic report."""

    CLEAN = "clean"
    ISSUES_FOUND = "issues_found"
    UNKNOWN = "unknown"


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


class RAGApiKeyScope(StrEnum):
    """Authorization scopes for RAG API keys.

    FULL is the internal/admin scope: it may invoke every MCP tool and reach the
    REST + ingest surfaces. PODCAST_QUERY is the public consumer scope: it may
    ONLY invoke the public podcast tools (search_podcasts / list_podcasts).

    Backward compatibility: existing key records carry no `scopes` field (or an
    empty list). The auth layer treats a missing/empty scope as FULL so no
    already-issued key loses access. A key is treated as PODCAST_QUERY-restricted
    ONLY when PODCAST_QUERY is present AND FULL is absent.
    """

    FULL = "full"
    PODCAST_QUERY = "podcast_query"


class RAGEventType(StrEnum):
    """SSE event types for RAG chat streaming."""

    TOKEN = "token"
    CITATION = "citation"
    DONE = "done"
    ERROR = "error"
    EVALUATION_SCORE = "evaluation_score"


class RAGTraceName(StrEnum):
    """Langfuse trace names for the live RAG request paths (REST + MCP)."""

    REST_CHAT = "rag_chat"
    REST_CHAT_STREAM = "rag_chat_stream"
    MCP_QUERY = "rag_query"
    MCP_SEARCH = "rag_search"


class RAGTraceTag(StrEnum):
    """Langfuse tag strings for RAG traces. The streaming tag reuses the
    module-level TAG_STREAMING constant rather than duplicating it here."""

    RAG = "rag"
    SYNC = "sync"
    MCP = "mcp"


# Langfuse trace metadata keys for the live RAG paths. These are behavior-affecting
# dict keys read/filtered in the Langfuse UI (dashboards, refusal-rate view), not
# display text, so they are immutable constants rather than inline literals.
RAG_TRACE_META_CONTENT_SOURCES = "content_sources"
RAG_TRACE_META_DATE_START = "date_start"
RAG_TRACE_META_DATE_END = "date_end"
RAG_TRACE_META_REFUSAL = "refusal"
RAG_TRACE_META_CITATION_COUNT = "citation_count"
RAG_TRACE_META_TRANSPORT = "transport"

# Trace output key for the generated answer text.
RAG_TRACE_OUTPUT_ANSWER = "answer"

# Query-input truncation bound for trace `input` (matches pipeline span_input[:500]).
RAG_TRACE_INPUT_MAX = 500

# user_id label attached to MCP-originated RAG traces (no caller identity on the
# FastMCP tool signature, so a fixed owner label is used).
MCP_TRACE_USER = "mcp"

# Prefix for the per-call session_id synthesized in the MCP tool wrappers. FastMCP
# carries no caller identity, so each tool call becomes its own grouped trace.
MCP_SESSION_ID_PREFIX = "mcp-"

# Langfuse trace metadata key carrying the resolved per-key identifier (the key_id
# / hash, NEVER the raw bearer) so the owner can see per-key analytics on the
# self-hosted Langfuse (OBS-1). Behavior-affecting dashboard filter key.
RAG_TRACE_META_KEY_ID = "key_id"

# Sentinel key_id for the process-wide daily embedding circuit-breaker counter
# row in COLLECTION_RAG_QUERY_QUOTA (COST-4b). Not a real key; namespaced with a
# leading double-underscore so it can never collide with a minted key_id.
RAG_GLOBAL_EMBED_QUOTA_KEY_ID = "__global_embed__"

# Reject observability (OBS-2). Emitted (metric + Langfuse event) at every reject
# point so the owner can watch abuse patterns, not just successes. These reason
# labels are behavior-affecting (Prometheus label values + Langfuse event names).
RAG_REJECT_EVENT_NAME = "rag_reject"
RAG_REJECT_REASON_SCOPE_DENIED = "scope_denied"
RAG_REJECT_REASON_UNAUTHORIZED = "unauthorized"
RAG_REJECT_REASON_VALIDATION = "validation_rejected"
RAG_REJECT_REASON_CAPACITY = "capacity_exceeded"
# Global embedding circuit-breaker trip reason (COST-4b reject visibility).
RAG_REJECT_REASON_GLOBAL_EMBED_BREAKER = "global_embed_breaker_open"
# Anonymous-lane global daily breaker trip reason (keyless BYOA lane).
RAG_REJECT_REASON_ANON_GLOBAL_BREAKER = "anon_global_breaker_open"

# --- Anonymous (keyless) MCP lane ---------------------------------------------
# Synthetic key_id prefix for anonymous principals on the public podcast MCP.
# The suffix is a SHA-256 prefix of the resolved client IP so quota rows, trace
# tags, and logs never carry a raw IP. Prefix check = principal routing.
RAG_ANON_KEY_ID_PREFIX = "anon:"
# Owner label stamped on the synthetic anonymous key record.
RAG_ANON_OWNER = "anonymous"
# Hex chars of sha256(ip) kept in the anonymous key_id (collision-safe for quota
# bucketing; not a security boundary).
RAG_ANON_IP_HASH_LEN = 16
# Sentinel key_id for the anonymous-lane global daily counter row in
# COLLECTION_RAG_QUERY_QUOTA. Namespaced like RAG_GLOBAL_EMBED_QUOTA_KEY_ID so
# it can never collide with a minted key_id.
RAG_GLOBAL_ANON_QUOTA_KEY_ID = "__global_anon__"

# --- Public MCP prompt / resource surface (BYOA answer-quality polish) --------
# Registered names are the public contract; renaming breaks third-party agents.
MCP_PROMPT_ASK_PODCASTS = "ask_podcasts"
MCP_RESOURCE_ANSWER_GUIDE_URI = "langrag://podcasts/answer-guide"


class AgentEventType(StrEnum):
    """SSE event types for the v1.13.0 agent chat streaming endpoint.

    See knowledge/plans/AGENTIC_CHATBOT_LAYER.md §G.
    """

    TOKEN = "token"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    ARTIFACT_PANEL = "artifact_panel"
    INTERRUPT_REQUIRED = "interrupt_required"
    MEMORY_WRITTEN = "memory_written"
    BUDGET_WARNING = "budget_warning"
    ERROR = "error"
    DONE = "done"


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


class SeShadowKey(StrEnum):
    """Langfuse score names / Mongo field names written by the SE shadow scorer.

    Kept separate from EvaluationMetric so semantic-entropy shadow scores never
    pollute the judge metrics consumed by _passes_threshold / overall_passed.
    """

    SE_SCORE = "se_shadow_score"
    N_CLUSTERS = "se_shadow_n_clusters"
    N_SAMPLES = "se_shadow_n_samples"
    ESCALATION_FLAG = "se_shadow_escalated"


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
RESULT_KEY_TRANSLATED_PATH = "translated_path"


# ============================================================================
# SCHEDULE FIELD CONSTANTS
# ============================================================================

SCHEDULE_FIELD_RUN_TIME = "run_time"
SCHEDULE_FIELD_INTERVAL_DAYS = "interval_days"
SCHEDULE_DEFAULT_RUN_TIME = "08:00"

# APScheduler job identifier prefix for newsletter schedules. One in-memory
# job per MongoDB schedule document, keyed by string-ified ObjectId, so the
# change-stream watcher can add/remove/reschedule by ID without scanning.
SCHEDULER_JOB_ID_PREFIX = "newsletter_schedule_"

# Bounded delay tolerated between change-stream stream drop and reconcile.
# Sleeping then doing a full reconcile is safer than tight reconnect loops
# that thunder a flaky mongod.
CHANGE_STREAM_RECONNECT_DELAY_SECONDS = 5


class ChangeStreamOperation(StrEnum):
    """MongoDB change stream operationType values we react to."""

    INSERT = "insert"
    UPDATE = "update"
    REPLACE = "replace"
    DELETE = "delete"


# ============================================================================
# HITL KEY CONSTANTS
# ============================================================================

HITL_KEY_PHASE_1_COMPLETE = "phase_1_complete"
HITL_KEY_PHASE_2_READY = "phase_2_ready"
HITL_KEY_TIMEOUT_DEADLINE = "timeout_deadline"
# NOTE: Which formats support HITL is owned by the newsletter-format registry's
# per-format `supports_hitl` capability flag (see
# custom_types.newsletter_formats.format_supports_hitl). Do NOT reintroduce a
# parallel hardcoded list here — it drifts from the registry.


# ============================================================================
# SENTINEL CONSTANTS
# ============================================================================

CONSOLIDATED_CHAT_SENTINEL = "__consolidated__"
UNKNOWN_CHAT_NAME = "unknown"
NO_CONTENT_FOR_SECTION = "No content for this section"


# ============================================================================
# MONGODB BACKUP → GCS
# ============================================================================
# Single source of truth for the backup sidecar. The shell scripts in
# scripts/backup/ receive these as environment variables, injected by the
# `mongo-backup` Compose service which references the same values. See
# knowledge/plans/MONGODB_BACKUP_GCS.md.

# GCS destination (project langrag-499615, region europe-west1).
BACKUP_GCS_BUCKET = "langrag-499615-langrag-backups"
BACKUP_GCS_DAILY_PREFIX = "langrag/daily/"
BACKUP_GCS_MONTHLY_PREFIX = "langrag/monthly/"

# Database being dumped (matches DatabaseSettings.database default).
BACKUP_DATABASE_NAME = "langrag"

# In-Docker-network Mongo target: service DNS name `mongodb`, replica set
# `langrag-mongodb` (per docker-compose.yml). NOT `rs0`.
BACKUP_MONGO_HOST = "mongodb"
BACKUP_MONGO_PORT = 27017
BACKUP_MONGO_REPLICA_SET = "langrag-mongodb"

# Archive naming: langrag-YYYYMMDDTHHMMSSZ.archive.gz
BACKUP_ARCHIVE_PREFIX = "langrag-"
BACKUP_ARCHIVE_SUFFIX = ".archive.gz"

# Retention (enforced by the GCS lifecycle rule, mirrored here for reference).
BACKUP_DAILY_RETENTION_DAYS = 30
BACKUP_MONTHLY_RETENTION_DAYS = 365
