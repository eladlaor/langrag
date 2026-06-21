"""
Field key constants for data structure dictionaries (discussions, rankings, newsletters,
DB documents, decryption results, images, RAG chunks, etc.).

These keys are used for accessing fields in domain data dictionaries that flow through
the pipeline — NOT for LangGraph workflow state fields.

For LangGraph workflow state keys (SingleChatState, ParallelOrchestratorState, etc.), see:
    src/graphs/state_keys.py

CRITICAL: All dictionary key access for these data structures MUST use these constants.
Never hardcode field keys as strings - use these constants instead.

This prevents typos, enables refactoring, and provides IDE autocomplete support.

Usage:
    from custom_types.field_keys import DiscussionKeys, RankingResultKeys

    # GOOD
    title = discussion[DiscussionKeys.TITLE]
    featured = ranking[RankingResultKeys.FEATURED_DISCUSSION_IDS]

    # BAD (brittle, typo-prone)
    title = discussion["title"]
    featured = ranking["featured_discussion_ids"]

Note: These are plain classes with string constants (not StrEnum) because they represent
dictionary keys for data interchange, not closed sets of categorical values.
"""


class DiscussionKeys:
    """Keys for discussion dictionaries throughout the pipeline."""

    ID = "id"
    TITLE = "title"
    NUTSHELL = "nutshell"
    GROUP_NAME = "group_name"
    NUM_MESSAGES = "num_messages"
    NUM_UNIQUE_PARTICIPANTS = "num_unique_participants"
    FIRST_MESSAGE_TIMESTAMP = "first_message_timestamp"
    FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP = "first_message_in_discussion_timestamp"
    SAMPLE_MESSAGES = "sample_messages"
    MESSAGES = "messages"
    # Per-message multi-label enrichment fields written by slm_enrichment_node.
    SLM_ACTIVE_LABELS = "slm_active_labels"
    # Compact per-discussion aggregation of active labels (label -> message count),
    # injected into the ranking summary so the LLM sees enrichment signals without
    # the token cost of every message's full label vector.
    SLM_LABEL_COUNTS = "slm_label_counts"
    IS_MERGED = "is_merged"
    SOURCE_DISCUSSIONS = "source_discussions"
    SOURCE_GROUP = "group"
    SOURCE_GROUPS = "source_groups"
    ORIGINAL_TITLE = "original_title"
    DISCUSSION_TITLE = "discussion_title"
    MERGE_REASONING = "merge_reasoning"
    MERGE_CONFIDENCE = "merge_confidence"
    ORIGINAL_ID = "original_id"
    SOURCE_CHAT = "source_chat"
    SOURCE_DATE_RANGE = "source_date_range"
    DETAILED_SUMMARY = "detailed_summary"
    RELEVANT_LINKS = "relevant_links"
    METADATA = "metadata"
    EMBEDDING = "embedding"
    DISCUSSIONS = "discussions"
    # Transient marker set on a parsed message whose source event was still
    # encrypted (decryption failed). Used to filter undecryptable ciphertext out
    # of the corpus when should_filter_decryption_errors is set; stripped before
    # the message reaches downstream stages.
    DECRYPTION_FAILED = "_decryption_failed"


class MessageSourceKeys:
    """Keys for the raw extracted-message dicts (custom_types.common.Message)
    consumed by the persistence layer before they become MongoDB documents."""

    ID = "id"
    SENDER_ID = "sender_id"
    SENDER = "sender"
    TIMESTAMP = "timestamp"
    CONTENT = "content"
    REPLIES_TO = "replies_to"
    URLS = "urls"
    MENTIONS = "mentions"
    MATRIX_EVENT_ID = "matrix_event_id"


