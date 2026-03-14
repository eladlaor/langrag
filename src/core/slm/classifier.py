"""
Message Classifier using SLM

Classifies WhatsApp messages into KEEP/FILTER/UNCERTAIN categories
to reduce expensive LLM API calls for low-quality messages.
"""

import asyncio
import logging
import time
from typing import Any

from config import get_settings
from core.slm.provider import OllamaProvider, get_slm_provider
from custom_types.field_keys import DiscussionKeys, DecryptionResultKeys
from custom_types.slm_schemas import (
    MessageClassification,
    MessageClassificationResult,
    MessageForClassification,
    BatchClassificationResult,
    SLMFilterStats,
)

logger = logging.getLogger(__name__)


# Classification prompt template
CLASSIFICATION_PROMPT = """Classify this WhatsApp message for a technical AI/LLM community.

Message: {message_text}
Sender: {sender_name}
Context: {context}

Output ONE of these three words followed by a short reason:
- KEEP: Technical content, questions, answers, resources, job posts
- FILTER: Spam, simple greetings, emoji-only, ads, off-topic
- UNCERTAIN: Ambiguous, needs review

Examples:
KEEP - asks about LangChain implementation
FILTER - just a greeting
UNCERTAIN - unclear intent

Your response (one word + reason):"""


class MessageClassifier:
    """
    Classifies messages using SLM to determine which should continue to LLM processing.

    Implements a three-tier classification:
    - KEEP: High-value messages that should be processed
    - FILTER: Low-value messages that can be skipped
    - UNCERTAIN: Borderline messages that need LLM review (fail-safe)

    Usage:
        classifier = MessageClassifier()
        results = await classifier.classify_batch(messages)
    """

    def __init__(
        self,
        provider: OllamaProvider | None = None,
        confidence_threshold: float | None = None,
        batch_size: int | None = None,
    ):
        """
        Initialize the classifier.

        Args:
            provider: OllamaProvider instance (default: singleton)
            confidence_threshold: Minimum confidence for classification (default from config)
            batch_size: Batch size for parallel classification (default from config)
        """
        settings = get_settings()
        slm_settings = settings.slm

        self.provider = provider or get_slm_provider()
        self.confidence_threshold = confidence_threshold or slm_settings.confidence_threshold
        self.batch_size = batch_size or slm_settings.batch_size

    def _build_prompt(self, message: MessageForClassification) -> str:
        """
        Build the classification prompt for a message.

        Args:
            message: Message to build prompt for

        Returns:
            Formatted prompt string
        """
        context = message.previous_message_summary or "No prior context"
        sender = message.sender_name or "Unknown"
        # Truncate long messages to keep prompt manageable
        text = message.text[:500] if len(message.text) > 500 else message.text

        return CLASSIFICATION_PROMPT.format(
            message_text=text,
            sender_name=sender,
            context=context,
        )

    def _parse_response(self, response: str, message_id: str) -> MessageClassificationResult:
        """
        Parse the SLM response into a classification result.

        Expected format: "CLASSIFICATION - reason"
        """
        response = response.strip().upper()

        # Extract classification and reason
        classification = MessageClassification.UNCERTAIN
        reason = ""
        confidence = 0.5  # Default to medium confidence for uncertain parsing

        # Try to parse the response
        if " - " in response:
            parts = response.split(" - ", 1)
            class_str = parts[0].strip()
            reason = parts[1].strip() if len(parts) > 1 else ""
        else:
            # Just the classification word
            class_str = response.split()[0] if response.split() else ""
            reason = ""

        # Map to classification enum
        if "KEEP" in class_str:
            classification = MessageClassification.KEEP
            confidence = 0.9
        elif "FILTER" in class_str:
            classification = MessageClassification.FILTER
            confidence = 0.85
        elif "UNCERTAIN" in class_str:
            classification = MessageClassification.UNCERTAIN
            confidence = 0.6
        else:
            # Could not parse - default to UNCERTAIN (fail-safe)
            classification = MessageClassification.UNCERTAIN
            reason = f"Unparseable response: {response[:50]}"
            confidence = 0.3

        # If confidence is below threshold, mark as UNCERTAIN
        if confidence < self.confidence_threshold:
            classification = MessageClassification.UNCERTAIN
            reason = f"Low confidence ({confidence:.2f}): {reason}"

        return MessageClassificationResult(
            classification=classification,
            reason=reason[:100],  # Limit reason length
            confidence=confidence,
            message_id=message_id,
        )

    async def classify_message(self, message: MessageForClassification) -> MessageClassificationResult:
        """
        Classify a single message.

        Args:
            message: Message to classify

        Returns:
            Classification result
        """
        try:
            prompt = self._build_prompt(message)
            response = await self.provider.complete(prompt)
            return self._parse_response(response, message.message_id)

        except Exception as e:
            # Log full error for debugging, truncate in result for display
            logger.warning(f"SLM classification failed for message_id={message.message_id}: {e}", exc_info=True)
            # Fail-safe: mark as UNCERTAIN so it continues to LLM
            return MessageClassificationResult(
                classification=MessageClassification.UNCERTAIN,
                reason=f"Classification error: {str(e)[:50]}",
                confidence=0.0,
                message_id=message.message_id,
            )

    async def classify_batch(self, messages: list[MessageForClassification]) -> BatchClassificationResult:
        """
        Classify a batch of messages in parallel.

        Uses asyncio.gather with limited concurrency for efficiency.

        Args:
            messages: List of messages to classify

        Returns:
            Batch classification result with statistics
        """
        start_time = time.time()
        result = BatchClassificationResult(
            total_messages=len(messages),
        )

        if not messages:
            return result

        # Check SLM availability first
        health = await self.provider.health_check()
        result.slm_available = health.available and health.model_loaded

        if not result.slm_available:
            logger.warning(f"SLM not available: {health.error_message}. " "Marking all messages as UNCERTAIN (fail-safe).")
            # Mark all as UNCERTAIN so they continue to LLM
            result.results = [
                MessageClassificationResult(
                    classification=MessageClassification.UNCERTAIN,
                    reason="SLM unavailable - needs LLM review",
                    confidence=0.0,
                    message_id=msg.message_id,
                )
                for msg in messages
            ]
            result.uncertain_count = len(messages)
            result.processing_time_ms = (time.time() - start_time) * 1000
            return result

        # Process in batches to limit concurrency
        all_results: list[MessageClassificationResult] = []

        for i in range(0, len(messages), self.batch_size):
            batch = messages[i : i + self.batch_size]
            tasks = [self.classify_message(msg) for msg in batch]
            batch_results = await asyncio.gather(*tasks)
            all_results.extend(batch_results)

        # Calculate statistics
        result.results = all_results
        for r in all_results:
            if r.classification == MessageClassification.KEEP:
                result.kept_count += 1
            elif r.classification == MessageClassification.FILTER:
                result.filtered_count += 1
            else:
                result.uncertain_count += 1

        result.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(f"SLM classified {result.total_messages} messages: " f"KEEP={result.kept_count}, FILTER={result.filtered_count}, " f"UNCERTAIN={result.uncertain_count} in {result.processing_time_ms:.0f}ms")

        return result


