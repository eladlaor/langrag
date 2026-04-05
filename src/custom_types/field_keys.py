"""
Field Key Constants for Discussion, Ranking, Newsletter, and MMR Data Structures.

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
    FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP = "first_message_in_disussion_timestamp"
    SAMPLE_MESSAGES = "sample_messages"
    MESSAGES = "messages"
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