class RankingResultKeys:
    """Keys for ranking result dictionaries from the discussion ranker."""

    RANKED_DISCUSSIONS = "ranked_discussions"
    FEATURED_DISCUSSION_IDS = "featured_discussion_ids"
    BRIEF_MENTION_ITEMS = "brief_mention_items"
    TOP_K_APPLIED = "top_k_applied"
    EDITORIAL_NOTES = "editorial_notes"
    TOPIC_DIVERSITY = "topic_diversity"
    DISCUSSION_ID = "discussion_id"
    RANK = "rank"
    SKIP_REASON = "skip_reason"
    CATEGORY = "category"
    ONE_LINER_SUMMARY = "one_liner_summary"
    IMPORTANCE_SCORE = "importance_score"
    REPETITION_SCORE = "repetition_score"
    REPETITION_IDENTIFICATION_REASONING = "repetition_identification_reasoning"
    RANKING_SCORE = "ranking_score"


class NewsletterStructureKeys:
    """Keys for newsletter JSON structure (LangTalks and MCP Israel formats)."""

    PRIMARY_DISCUSSION = "primary_discussion"
    SECONDARY_DISCUSSIONS = "secondary_discussions"
    WORTH_MENTIONING = "worth_mentioning"
    INDUSTRY_UPDATES = "industry_updates"
    TOOLS_MENTIONED = "tools_mentioned"
    WORK_PRACTICES = "work_practices"
    SECURITY_RISKS = "security_risks"
    VALUABLE_POSTS = "valuable_posts"
    OPEN_QUESTIONS = "open_questions"
    CONCEPTUAL_DISCUSSIONS = "conceptual_discussions"
    HEADLINE = "headline"
    ISSUES_CHALLENGES = "issues_challenges"
    TITLE = "title"
    BULLET_POINTS = "bullet_points"
    LABEL = "label"
    CONTENT = "content"
    LINKS_INSERTED = "links_inserted"
    FIRST_MESSAGE_TIMESTAMP = "first_message_timestamp"
    IS_MERGED = "is_merged"
    SOURCE_DISCUSSIONS = "source_discussions"
    CHAT_NAME = "chat_name"
    MARKDOWN_CONTENT = "markdown_content"
    LAST_MESSAGE_TIMESTAMP = "last_message_timestamp"
    RANKING_OF_RELEVANCE = "ranking_of_relevance_to_gen_ai_engineering"
    NUMBER_OF_MESSAGES = "number_of_messages"
    NUMBER_OF_UNIQUE_PARTICIPANTS = "number_of_unique_participants"
    LINK_ENRICHMENT_METADATA = "link_enrichment_metadata"
    METADATA = "metadata"
    IMAGE_DESCRIPTIONS = "image_descriptions"


class MMRMetadataKeys:
    """Keys for MMR (Maximal Marginal Relevance) metadata dictionaries."""

    MMR_METADATA = "mmr_metadata"
    QUALITY_SCORE = "quality_score"
    DIVERSITY_SCORE = "diversity_score"
    MMR_RANK = "mmr_rank"
    LAMBDA = "lambda"
    RANKING_MODE = "ranking_mode"


class ContentResultKeys:
    """Keys for content generation result dictionaries."""

    NEWSLETTER_ID = "newsletter_id"
    LINKS_ADDED = "links_added"


class MergeGroupKeys:
    """Keys for LLM merge group response dictionaries."""

    MERGE_GROUPS = "merge_groups"
    STANDALONE_IDS = "standalone_ids"
    SUGGESTED_TITLE = "suggested_title"
    DISCUSSION_IDS = "discussion_ids"
    REASONING = "reasoning"


class DecryptionResultKeys:
    """Keys for decryption result dictionaries."""

    DECRYPTED = "decrypted"
    DECRYPTION_METHOD = "decryption_method"
    EVENT_ID = "event_id"
    SENDER = "sender"
    ORIGIN_SERVER_TS = "origin_server_ts"
    ROOM_ID = "room_id"
    SESSION_ID = "session_id"
    TYPE = "type"
    CONTENT = "content"
    BODY = "body"
    MSGTYPE = "msgtype"
    FORMATTED_BODY = "formatted_body"
    FORMAT = "format"
    URL = "url"
    INFO = "info"