def convert_raw_messages_to_classification_input(
    messages: list[dict[str, Any]],
    include_context: bool = True,
) -> list[MessageForClassification]:
    """
    Convert raw message dictionaries to classification input format.

    Args:
        messages: List of raw message dictionaries from extraction
        include_context: Whether to include previous message context

    Returns:
        List of MessageForClassification objects
    """
    result = []
    previous_summary = None

    for i, msg in enumerate(messages):
        # Extract message ID - try various field names
        msg_id = msg.get(DiscussionKeys.ID) or msg.get("message_id") or msg.get(DecryptionResultKeys.EVENT_ID) or str(i)

        # Extract text content - handle Matrix format where 'content' is a dict with 'body' key
        raw_content = msg.get(DecryptionResultKeys.CONTENT)
        if isinstance(raw_content, dict):
            text = raw_content.get("body") or raw_content.get("text") or ""
        else:
            text = raw_content or msg.get("text") or msg.get("body") or msg.get("message") or ""

        # Extract sender name
        sender = msg.get("sender_name") or msg.get("sender") or msg.get("display_name") or msg.get("author") or None

        text_str = str(text) if not isinstance(text, str) else text

        classification_input = MessageForClassification(
            message_id=str(msg_id),
            text=text_str,
            sender_name=sender,
            previous_message_summary=str(previous_summary) if (include_context and previous_summary is not None) else None,
        )
        result.append(classification_input)

        # Update context for next message
        if include_context and text_str:
            previous_summary = text_str[:100] if len(text_str) > 100 else text_str

    return result


def filter_messages_by_classification(
    messages: list[dict[str, Any]],
    classification_results: BatchClassificationResult,
) -> tuple[list[dict[str, Any]], SLMFilterStats]:
    """
    Filter messages based on classification results.

    KEEP and UNCERTAIN messages are kept (fail-safe).
    FILTER messages are removed.

    Args:
        messages: Original list of messages
        classification_results: Results from classify_batch

    Returns:
        Tuple of (filtered messages, filter statistics)
    """
    stats = SLMFilterStats(
        enabled=True,
        total_input_messages=len(messages),
        slm_available=classification_results.slm_available,
    )

    if not classification_results.results:
        # No classification results - keep all messages (fail-safe)
        stats.total_output_messages = len(messages)
        stats.fallback_used = True
        return messages, stats

    # Create a mapping from message_id to classification
    classification_map: dict[str, MessageClassificationResult] = {r.message_id: r for r in classification_results.results}

    filtered_messages = []
    for i, msg in enumerate(messages):
        # Get message ID (same logic as convert_raw_messages_to_classification_input)
        msg_id = str(msg.get(DiscussionKeys.ID) or msg.get("message_id") or msg.get(DecryptionResultKeys.EVENT_ID) or i)

        result = classification_map.get(msg_id)

        if result is None:
            # No classification - keep the message (fail-safe)
            filtered_messages.append(msg)
            stats.uncertain += 1
            continue

        if result.classification == MessageClassification.FILTER:
            stats.filtered += 1
            logger.debug(f"Filtered message {msg_id}: {result.reason}")
        else:
            # KEEP or UNCERTAIN - keep the message
            filtered_messages.append(msg)
            if result.classification == MessageClassification.KEEP:
                stats.kept += 1
            else:
                stats.uncertain += 1

    stats.total_output_messages = len(filtered_messages)
    stats.calculate_filter_rate()
    stats.processing_time_ms = classification_results.processing_time_ms

    logger.info(f"SLM filter: {stats.total_input_messages} → {stats.total_output_messages} messages " f"({stats.filter_rate:.1f}% filtered)")

    return filtered_messages, stats
