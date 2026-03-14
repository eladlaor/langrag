from core.ingestion.preprocessors.base import DataPreprocessorInterface

import json
import logging
import os
import re
from typing import Any
from datetime import datetime, UTC
from constants import (
    DataSources,
    LlmInputPurposes,
    PreprocessingOperations,
    DEFAULT_LANGUAGE,
    DEFAULT_HTML_LANGUAGE,
    OUTPUT_FILENAME_MESSAGES_PROCESSED,
    OUTPUT_FILENAME_MESSAGES_PROCESSED_TEMP,
    OUTPUT_FILENAME_SENDER_MAP,
    OUTPUT_FILENAME_MESSAGE_STATS,
    OUTPUT_FILENAME_SEPARATE_DISCUSSIONS,
    MATRIX_KEY_RELATES_TO,
    MATRIX_KEY_IN_REPLY_TO,
    OLDER_MESSAGE_PLACEHOLDER,
)
from custom_types.exceptions import (
    PreprocessingError,
    TranslationError,
    DiscussionSeparationError,
    ValidationError,
    FileValidationError,
    LLMResponseError,
)
from custom_types.field_keys import DiscussionKeys, DecryptionResultKeys
from utils.llm import get_llm_caller
from custom_types.common import LlmResponseSeparateDiscussions