class LlmInputKeys:
    """Keys for LLM provider kwargs passed to _get_input_by_purpose().

    These kwargs are shared across OpenAI, Anthropic, and Gemini providers.
    """

    TRANSLATE_FROM = "translate_from"
    TRANSLATE_TO = "translate_to"
    CONTENT_BATCH = "content_batch"
    MESSAGES = "messages"
    CHAT_NAME = "chat_name"
    JSON_INPUT_TO_SUMMARIZE = "json_input_to_summarize"
    MODEL = "model"
    GROUP_NAME = "group_name"
    BRIEF_MENTION_ITEMS = "brief_mention_items"
    INPUT_TO_TRANSLATE = "input_to_translate"
    DESIRED_LANGUAGE_FOR_SUMMARY = "desired_language_for_summary"
    EXAMPLES = "examples"
    NON_FEATURED_DISCUSSIONS = "non_featured_discussions"
    NEWSLETTER_ID = "newsletter_id"
    FEATURED_DISCUSSION_IDS = "featured_discussion_ids"
    IMAGE_DISCUSSION_MAP = "image_discussion_map"


class MatrixImageInfoKeys:
    """Keys for Matrix image info sub-object (content.info)."""

    MIMETYPE = "mimetype"
    WIDTH = "w"
    HEIGHT = "h"
    SIZE = "size"


class MatrixEncryptedFileKeys:
    """Keys for Matrix encrypted file sub-object (content.file).

    Encrypted media in Matrix stores the mxc URL inside content.file.url
    instead of content.url, along with encryption keys for decryption.
    """

    FILE = "file"
    URL = "url"
    FILENAME = "filename"
    # Nested encryption-key fields (content.file.key.k, content.file.iv,
    # content.file.hashes.sha256) used to decrypt AES-CTR encrypted media.
    KEY = "key"
    K = "k"
    IV = "iv"
    HASHES = "hashes"
    SHA256 = "sha256"


class ExtractionCacheKeys:
    """Keys for extraction_cache (parent) and extraction_cache_chunks documents.

    The parent doc holds metadata only (no inline messages once auto-split is in
    effect); the message arrays are sharded into chunk docs in the companion
    collection. MESSAGES is the assembled-list key re-attached to the parent on
    read so callers stay unaware of the split.
    """

    CACHE_KEY = "cache_key"
    CHAT_NAME_NORMALIZED = "chat_name_normalized"
    START_DATE = "start_date"
    END_DATE = "end_date"
    MESSAGES = "messages"
    MESSAGE_COUNT = "message_count"
    ENCRYPTED_COUNT = "encrypted_count"
    EXTRACTION_METADATA = "extraction_metadata"
    CHUNK_COUNT = "chunk_count"
    CHUNK_INDEX = "chunk_index"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    EXPIRES_AT = "expires_at"


class PollContentKeys:
    """Keys for MSC3381 poll event content structure.

    Used to access fields inside org.matrix.msc3381.poll.start content.
    """

    QUESTION = "question"
    ANSWERS = "answers"
    ANSWER_ID = "id"
    KIND = "kind"
    MAX_SELECTIONS = "max_selections"


