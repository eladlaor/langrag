"""
LangRAG Custom Exception Hierarchy

Provides domain-specific exceptions for fail-fast error handling with clear
categorization and proper exception chaining support.

Usage:
    from custom_types.exceptions import LLMError, ConfigurationError

    try:
        response = llm.call(...)
    except LLMError as e:
        logger.error(f"LLM call failed: {e}")
        raise

Exception Hierarchy:
    LangRAGError (base)
    ├── ConfigurationError - Missing/invalid configuration
    ├── ExtractionError - Data extraction failures
    │   ├── BeeperError - Beeper/Matrix specific
    │   └── DecryptionError - Message decryption
    ├── ProcessingError - Data transformation failures
    │   ├── PreprocessingError - Preprocessing stage
    │   └── TranslationError - Translation failures
    ├── LLMError - LLM provider errors
    │   ├── LLMResponseError - Invalid LLM response
    │   └── LLMRateLimitError - Rate limiting
    ├── GenerationError - Newsletter generation
    │   └── RankingError - Discussion ranking
    ├── DeliveryError - Newsletter delivery
    │   ├── EmailDeliveryError - Email sending
    │   └── SubstackError - Substack publishing
    └── ValidationError - Input validation
        └── FileValidationError - File-related validation
"""


class LangRAGError(Exception):
    """
    Base exception for all LangRAG application errors.

    All domain-specific exceptions inherit from this class, enabling
    catch-all handling when needed while maintaining specificity.
    """

    pass


# =============================================================================
# CONFIGURATION ERRORS
# =============================================================================


class ConfigurationError(LangRAGError):
    """
    Missing or invalid configuration.

    Raised when required environment variables, settings, or configuration
    files are missing or contain invalid values.

    Examples:
        - Missing OPENAI_API_KEY
        - Invalid BEEPER_ACCESS_TOKEN
        - Malformed config.yaml
    """

    pass


# =============================================================================
# EXTRACTION / INGESTION ERRORS
# =============================================================================


class ExtractionError(LangRAGError):
    """
    Failed to extract data from source.

    Base class for all data extraction failures from external sources
    like Beeper, WhatsApp, or other messaging platforms.
    """

    pass


class BeeperError(ExtractionError):
    """
    Beeper/Matrix specific extraction failure.

    Raised when communication with Beeper's Matrix server fails,
    including authentication, room lookup, or message fetching errors.
    """

    pass


class DecryptionError(BeeperError):
    """
    Message decryption failed.

    Raised when encrypted messages cannot be decrypted due to
    missing keys, invalid session, or corrupted ciphertext.
    """

    pass


class RoomNotFoundError(BeeperError):
    """
    Matrix room not found.

    Raised when the specified chat/room cannot be found in the
    user's Matrix account.
    """

    pass


# =============================================================================
# PROCESSING ERRORS
# =============================================================================


class ProcessingError(LangRAGError):
    """
    Failed to process/transform data.

    Base class for all data processing failures during the pipeline
    stages like preprocessing, translation, or discussion separation.
    """

    pass


class PreprocessingError(ProcessingError):
    """
    Failed during preprocessing stage.

    Raised when message parsing, normalization, or sender ID mapping fails.
    """

    pass


class TranslationError(ProcessingError):
    """
    Translation failed.

    Raised when LLM-based translation of messages or content fails.
    """

    pass


class DiscussionSeparationError(ProcessingError):
    """
    Discussion separation failed.

    Raised when the LLM fails to separate messages into distinct discussions.
    """

    pass


# =============================================================================
# LLM ERRORS
# =============================================================================


class LLMError(LangRAGError):
    """
    LLM provider error.

    Base class for all LLM-related failures including API errors,
    invalid responses, and rate limiting.
    """

    pass


class LLMResponseError(LLMError):
    """
    Invalid or unexpected LLM response.

    Raised when the LLM response doesn't match expected schema,
    is missing required fields, or contains invalid data.
    """

    pass


class LLMRateLimitError(LLMError):
    """
    Rate limit exceeded.

    Raised when the LLM API returns a rate limit error.
    May include retry-after information.
    """

    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMContextLengthError(LLMError):
    """
    Context length exceeded.

    Raised when input exceeds the model's context window.
    """

    pass


# =============================================================================
# GENERATION ERRORS
# =============================================================================


class GenerationError(LangRAGError):
    """
    Newsletter generation failed.

    Base class for failures during the content generation phase,
    including ranking, summarization, and formatting.
    """

    pass


class RankingError(GenerationError):
    """
    Discussion ranking failed.

    Raised when the LLM fails to rank discussions or returns
    an invalid ranking structure.
    """

    pass


class ContentGenerationError(GenerationError):
    """
    Newsletter content generation failed.

    Raised when the LLM fails to generate newsletter content
    from ranked discussions.
    """

    pass


class LinkEnrichmentError(GenerationError):
    """
    Link enrichment failed.

    Raised when web search or link metadata extraction fails
    during newsletter enrichment.
    """

    pass


# =============================================================================
# DELIVERY ERRORS
# =============================================================================


class DeliveryError(LangRAGError):
    """
    Failed to deliver newsletter.

    Base class for all newsletter delivery failures including
    email, Substack, and webhook delivery.
    """

    pass


class EmailDeliveryError(DeliveryError):
    """
    Email sending failed.

    Raised when email delivery via SendGrid, SMTP2GO, or other
    providers fails.
    """

    pass


class SubstackError(DeliveryError):
    """
    Substack publishing failed.

    Raised when authentication with Substack fails or when
    draft/post creation fails.
    """

    pass


class WebhookDeliveryError(DeliveryError):
    """
    Webhook delivery failed.

    Raised when HTTP POST to configured webhook URL fails.
    """

    pass


# =============================================================================
# VALIDATION ERRORS
# =============================================================================


class ValidationError(LangRAGError):
    """
    Input validation failed.

    Raised when user input, API request parameters, or internal
    data doesn't meet required constraints.
    """

    pass


class FileValidationError(ValidationError):
    """
    File-related validation failed.

    Raised when required files are missing, empty, or contain
    invalid data.
    """

    pass


class DateRangeError(ValidationError):
    """
    Invalid date range.

    Raised when start_date > end_date or dates are in invalid format.
    """

    pass


class ChatNameError(ValidationError):
    """
    Invalid or unknown chat name.

    Raised when the specified WhatsApp chat name doesn't exist
    or isn't accessible.
    """

    pass


# =============================================================================
# WORKFLOW ERRORS
# =============================================================================


class WorkflowError(LangRAGError):
    """
    LangGraph workflow execution failed.

    Base class for failures during workflow orchestration.
    """

    pass


class WorkflowStateError(WorkflowError):
    """
    Invalid workflow state.

    Raised when required state fields are missing or invalid
    during workflow execution.
    """

    pass


class WorkflowTimeoutError(WorkflowError):
    """
    Workflow execution timed out.

    Raised when a workflow exceeds its configured timeout.
    """

    pass