# This class should hold some common preprocessing implementations for every whatsapp chat.
class DataPreprocessorWhatsappChatsBase(DataPreprocessorInterface):
    PREPROCESSING_OPERATIONS_MAP: dict[str, Any] = None

    def __init__(self, source_name: str, chat_name: str, **kwargs):
        try:
            super().__init__(**kwargs)
            self.source_name = source_name
            self.chat_name = chat_name

            self.PREPROCESSING_OPERATIONS_MAP = {
                DataSources.WHATSAPP_GROUP_CHAT_MESSAGES: {
                    PreprocessingOperations.PARSE_AND_STANDARDIZE_RAW_WHATSAPP_MESSAGES_WITH_STATS: self._parse_and_standardize_raw_whatsapp_messages_with_stats,
                    PreprocessingOperations.TRANSLATE_WHATSAPP_GROUP_CHAT_MESSAGES: self._translate_whatsapp_group_chat_messages,
                    PreprocessingOperations.SEPARATE_WHATSAPP_GROUP_MESSAGE_DISCUSSIONS: self._separate_whatsapp_group_message_discussions,
                }
            }

        except Exception as e:
            error_message = f"Error initializing DataPreprocessorWhatsappChatsBase: {e}"
            logging.error(error_message)
            raise PreprocessingError(error_message) from e

    def _sanitize_malformed_unicode_escapes(self, text: str) -> str:
        """
        Sanitize malformed Unicode escape sequences that cause JSON parsing errors.
        Fixes sequences like \u00005d9 (6 chars) to \u05d9 (4 chars) or removes them if invalid.
        """
        if not isinstance(text, str):
            return text

        # Pattern to match malformed Unicode escapes: \u followed by more than 4 hex digits
        # This catches cases like \u00005d9, \u0005e4, etc.
        malformed_pattern = r"\\u([0-9a-fA-F]{5,})"

        def fix_unicode_escape(match):
            hex_digits = match.group(1)

            # Take the last 4 digits for the Unicode escape
            if len(hex_digits) >= 4:
                # Use the last 4 characters as the Unicode code point
                valid_hex = hex_digits[-4:]
                try:
                    # Verify it's a valid Unicode code point
                    chr(int(valid_hex, 16))
                    return f"\\u{valid_hex}"
                except (ValueError, OverflowError):
                    # If invalid, remove the escape sequence
                    logging.warning(f"Removed invalid Unicode escape: \\u{hex_digits}")
                    return ""
            else:
                # If less than 4 digits, pad with zeros
                valid_hex = hex_digits.zfill(4)
                return f"\\u{valid_hex}"

        try:
            sanitized_text = re.sub(malformed_pattern, fix_unicode_escape, text)
            if sanitized_text != text:
                logging.debug("Sanitized malformed Unicode escapes in text")
            return sanitized_text
        except Exception as e:
            logging.warning(f"Error sanitizing Unicode escapes: {e}")
            return text

    async def preprocess_data(self, data_source_type: str, preprocessing_operations: list[str], **kwargs) -> list[Any]:
        try:
            import asyncio
            preprocess_results = []

            for preprocessing_operation in preprocessing_operations:
                preprocess_func = self.PREPROCESSING_OPERATIONS_MAP.get(data_source_type, {}).get(preprocessing_operation)
                if not preprocess_func:
                    raise ValueError(f"No preprocess function found for data source type: {data_source_type} and data eventual purpose: {preprocessing_operation}")

                # Support both sync and async preprocessing functions
                if asyncio.iscoroutinefunction(preprocess_func):
                    res = await preprocess_func(**kwargs)
                else:
                    res = preprocess_func(**kwargs)
                preprocess_results.append(res)

            return preprocess_results

        except ValidationError:
            raise  # Re-raise validation errors as-is
        except Exception as e:
            error_message = f"Error preprocessing data: {e}"
            logging.error(error_message)
            raise PreprocessingError(error_message) from e

    def _parse_and_standardize_raw_whatsapp_messages_with_stats(self, **kwargs) -> str:
        try:
            data_source_path: str = kwargs.get("data_source_path")
            if not data_source_path:
                raise ValueError("data_source_path is required")

            output_path_base = kwargs.get("output_dir")
            if not output_path_base:
                raise ValueError("output_dir is required")

            chunk_size = kwargs.get("chunk_size", 1000)  # Processing 1000 messages at a time
            if chunk_size <= 0 or not isinstance(chunk_size, int):
                raise ValueError("chunk_size must be an int greater than 0")

            should_filter_decryption_errors = kwargs.get("should_filter_decryption_errors", True)  # Default to filtering out decryption errors
            should_generate_message_stats = kwargs.get("should_generate_message_stats", True)  # Default to generating message stats
            should_use_utc = kwargs.get("should_use_utc", False)  # Option to use UTC time zone
            should_clean_message_ids = kwargs.get("should_clean_message_ids", True)  # Default to cleaning message IDs

            now = datetime.now()
            now_utc = datetime.now(UTC)
            logging.info(f"Current local time: {now.strftime('%Y-%m-%d %H:%M:%S')} {now.astimezone().tzinfo}")
            logging.info(f"Current UTC time: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            try:
                with open(data_source_path) as file:
                    raw_whatsapp_group_chat_messages = json.load(file)
            except FileNotFoundError as e:
                error_message = f"Data source file not found: {data_source_path}"
                logging.error(error_message)
                raise FileValidationError(error_message) from e
            except json.JSONDecodeError as e:
                error_message = f"Invalid JSON in data source: {data_source_path}: {e}"
                logging.error(error_message)
                raise PreprocessingError(error_message) from e
            except Exception as e:
                error_message = f"Error loading raw whatsapp group chat messages: {e}. data_source_path: {data_source_path}"
                logging.error(error_message)
                raise PreprocessingError(error_message) from e

            total_messages = len(raw_whatsapp_group_chat_messages)
            if total_messages == 0:
                logging.warning(f"No messages found in data source path: {data_source_path}. Creating empty processed messages file.")

                # Create empty output files for consistency
                final_output_path = os.path.join(output_path_base, OUTPUT_FILENAME_MESSAGES_PROCESSED)
                sender_map_path = os.path.join(output_path_base, OUTPUT_FILENAME_SENDER_MAP)
                stats_output_path = os.path.join(output_path_base, OUTPUT_FILENAME_MESSAGE_STATS)

                # Save empty processed messages
                with open(final_output_path, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2, ensure_ascii=False)

                # Save empty sender map
                with open(sender_map_path, "w") as f:
                    json.dump({}, f, indent=2)

                # Save empty stats if requested
                if kwargs.get("should_generate_message_stats", True):
                    empty_stats = {"total_messages": 0, "unique_senders": 0, "date_range": None, "messages_per_sender": {}, "messages_per_day": {}, "reply_statistics": {"total_replies": 0, "messages_with_replies": 0, "reply_percentage": 0.0}}
                    with open(stats_output_path, "w") as f:
                        json.dump(empty_stats, f, ensure_ascii=False, indent=4)

                logging.info(f"Created empty processed messages file: {final_output_path}")
                return final_output_path

            total_chunks = (total_messages + chunk_size - 1) // chunk_size  # ceiling division.

            logging.info(f"Processing {total_messages} messages in {total_chunks} chunks")

            try:
                # TODO: super dependent on Beeper format. Let's ease this dependency.
                first_ts = raw_whatsapp_group_chat_messages[0][DecryptionResultKeys.ORIGIN_SERVER_TS]
                last_ts = raw_whatsapp_group_chat_messages[-1][DecryptionResultKeys.ORIGIN_SERVER_TS]
                first_date = datetime.fromtimestamp(first_ts / 1000, tz=UTC if should_use_utc else None)
                last_date = datetime.fromtimestamp(last_ts / 1000, tz=UTC if should_use_utc else None)
                logging.info(f"Raw messages timestamp range: {first_date.strftime('%Y-%m-%d %H:%M:%S')} to {last_date.strftime('%Y-%m-%d %H:%M:%S')}")
            except (KeyError, IndexError, TypeError) as e:
                error_message = f"Could not extract timestamp range from raw messages: {e}"
                logging.error(error_message)
                raise PreprocessingError(error_message) from e

            all_parsed_messages = []
            sender_map = {}  # an anonymization mechanism that converts real WhatsApp user identifiers into generic "user_X" IDs while maintaining consistent mappings across multiple processing runs. This is important for privacy and for generating consistent analytics without exposing real user identities.

            temp_output_path = os.path.join(output_path_base, OUTPUT_FILENAME_MESSAGES_PROCESSED_TEMP)
            final_output_path = os.path.join(output_path_base, OUTPUT_FILENAME_MESSAGES_PROCESSED)
            sender_map_path = os.path.join(output_path_base, OUTPUT_FILENAME_SENDER_MAP)
            stats_output_path = os.path.join(output_path_base, OUTPUT_FILENAME_MESSAGE_STATS)

            # Define placeholder constant for older messages
            older_message_placeholder = OLDER_MESSAGE_PLACEHOLDER

            # just creating the files:
            with open(temp_output_path, "w") as f:
                json.dump(all_parsed_messages, f)
            with open(sender_map_path, "w") as f:
                json.dump(sender_map, f)

            # Load the existing sender map
            with open(sender_map_path) as f:
                sender_map = json.load(f)

            # Process all messages using our deterministic parser in chunks
            logging.info(f"Parsing {total_messages} messages with deterministic parser")

            for chunk_index in range(total_chunks):
                start_idx = chunk_index * chunk_size
                end_idx = min(start_idx + chunk_size, total_messages)

                logging.info(f"Processing chunk {chunk_index + 1}/{total_chunks} (messages {start_idx + 1}-{end_idx})")

                current_chunk = raw_whatsapp_group_chat_messages[start_idx:end_idx]

                chunk_result = self._parse_messages(raw_messages=current_chunk, existing_sender_map=sender_map)

                if not isinstance(chunk_result, dict):
                    raise ValueError(f"Expected dict from _parse_messages, got {type(chunk_result)}")

                # TODO: rename to be clear that this is an updated sender map.
                if "sender_map" not in chunk_result:
                    raise ValueError("_parse_messages result missing required 'sender_map' field")

                if DiscussionKeys.MESSAGES not in chunk_result:
                    raise ValueError("_parse_messages result missing required 'messages' field")

                updated_sender_map = chunk_result["sender_map"]

                with open(sender_map_path, "w") as f:
                    json.dump(updated_sender_map, f, indent=2)

                # Append chunk messages to all_parsed_messages
                all_parsed_messages.extend(chunk_result[DiscussionKeys.MESSAGES])
                # Save progress to temp file after each chunk
                with open(temp_output_path, "w") as f:
                    json.dump(all_parsed_messages, f, ensure_ascii=False, indent=2)

                logging.info(f"Completed chunk {chunk_index + 1}/{total_chunks}. Total messages processed: {len(all_parsed_messages)}")

            logging.info(f"Initial parsing complete for {len(all_parsed_messages)} messages. Post-processing...")

            # Validate that all reply references point to existing messages
            valid_message_ids = {msg[DiscussionKeys.ID] for msg in all_parsed_messages}  # Using a set for O(1) lookups
            replies_to_older_messages = [msg for msg in all_parsed_messages if msg.get("replies_to") and msg["replies_to"] not in valid_message_ids]

            if replies_to_older_messages:
                logging.info(f"Found {len(replies_to_older_messages)} messages referencing messages not in the current dataset")
                for msg in replies_to_older_messages:
                    original_reference = msg["replies_to"]
                    msg["replies_to"] = older_message_placeholder
                    logging.debug(f"Message {msg[DiscussionKeys.ID]} references message {original_reference} not in dataset.")

            logging.info("Reply references validation complete. Filtering out decryption error messages if requested...")

            if should_filter_decryption_errors:
                logging.warning("-" * 10)
                logging.warning("Filtering out decryption error messages is not implemented yet!")
                logging.warning("-" * 10)

            final_messages = all_parsed_messages
            if should_clean_message_ids:
                logging.info("Cleaning message IDs...")

                # Create ID mapping dictionary for the entire dataset
                id_mapping = {}
                next_id = 1000  # Start with 1000 to get 4-digit IDs

                # First pass: create mappings from original IDs to short IDs
                for message in all_parsed_messages:
                    original_id = message[DiscussionKeys.ID]
                    if original_id not in id_mapping:
                        id_mapping[original_id] = str(next_id)
                        next_id += 1

                # Second pass: create cleaned messages with short IDs
                cleaned_messages = []
                for message in all_parsed_messages:
                    # Create a copy of the message without modifying the original
                    cleaned_message = message.copy()

                    # Preserve original event_id before replacing with short ID
                    original_event_id = message[DiscussionKeys.ID]
                    cleaned_message["matrix_event_id"] = original_event_id

                    # Replace ID with short ID
                    cleaned_message[DiscussionKeys.ID] = id_mapping[original_event_id]

                    # Update replies_to to use the new short IDs
                    if message.get("replies_to") is not None:
                        if message["replies_to"] == older_message_placeholder:
                            # Keep the older-message placeholder as is
                            cleaned_message["replies_to"] = older_message_placeholder
                        elif message["replies_to"] in id_mapping:
                            cleaned_message["replies_to"] = id_mapping[message["replies_to"]]
                        else:
                            # This is a fallback - should rarely happen after our earlier fix
                            logging.warning(f"Message {message[DiscussionKeys.ID]} references non-existent message {message['replies_to']}")
                            cleaned_message["replies_to"] = older_message_placeholder
                    else:
                        # Remove null replies_to fields
                        if "replies_to" in cleaned_message:
                            del cleaned_message["replies_to"]

                    cleaned_messages.append(cleaned_message)

                final_messages = cleaned_messages
                logging.info(f"Generated {len(id_mapping)} unique short IDs")

            # Save the final processed messages
            logging.info(f"Saving {len(final_messages)} final processed messages")
            with open(final_output_path, "w", encoding="utf-8") as f:
                json.dump(final_messages, f, indent=2, ensure_ascii=False)

            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
                    logging.info(f"Cleaned up temporary file: {temp_output_path}")
            except Exception as e:
                logging.warning(f"Failed to cleanup temporary file {temp_output_path}: {e}")

            if should_generate_message_stats:
                message_stats = self._analyze_message_stats(final_messages)

                with open(stats_output_path, "w") as f:
                    json.dump(message_stats, f, ensure_ascii=False, indent=4)

                logging.info(f"Saved message stats to {stats_output_path}")

            return final_output_path

        except (ValidationError, FileValidationError, PreprocessingError):
            raise  # Re-raise known exceptions as-is
        except Exception as e:
            error_message = f"Error in _parse_and_standardize_raw_whatsapp_messages_with_stats: {e}"
            logging.error(error_message)
            raise PreprocessingError(error_message) from e

    def _translate_whatsapp_group_chat_messages(self, **kwargs) -> Any:
        try:
            data_source_path = kwargs.get("data_source_path")
            if not data_source_path:
                error_message = "data_source_path is required"
                logging.error(error_message)
                raise ValidationError(error_message)

            if not os.path.exists(data_source_path):
                raise FileValidationError(f"Data source path does not exist: {data_source_path}")

            # Check if output_dir is provided, use it instead of the default
            output_path_base = kwargs.get("output_dir")
            if not output_path_base:
                error_message = "output_dir is required"
                logging.error(error_message)
                raise ValidationError(error_message)

            # TODO: not hardcoded. parametrized of course.
            translate_from = DEFAULT_HTML_LANGUAGE
            translate_to = DEFAULT_LANGUAGE

            batch_size = kwargs.get("batch_size", 100)  # defaults to 100 messages per batch.

            translated_output_path = os.path.join(output_path_base, f"messages_translated_to_{translate_to}.json")
            recovery_file_path = os.path.join(output_path_base, f"{translate_to}_translation_progress.json")

            logging.info(f"Will save translated messages to: {translated_output_path}")

            logging.info(f"Loading messages from {data_source_path}")
            with open(data_source_path) as file:
                all_messages = json.load(file)

            total_messages = len(all_messages)
            logging.info(f"Found {total_messages} messages to translate from {translate_from} to {translate_to}.")

            # Handle empty message set gracefully
            if total_messages == 0:
                logging.warning("No messages to translate. Creating empty translated messages file.")
                with open(translated_output_path, "w") as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
                logging.info(f"Empty translated messages saved to: {translated_output_path}")
                return []

            # Use Batch API for translation (50% cost savings)
            from utils.llm.batch import BatchTranslator
            from config import get_settings

            settings = get_settings()
            translator = BatchTranslator(model=settings.llm.default_model, provider_name=settings.llm.provider)

            translated_messages, batch_info = translator.translate_messages_batch(all_messages=all_messages, translate_from=translate_from, translate_to=translate_to, batch_size=batch_size, timeout_minutes=120)

            # Save recovery file
            with open(recovery_file_path, "w") as f:
                json.dump(translated_messages, f, ensure_ascii=False, indent=2)

            with open(translated_output_path, "w") as f:
                json.dump(translated_messages, f, ensure_ascii=False, indent=2)

            translation_stats = {
                "total_messages": total_messages,
                "translated_count": batch_info.get("completed_requests", 0),
                "failed_count": batch_info.get("failed_requests", 0),
                "batch_id": batch_info.get("batch_id"),
                "provider": batch_info.get("provider"),
            }

            logging.info(f"Translation complete. Stats: {translation_stats}")
            logging.info(f"Translated messages saved to: {translated_output_path}")

            # Log the metadata but return the messages directly
            translation_metadata = {"translated_messages_count": total_messages, "translated_messages_path": translated_output_path, "translation_stats": translation_stats}
            logging.info(f"Translation metadata: {translation_metadata}")

            # Return the messages directly instead of a dictionary containing them
            return translated_messages

        except (TranslationError, LLMResponseError, ValidationError, FileValidationError):
            raise  # Re-raise known exceptions as-is
        except Exception as e:
            error_message = f"Error translating whatsapp group chat messages: {e}"
            logging.error(error_message)
            raise TranslationError(error_message) from e

    async def _separate_whatsapp_group_message_discussions(self, **kwargs) -> Any:
        try:
            data_source_path = kwargs.get("data_source_path")
            if not data_source_path:
                raise ValueError("data_source_path is required")
            if not os.path.exists(data_source_path):
                raise ValueError(f"Data source path does not exist: {data_source_path}")

            base_output_dir = kwargs.get("output_dir")
            if not base_output_dir:
                raise ValueError("output_dir is required")
            os.makedirs(base_output_dir, exist_ok=True)

            separate_discussions_file_path = os.path.join(base_output_dir, OUTPUT_FILENAME_SEPARATE_DISCUSSIONS)

            llm_caller = get_llm_caller()

            logging.info(f"Loading translated messages from {data_source_path}")
            with open(data_source_path) as file:
                all_messages = json.load(file)

            total_messages = len(all_messages)
            logging.info(f"Found {total_messages} messages to organize into discussions")

            # Handle empty message set gracefully
            if total_messages == 0:
                logging.warning("No messages to organize into discussions. Creating empty discussions file.")
                empty_discussions = {DiscussionKeys.DISCUSSIONS: []}
                with open(separate_discussions_file_path, "w") as f:
                    json.dump(empty_discussions, f, ensure_ascii=False, indent=2)
                logging.info(f"Empty discussions saved to: {separate_discussions_file_path}")
                return {"discussions_count": 0, "discussions_path": separate_discussions_file_path}

            # TODO: add token counting here and a mechanism to make sure we don't exceed context limits.
            if total_messages > 500:
                logging.warning(f"Large number of messages ({total_messages}). This might exceed context limits. Consider filtering or batching.")

            # TODO: make sure indeed this is the format in which the response returns, cause it might be a single item list.
            result: LlmResponseSeparateDiscussions = await llm_caller.call_with_structured_output(purpose=LlmInputPurposes.SEPARATE_DISCUSSIONS, response_schema=LlmResponseSeparateDiscussions, messages=all_messages, chat_name=self.chat_name)

            # Validate discussions - Handle both direct dict response and Pydantic model response
            if isinstance(result, dict) and DiscussionKeys.DISCUSSIONS in result:
                # Create discussions from the raw dict
                discussions = result[DiscussionKeys.DISCUSSIONS]
                logging.info(f"Received {len(discussions)} discussions as dictionary")
            elif hasattr(result, "discussions"):
                # Already a Pydantic model
                discussions = result.discussions
                logging.info(f"Received {len(discussions)} discussions as Pydantic model")
            else:
                raise ValueError(f"Expected '{DiscussionKeys.DISCUSSIONS}' field in response, but got: {result}")

            # Process discussions to ensure consistent format
            processed_discussions = []
            for i, discussion in enumerate(discussions):
                # Convert dict to a standard format if needed
                if isinstance(discussion, dict):
                    # Ensure each discussion has the required fields
                    if not discussion.get(DiscussionKeys.ID):
                        discussion[DiscussionKeys.ID] = f"discussion_{i+1}"

                    # ALWAYS set group_name from the known chat_name
                    # (don't rely on LLM output which may be incorrect or missing)
                    discussion[DiscussionKeys.GROUP_NAME] = self.chat_name

                    # Calculate num_messages if not set
                    if not discussion.get(DiscussionKeys.NUM_MESSAGES):
                        discussion[DiscussionKeys.NUM_MESSAGES] = len(discussion.get(DiscussionKeys.MESSAGES, []))

                    # Calculate first message timestamp if not set
                    if not discussion.get(DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP) and discussion.get(DiscussionKeys.MESSAGES):
                        try:
                            discussion[DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP] = min(msg.get("timestamp", 0) for msg in discussion[DiscussionKeys.MESSAGES])
                        except Exception as e:
                            logging.warning(f"Error calculating first message timestamp: {e}")
                            discussion[DiscussionKeys.FIRST_MESSAGE_IN_DISCUSSION_TIMESTAMP] = 0
                else:
                    # It's a Pydantic model, ensure fields are set
                    if not discussion.id:
                        discussion.id = f"discussion_{i+1}"

                    # ALWAYS set group_name from the known chat_name
                    # (don't rely on LLM output which may be incorrect or missing)
                    discussion.group_name = self.chat_name

                    # Calculate num_messages if not set
                    if not discussion.num_messages:
                        discussion.num_messages = len(discussion.messages)

                    # Calculate first message timestamp if not set
                    if not discussion.first_message_in_disussion_timestamp and discussion.messages:
                        try:
                            discussion.first_message_in_disussion_timestamp = min(msg.timestamp for msg in discussion.messages)
                        except Exception as e:
                            logging.warning(f"Error calculating first message timestamp: {e}")
                            discussion.first_message_in_disussion_timestamp = 0

                processed_discussions.append(discussion)

            # Save the discussions
            logging.info(f"Saving {len(processed_discussions)} discussions to {separate_discussions_file_path}")

            # Convert to dict for JSON serialization
            discussions_dict = {DiscussionKeys.DISCUSSIONS: []}
            for discussion in processed_discussions:
                if isinstance(discussion, dict):
                    discussions_dict[DiscussionKeys.DISCUSSIONS].append(discussion)
                else:
                    # It's a Pydantic model, convert to dict
                    discussions_dict[DiscussionKeys.DISCUSSIONS].append(discussion.model_dump())

            with open(separate_discussions_file_path, "w") as f:
                json.dump(discussions_dict, f, ensure_ascii=False, indent=2)

            return {"discussions_count": len(processed_discussions), "discussions_path": separate_discussions_file_path}

        except (DiscussionSeparationError, LLMResponseError, ValidationError, FileValidationError):
            raise  # Re-raise known exceptions as-is
        except Exception as e:
            error_message = f"Error separating whatsapp group message discussions: {e}"
            logging.error(error_message)
            raise DiscussionSeparationError(error_message) from e

    def _parse_messages(self, raw_messages: list[dict[str, Any]], existing_sender_map: dict[str, str] = None) -> dict[str, Any]:
        """
        Parse raw WhatsApp messages from Beeper/Matrix into a structured format.

        Args:
            raw_messages: List of raw message dictionaries from Beeper/Matrix API
            existing_sender_map: Optional dictionary mapping real sender names to anonymized IDs

        Returns:
            Dict containing 'messages' (list of structured message objects) and 'sender_map'
        """
        try:
            # Initialize sender_map from existing or create new
            sender_map = existing_sender_map.copy() if existing_sender_map else {}

            # Track the highest user number to continue from there for new senders
            max_user_num = 0
            for sender_id in sender_map.values():
                if sender_id.startswith("user_"):
                    try:
                        user_num = int(sender_id.split("_")[1])
                        max_user_num = max(max_user_num, user_num)
                    except (ValueError, IndexError):
                        continue

            structured_messages = []

            for msg in raw_messages:
                # Skip if not a valid message
                if not isinstance(msg, dict):
                    logging.warning(f"Skipping invalid message format: {type(msg)}")
                    continue

                # Extract event_id as message ID
                msg_id = msg.get(DecryptionResultKeys.EVENT_ID)
                if not msg_id:
                    logging.warning("Skipping message without event_id")
                    continue

                # Extract timestamp
                timestamp = msg.get(DecryptionResultKeys.ORIGIN_SERVER_TS)
                if not timestamp:
                    logging.warning(f"Skipping message {msg_id} without timestamp")
                    continue

                # Extract sender
                sender = msg.get("sender")
                if not sender:
                    logging.warning(f"Skipping message {msg_id} without sender")
                    continue

                # Assign sender_id from map or create new
                if sender not in sender_map:
                    max_user_num += 1
                    sender_map[sender] = f"user_{max_user_num}"
                sender_id = sender_map[sender]

                # Extract content body
                content = msg.get("content", {})
                body = content.get("body", "")

                # Sanitize malformed Unicode escape sequences
                body = self._sanitize_malformed_unicode_escapes(body)

                # Check for replies
                replies_to = None
                if MATRIX_KEY_RELATES_TO in content:
                    relates_to = content.get(MATRIX_KEY_RELATES_TO, {})
                    if MATRIX_KEY_IN_REPLY_TO in relates_to:
                        replies_to = relates_to.get(MATRIX_KEY_IN_REPLY_TO, {}).get(DecryptionResultKeys.EVENT_ID)

                # Create structured message
                structured_msg = {DiscussionKeys.ID: msg_id, "timestamp": timestamp, "sender_id": sender_id, "replies_to": replies_to, "content": body}

                structured_messages.append(structured_msg)

            return {DiscussionKeys.MESSAGES: structured_messages, "sender_map": sender_map}

        except Exception as e:
            error_message = f"Error parsing messages: {e}"
            logging.error(error_message)
            raise PreprocessingError(error_message) from e

    def _analyze_message_stats(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Analyze message statistics including counts by day and sender.

        Args:
            messages: List of structured message objects

        Returns:
            Dict containing statistics about the messages
        """
        try:
            if not messages:
                return {"total_message_count": 0, "messages_by_day": {}, "messages_by_sender": {}, "date_range": {"start_date": None, "end_date": None}}

            # Sort messages by timestamp
            sorted_messages = sorted(messages, key=lambda msg: msg.get("timestamp", 0))

            # Initialize tracking variables
            messages_by_day = {}
            messages_by_sender = {}
            start_timestamp = float("inf")
            end_timestamp = 0

            # Process each message
            for msg in sorted_messages:
                # Skip messages without timestamp
                if "timestamp" not in msg:
                    continue

                timestamp = msg["timestamp"]

                # Convert timestamp to date string
                date_obj = datetime.fromtimestamp(timestamp / 1000)  # Convert ms to seconds
                date_str = date_obj.strftime("%Y-%m-%d")

                # Update counts
                messages_by_day[date_str] = messages_by_day.get(date_str, 0) + 1

                sender_id = msg.get("sender_id", "unknown")
                messages_by_sender[sender_id] = messages_by_sender.get(sender_id, 0) + 1

                # Update timestamp range
                start_timestamp = min(start_timestamp, timestamp)
                end_timestamp = max(end_timestamp, timestamp)

            # Calculate date range
            start_date = None
            if start_timestamp != float("inf"):
                start_date = datetime.fromtimestamp(start_timestamp / 1000).strftime("%Y-%m-%d")

            end_date = None
            if end_timestamp != 0:
                end_date = datetime.fromtimestamp(end_timestamp / 1000).strftime("%Y-%m-%d")

            # Create stats object
            stats = {"total_message_count": len(messages), "messages_by_day": dict(sorted(messages_by_day.items())), "messages_by_sender": messages_by_sender, "date_range": {"start_date": start_date, "end_date": end_date}}

            return stats

        except Exception as e:
            error_message = f"Error analyzing message stats: {e}"
            logging.error(error_message)
            raise PreprocessingError(error_message) from e


# Consolidated WhatsApp preprocessor - replaces CommunityLangTalksDataPreprocessor and CommunityMcpDataPreprocessor
# Both previous classes were identical thin wrappers around DataPreprocessorWhatsappChatsBase
class WhatsAppPreprocessor(DataPreprocessorWhatsappChatsBase):
    """
    Unified WhatsApp message preprocessor for all community data sources.

    This replaces the previously separate CommunityLangTalksDataPreprocessor and
    CommunityMcpDataPreprocessor classes which were functionally identical.
    """

    def __init__(self, source_name: str, chat_name: str, **kwargs):
        try:
            super().__init__(source_name, chat_name, **kwargs)
        except PreprocessingError:
            raise  # Re-raise preprocessing errors as-is
        except Exception as e:
            error_message = f"Error initializing WhatsAppPreprocessor: {e}"
            logging.error(error_message)
            raise PreprocessingError(error_message) from e


# Backward compatibility aliases
CommunityLangTalksDataPreprocessor = WhatsAppPreprocessor
CommunityMcpDataPreprocessor = WhatsAppPreprocessor