class PollDbKeys:
    """Keys for poll documents in MongoDB polls collection."""

    POLL_ID = "poll_id"
    MATRIX_EVENT_ID = "matrix_event_id"
    RUN_ID = "run_id"
    CHAT_NAME = "chat_name"
    DATA_SOURCE_NAME = "data_source_name"
    SENDER = "sender"
    TIMESTAMP = "timestamp"
    QUESTION = "question"
    OPTIONS = "options"
    OPTION_ID = "option_id"
    OPTION_TEXT = "text"
    VOTE_COUNT = "vote_count"
    TOTAL_VOTES = "total_votes"
    UNIQUE_VOTER_COUNT = "unique_voter_count"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class ImageKeys:
    """Keys for image metadata dictionaries."""

    IMAGE_ID = "image_id"
    MXC_URL = "mxc_url"
    HTTP_URL = "http_url"
    MIMETYPE = "mimetype"
    WIDTH = "width"
    HEIGHT = "height"
    SIZE_BYTES = "size_bytes"
    FILENAME = "filename"
    SENDER_ID = "sender_id"
    TIMESTAMP = "timestamp"
    MESSAGE_ID = "message_id"
    STORAGE_PATH = "storage_path"
    DESCRIPTION = "description"
    DESCRIPTION_MODEL = "description_model"
    DISCUSSION_ID = "discussion_id"
    CHAT_NAME = "chat_name"
    DATA_SOURCE_NAME = "data_source_name"


class RAGChunkKeys:
    """Keys for RAG chunk documents in rag_chunks collection."""

    CHUNK_ID = "chunk_id"
    CONTENT_SOURCE = "content_source"
    SOURCE_ID = "source_id"
    SOURCE_TITLE = "source_title"
    CONTENT = "content"
    EMBEDDING = "embedding"
    EMBEDDING_MODEL = "embedding_model"
    CHUNK_INDEX = "chunk_index"
    METADATA = "metadata"
    CREATED_AT = "created_at"
    SOURCE_DATE_START = "source_date_start"
    SOURCE_DATE_END = "source_date_end"
    # Community key, promoted to top-level (out of metadata) so it is filterable
    # in the vector + lexical search indexes. Null for podcast chunks.
    DATA_SOURCE_NAME = "data_source_name"


class RAGChunkMetadataKeys:
    """Sub-keys stored inside a rag_chunks document's free-form `metadata` dict.

    Parent-document retrieval (D10) persists the provenance of a newsletter chunk
    here at ingest time: the discussion ids that fed the newsletter, and the
    flattened raw-message ids behind those discussions. Granularity is
    whole-newsletter (every chunk of a newsletter shares the same lists) — the
    newsletter markdown carries no per-section discussion map.
    """

    MESSAGE_IDS = "message_ids"
    DISCUSSION_IDS = "discussion_ids"
    # Attached at retrieval time by the $lookup expansion, not stored.
    PARENT_MESSAGES = "parent_messages"


class RAGConversationKeys:
    """Keys for RAG conversation documents in rag_conversations collection."""

    SESSION_ID = "session_id"
    OWNER = "owner"
    TITLE = "title"
    CONTENT_SOURCES = "content_sources"
    MESSAGES = "messages"
    MESSAGE_ID = "message_id"
    ROLE = "role"
    CONTENT = "content"
    CITATIONS = "citations"
    EVALUATION_ID = "evaluation_id"
    MESSAGE_COUNT = "message_count"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

    # Citation sub-keys
    CITATION_CHUNK_ID = "chunk_id"
    CITATION_SOURCE_TYPE = "source_type"
    CITATION_SOURCE_TITLE = "source_title"
    CITATION_SNIPPET = "snippet"
    CITATION_METADATA = "metadata"


class RAGMessageKeys:
    """Keys for RAG message documents in the rag_messages collection.

    One document per conversation turn. Split out of the embedded
    ``rag_conversations.messages`` array so a long-lived session can never
    breach the 16MB BSON document-size limit. Referenced back to its session
    by ``session_id``; the session document is owner-scoped, so messages are
    only ever reachable through an already-authorized session.
    """

    MESSAGE_ID = "message_id"
    SESSION_ID = "session_id"
    ROLE = "role"
    CONTENT = "content"
    CITATIONS = "citations"
    EVALUATION_ID = "evaluation_id"
    CREATED_AT = "created_at"


class RAGApiKeyKeys:
    """Keys for RAG API key documents in rag_api_keys collection."""

    KEY_ID = "key_id"
    KEY_HASH = "key_hash"
    NAME = "name"
    OWNER = "owner"
    SCOPES = "scopes"
    ENABLED = "enabled"
    CREATED_AT = "created_at"
    LAST_USED_AT = "last_used_at"
    EXPIRES_AT = "expires_at"


class RAGEvaluationKeys:
    """Keys for RAG evaluation documents in rag_evaluations collection."""

    EVALUATION_ID = "evaluation_id"
    SESSION_ID = "session_id"
    MESSAGE_ID = "message_id"
    QUERY = "query"
    RESPONSE = "response"
    RETRIEVED_CONTEXTS = "retrieved_contexts"
    SCORES = "scores"
    OVERALL_PASSED = "overall_passed"
    EVALUATION_MODEL = "evaluation_model"
    EVALUATION_DURATION_MS = "evaluation_duration_ms"
    STATUS = "status"
    ERROR = "error"
    CREATED_AT = "created_at"
    COMPLETED_AT = "completed_at"

    # Score sub-keys
    SCORE_FAITHFULNESS = "faithfulness"
    SCORE_ANSWER_RELEVANCY = "answer_relevancy"
    SCORE_CONTEXTUAL_RELEVANCY = "contextual_relevancy"
    SCORE_HALLUCINATION = "hallucination"


class DbFieldKeys:
    """Keys for MongoDB document fields shared across repositories.

    These are DB schema field names used when constructing or querying MongoDB documents.
    Fields that overlap with DiscussionKeys (e.g., chat_name, title) should still use
    the domain-specific key class at the application layer; this class covers DB-only fields.
    """

    DISCUSSION_ID = "discussion_id"
    MESSAGE_ID = "message_id"
    NEWSLETTER_ID = "newsletter_id"
    RUN_ID = "run_id"
    CHAT_NAME = "chat_name"
    TITLE = "title"
    NUTSHELL = "nutshell"
    RANKING_SCORE = "ranking_score"
    MESSAGE_COUNT = "message_count"
    MESSAGE_IDS = "message_ids"
    EMBEDDING = "embedding"
    EMBEDDING_MODEL = "embedding_model"
    EMBEDDING_TIMESTAMP = "embedding_timestamp"
    METADATA = "metadata"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    COMPLETED_AT = "completed_at"
    STATUS = "status"
    SENDER = "sender"
    CONTENT = "content"
    TIMESTAMP = "timestamp"
    TRANSLATED_CONTENT = "translated_content"
    REPLIES_TO = "replies_to"
    # Message-document fields written by the extraction/preprocessing path
    # (RunTracker.store_raw_messages / store_messages). These describe the
    # `messages` collection's actual stored shape; see MessageDocument.
    SHORT_ID = "short_id"
    CONTENT_TRANSLATED = "content_translated"
    IS_TRANSLATED = "is_translated"
    URLS = "urls"
    MENTIONS = "mentions"
    WORD_COUNT = "word_count"
    NEWSLETTER_TYPE = "newsletter_type"
    DATA_SOURCE_NAME = "data_source_name"
    START_DATE = "start_date"
    END_DATE = "end_date"
    SUMMARY_FORMAT = "summary_format"
    DESIRED_LANGUAGE = "desired_language"
    FEATURED_DISCUSSION_IDS = "featured_discussion_ids"
    BRIEF_MENTION_DISCUSSION_IDS = "brief_mention_discussion_ids"
    QUALITY_SCORES = "quality_scores"
    STATS = "stats"
    ROOM_ID = "room_id"
    MATRIX_EVENT_ID = "matrix_event_id"
    CONTENT_HASH = "content_hash"
    TRANSLATED_AT = "translated_at"
    EXPIRES_AT = "expires_at"
    VERSIONS = "versions"
    JSON_CONTENT = "json_content"
    HTML_CONTENT = "html_content"
    MARKDOWN_CONTENT = "markdown_content"
    FILE_PATHS = "file_paths"
    TARGET_LANGUAGE = "target_language"
    VERSION_TYPE = "version_type"
    ENABLED = "enabled"
    LAST_RUN = "last_run"
    LAST_RUN_STATUS = "last_run_status"
    LAST_RUN_ERROR = "last_run_error"
    NEXT_RUN = "next_run"
    RUN_COUNT = "run_count"
    DIAGNOSTIC_REPORT = "diagnostic_report"
    GENERATED_AT = "generated_at"


class UserKeys:
    """Keys for `users` collection documents (agentic chatbot layer)."""

    USER_ID = "user_id"
    EMAIL = "email"
    ROLE = "role"
    PASSWORD_HASH = "password_hash"
    SESSION_EPOCH = "session_epoch"
    DISABLED = "disabled"
    # External-identity fields (self-signup, schema v3). AUTH_PROVIDER records
    # how the account authenticates; GOOGLE_SUB is the OIDC subject identifier
    # (never the email), sparse-unique-indexed.
    AUTH_PROVIDER = "auth_provider"
    GOOGLE_SUB = "google_sub"
    COMMUNITIES = "communities"
    PREFERENCES = "preferences"
    RAG_PREFERENCES = "rag_preferences"
    QUOTAS = "quotas"
    DAILY_USAGE = "daily_usage"
    CREATED_AT = "created_at"
    LAST_SEEN_AT = "last_seen_at"

    # Nested `rag_preferences` sub-keys (saved per-user RAG MMR setting)
    RAG_PREF_MMR_LAMBDA = "mmr_lambda"
    RAG_PREF_ENABLE_MMR = "enable_mmr_diversity"

    # Nested `quotas` sub-keys
    QUOTA_DAILY_CHAT_INPUT_TOKENS = "daily_chat_input_tokens"
    QUOTA_DAILY_CHAT_OUTPUT_TOKENS = "daily_chat_output_tokens"
    QUOTA_DAILY_MEMORY_TOKENS = "daily_memory_tokens"
    QUOTA_DAILY_NEWSLETTER_RUNS = "daily_newsletter_runs"

    # Nested `daily_usage` sub-keys
    USAGE_DATE = "date"
    USAGE_CHAT_INPUT_TOKENS = "chat_input_tokens"
    USAGE_CHAT_OUTPUT_TOKENS = "chat_output_tokens"
    USAGE_MEMORY_TOKENS = "memory_tokens"
    USAGE_NEWSLETTER_RUNS = "newsletter_runs"


class AccessRequestKeys:
    """Keys for `access_requests` collection documents (self-signup)."""

    REQUEST_ID = "request_id"
    EMAIL = "email"
    NAME = "name"
    MESSAGE = "message"
    REQUESTED_PROVIDER = "requested_provider"
    STATUS = "status"
    CREATED_AT = "created_at"
    REVIEWED_AT = "reviewed_at"
    REVIEWED_BY = "reviewed_by"


class UserApiKeyKeys:
    """Keys for `user_api_keys` collection documents (agentic chatbot layer)."""

    KEY_ID = "key_id"
    KEY_HASH = "key_hash"
    USER_ID = "user_id"
    NAME = "name"
    SCOPES = "scopes"
    ENABLED = "enabled"
    CREATED_AT = "created_at"
    LAST_USED_AT = "last_used_at"
    EXPIRES_AT = "expires_at"


class AgentSessionKeys:
    """Keys for `agent_sessions` collection documents (agentic chatbot layer)."""

    SESSION_ID = "session_id"
    USER_ID = "user_id"
    TITLE = "title"
    COMMUNITY_CONTEXT = "community_context"
    CREATED_AT = "created_at"
    LAST_MESSAGE_AT = "last_message_at"
    MESSAGE_COUNT = "message_count"
    COST_SO_FAR = "cost_so_far"
    EXPIRES_AT = "expires_at"


class AgentMemoryKeys:
    """Keys for `agent_memories` collection documents (agentic chatbot layer)."""

    MEMORY_ID = "memory_id"
    USER_ID = "user_id"
    NAMESPACE = "namespace"
    CONTENT = "content"
    EMBEDDING = "embedding"
    EMBEDDING_MODEL = "embedding_model"
    IMPORTANCE = "importance"
    METADATA = "metadata"
    CREATED_AT = "created_at"
    LAST_ACCESSED_AT = "last_accessed_at"
    ACCESS_COUNT = "access_count"
    EXPIRES_AT = "expires_at"


class DeliveryResultKeys:
    """Keys for delivery result dicts (email, LinkedIn, Substack, webhook)."""

    SUCCESS = "success"
    ERROR = "error"
    RECIPIENTS = "recipients"
    DRAFT_RESPONSE = "draft_response"


class OutputPathKeys:
    """Keys for output path dicts stored in MongoDB run tracking."""

    NEWSLETTER_JSON = "newsletter_json"
    NEWSLETTER_MD = "newsletter_md"
    NEWSLETTER_HTML = "newsletter_html"
    ENRICHED_MD = "enriched_md"


class WorkerResultKeys:
    """Keys for worker result/error dicts exchanged between graph nodes."""

    ERROR = "error"
    ERROR_TYPE = "error_type"
    DISCUSSION_COUNT = "discussion_count"


class BatchJobKeys:
    """Keys for batch-job documents in the batch_jobs MongoDB collection.

    Written by db.batch_jobs.BatchJobManager and read by the batch worker
    (background_jobs.batch_worker) and the async-batch API
    (api.async_batch_orchestration). REQUEST is the embedded original
    PeriodicNewsletterRequest dict.
    """

    JOB_ID = "job_id"
    STATUS = "status"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    STARTED_AT = "started_at"
    COMPLETED_AT = "completed_at"
    OUTPUT_DIR = "output_dir"
    ERROR_MESSAGE = "error_message"
    OPENAI_BATCH_ID = "openai_batch_id"
    REQUEST = "request"
    WEBHOOK_URL = "webhook_url"
    NOTIFICATION_EMAIL = "notification_email"


class ScheduleDocumentKeys:
    """Keys for schedule documents in the scheduled_newsletters collection.

    Covers the newsletter-config fields read by the scheduler
    (scheduler.newsletter_scheduler) and the schedules API (api.schedules)
    when building orchestrator state. Operational fields (enabled, next_run,
    last_run, ...) are accessed via DbFieldKeys; DOCUMENT_ID is the MongoDB
    primary key.
    """

    DOCUMENT_ID = "_id"
    NAME = "name"
    DATA_SOURCE_NAME = "data_source_name"
    WHATSAPP_CHAT_NAMES_TO_INCLUDE = "whatsapp_chat_names_to_include"
    DESIRED_LANGUAGE_FOR_SUMMARY = "desired_language_for_summary"
    SUMMARY_FORMAT = "summary_format"
    CONSOLIDATE_CHATS = "consolidate_chats"
    EMAIL_RECIPIENTS = "email_recipients"


class CacheDocumentKeys:
    """Keys for LLM-response cache documents in the llm_response_cache
    collection (db.repositories.cache.CacheRepository)."""

    CACHE_KEY = "cache_key"
    OPERATION_TYPE = "operation_type"
    INPUT_HASH = "input_hash"
    RESPONSE_DATA = "response_data"
    CREATED_AT = "created_at"
    EXPIRES_AT = "expires_at"


class SelectionUIFieldKeys:
    """Keys for the HITL discussion-selection JSON built by the consolidator
    graph (graphs.multi_chat_consolidator.graph).

    Values MUST stay byte-for-byte identical to the RankedDiscussionItem
    Pydantic schema (custom_types.api_schemas) and the matching TS interface;
    the selection UI deserializes against those field names.
    """

    FIRST_MESSAGE_DATE = "first_message_date"
    FIRST_MESSAGE_TIME = "first_message_time"
    RELEVANCE_SCORE = "relevance_score"
    REASONING = "reasoning"
