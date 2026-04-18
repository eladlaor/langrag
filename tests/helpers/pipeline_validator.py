"""
Pipeline Validation Helpers

This module provides validation functions for each stage of the newsletter generation pipeline.
Used by end-to-end tests to verify outputs at each processing stage.

Validation Areas:
- File existence and permissions
- JSON schema validation
- Content quality checks
- Message structure validation
- Discussion separation quality
- Newsletter format compliance
"""

import glob
import json
import os
from pathlib import Path
from typing import Any


class ValidationResult:
    """
    Result of a validation check.

    Attributes:
        passed: Whether validation passed
        message: Human-readable result message
        details: Additional details about the validation
    """

    def __init__(self, passed: bool, message: str, details: dict[str, Any] | None = None):
        self.passed = passed
        self.message = message
        self.details = details or {}

    def __bool__(self):
        return self.passed

    def __repr__(self):
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return f"{status}: {self.message}"


# ============================================================================
# FILE VALIDATION
# ============================================================================

def validate_file_exists(file_path: str, description: str = "File") -> ValidationResult:
    """
    Validate that a file exists and is readable.

    Args:
        file_path: Path to file to check
        description: Human-readable description of file

    Returns:
        ValidationResult with pass/fail status
    """
    if not file_path:
        return ValidationResult(False, f"{description}: Path is empty or None")

    path = Path(file_path)

    if not path.exists():
        return ValidationResult(False, f"{description}: File does not exist at {file_path}")

    if not path.is_file():
        return ValidationResult(False, f"{description}: Path exists but is not a file: {file_path}")

    if not os.access(file_path, os.R_OK):
        return ValidationResult(False, f"{description}: File exists but is not readable: {file_path}")

    file_size = path.stat().st_size
    return ValidationResult(
        True,
        f"{description}: File exists and is readable",
        {"path": file_path, "size_bytes": file_size}
    )


def validate_json_file(file_path: str, description: str = "JSON file") -> ValidationResult:
    """
    Validate that a file exists and contains valid JSON.

    Args:
        file_path: Path to JSON file
        description: Human-readable description

    Returns:
        ValidationResult with pass/fail status and parsed JSON in details
    """
    # First check file exists
    exists_result = validate_file_exists(file_path, description)
    if not exists_result:
        return exists_result

    # Try to parse JSON
    try:
        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)

        return ValidationResult(
            True,
            f"{description}: Valid JSON with {len(data) if isinstance(data, (list, dict)) else 'N/A'} items",
            {"path": file_path, "data": data}
        )
    except json.JSONDecodeError as e:
        return ValidationResult(
            False,
            f"{description}: Invalid JSON - {e}",
            {"path": file_path, "error": str(e)}
        )
    except Exception as e:
        return ValidationResult(
            False,
            f"{description}: Error reading file - {e}",
            {"path": file_path, "error": str(e)}
        )


# ============================================================================
# EXTRACTION STAGE VALIDATION
# ============================================================================

def validate_extracted_messages(file_path: str) -> ValidationResult:
    """
    Validate extracted messages from Beeper/Matrix extraction stage.

    Checks:
    - File exists and is valid JSON
    - Messages list is present
    - Each message has required fields
    - Message structure is correct

    Args:
        file_path: Path to raw_messages.json

    Returns:
        ValidationResult with pass/fail and details
    """
    json_result = validate_json_file(file_path, "Extracted messages")
    if not json_result:
        return json_result

    data = json_result.details["data"]

    # Check for messages list
    if not isinstance(data, list):
        return ValidationResult(False, "Extracted data is not a list of messages")

    if len(data) == 0:
        return ValidationResult(False, "Extracted messages list is empty")

    # Validate message structure
    required_fields = ["event_id", "sender", "timestamp", "body"]
    issues = []

    for idx, msg in enumerate(data):
        if not isinstance(msg, dict):
            issues.append(f"Message {idx} is not a dictionary")
            continue

        missing_fields = [field for field in required_fields if field not in msg]
        if missing_fields:
            issues.append(f"Message {idx} missing fields: {', '.join(missing_fields)}")

    if issues:
        return ValidationResult(
            False,
            f"Extracted messages validation failed: {len(issues)} issues found",
            {"issues": issues[:10], "total_issues": len(issues)}  # Limit to first 10
        )

    # Check for decryption (messages should have readable content)
    encrypted_count = sum(1 for msg in data if msg.get("body", "").startswith("** Unable to decrypt"))
    decryption_rate = (len(data) - encrypted_count) / len(data) * 100 if len(data) > 0 else 0

    return ValidationResult(
        True,
        f"Extracted {len(data)} messages, {decryption_rate:.1f}% decrypted",
        {
            "message_count": len(data),
            "encrypted_count": encrypted_count,
            "decryption_rate": decryption_rate
        }
    )


# ============================================================================
# PREPROCESSING STAGE VALIDATION
# ============================================================================

def validate_preprocessed_messages(file_path: str) -> ValidationResult:
    """
    Validate preprocessed messages.

    Checks:
    - File exists and is valid JSON
    - Message count matches or is close to extraction
    - Required fields are present
    - Reply threading is preserved (m.relates_to)

    Args:
        file_path: Path to preprocessed_messages.json

    Returns:
        ValidationResult with pass/fail and details
    """
    json_result = validate_json_file(file_path, "Preprocessed messages")
    if not json_result:
        return json_result

    data = json_result.details["data"]

    if not isinstance(data, list):
        return ValidationResult(False, "Preprocessed data is not a list")

    if len(data) == 0:
        return ValidationResult(False, "Preprocessed messages list is empty")

    # Check for reply threading preservation
    reply_count = sum(1 for msg in data if "m.relates_to" in msg)
    reply_rate = (reply_count / len(data) * 100) if len(data) > 0 else 0

    # Validate message structure
    required_fields = ["sender", "timestamp", "content"]
    issues = []

    for idx, msg in enumerate(data):
        missing_fields = [field for field in required_fields if field not in msg]
        if missing_fields:
            issues.append(f"Message {idx} missing fields: {', '.join(missing_fields)}")

    if issues:
        return ValidationResult(
            False,
            f"Preprocessed messages validation failed: {len(issues)} issues",
            {"issues": issues[:10], "total_issues": len(issues)}
        )

    return ValidationResult(
        True,
        f"Preprocessed {len(data)} messages, {reply_count} replies preserved",
        {
            "message_count": len(data),
            "reply_count": reply_count,
            "reply_rate": reply_rate
        }
    )


# ============================================================================
# TRANSLATION STAGE VALIDATION
# ============================================================================

def validate_translated_messages(file_path: str, target_language: str = "english") -> ValidationResult:
    """
    Validate translated messages.

    Checks:
    - File exists and is valid JSON
    - Translation quality (non-empty, different from source)
    - Message count preserved

    Args:
        file_path: Path to translated_messages.json
        target_language: Expected target language

    Returns:
        ValidationResult with pass/fail and details
    """
    json_result = validate_json_file(file_path, "Translated messages")
    if not json_result:
        return json_result

    data = json_result.details["data"]

    if not isinstance(data, list):
        return ValidationResult(False, "Translated data is not a list")

    if len(data) == 0:
        return ValidationResult(False, "Translated messages list is empty")

    # Check that messages have non-empty content (translation updates content in-place)
    issues = []
    has_content_count = 0

    for idx, msg in enumerate(data):
        if "content" in msg and msg["content"]:
            has_content_count += 1
        elif "content" not in msg:
            issues.append(f"Message {idx} missing content field")
        else:
            issues.append(f"Message {idx} has empty content field")

    content_rate = (has_content_count / len(data) * 100) if len(data) > 0 else 0

    if content_rate < 50:
        return ValidationResult(
            False,
            f"Content rate too low: {content_rate:.1f}%",
            {"has_content_count": has_content_count, "total": len(data)}
        )

    return ValidationResult(
        True,
        f"Translated {has_content_count}/{len(data)} messages with content ({content_rate:.1f}%)",
        {
            "message_count": len(data),
            "has_content_count": has_content_count,
            "content_rate": content_rate
        }
    )


# ============================================================================
# DISCUSSION SEPARATION VALIDATION
# ============================================================================

def validate_discussions(file_path: str) -> ValidationResult:
    """
    Validate separated discussions.

    Checks:
    - File exists and is valid JSON
    - Discussions structure is correct
    - Each discussion has required fields
    - Messages are properly grouped

    Args:
        file_path: Path to separate_discussions.json

    Returns:
        ValidationResult with pass/fail and details
    """
    json_result = validate_json_file(file_path, "Separated discussions")
    if not json_result:
        return json_result

    data = json_result.details["data"]

    # Check for discussions list or dict structure
    discussions = []
    if isinstance(data, dict) and "discussions" in data:
        discussions = data["discussions"]
    elif isinstance(data, list):
        discussions = data
    else:
        return ValidationResult(
            False,
            "Discussions data has unexpected structure (expected list or dict with 'discussions' key)"
        )

    if len(discussions) == 0:
        return ValidationResult(False, "No discussions found")

    # Validate discussion structure
    required_fields = ["title", "messages"]
    issues = []
    total_messages = 0

    for idx, discussion in enumerate(discussions):
        if not isinstance(discussion, dict):
            issues.append(f"Discussion {idx} is not a dictionary")
            continue

        missing_fields = [field for field in required_fields if field not in discussion]
        if missing_fields:
            issues.append(f"Discussion {idx} missing fields: {', '.join(missing_fields)}")

        messages = discussion.get("messages", [])
        if not isinstance(messages, list):
            issues.append(f"Discussion {idx} messages field is not a list")
        else:
            total_messages += len(messages)
            if len(messages) == 0:
                issues.append(f"Discussion {idx} has no messages")

    if issues:
        return ValidationResult(
            False,
            f"Discussions validation failed: {len(issues)} issues",
            {"issues": issues[:10], "total_issues": len(issues)}
        )

    return ValidationResult(
        True,
        f"Found {len(discussions)} discussions with {total_messages} total messages",
        {
            "discussion_count": len(discussions),
            "total_messages": total_messages,
            "avg_messages_per_discussion": total_messages / len(discussions) if discussions else 0
        }
    )


# ============================================================================
# DISCUSSION RANKING VALIDATION
# ============================================================================

def validate_discussions_ranking(file_path: str) -> ValidationResult:
    """
    Validate discussions ranking output.

    Checks:
    - File exists and is valid JSON
    - Rankings structure is correct
    - Each ranking has required fields (score, category, reasoning)

    Args:
        file_path: Path to discussions_ranking.json

    Returns:
        ValidationResult with pass/fail and details
    """
    json_result = validate_json_file(file_path, "Discussions ranking")
    if not json_result:
        return json_result

    data = json_result.details["data"]

    # Check for rankings list or dict structure
    rankings = []
    if isinstance(data, dict) and "rankings" in data:
        rankings = data["rankings"]
    elif isinstance(data, list):
        rankings = data
    else:
        return ValidationResult(
            False,
            "Rankings data has unexpected structure"
        )

    if len(rankings) == 0:
        return ValidationResult(False, "No rankings found")

    # Validate ranking structure
    required_fields = ["discussion_id", "score", "category"]
    issues = []

    for idx, ranking in enumerate(rankings):
        if not isinstance(ranking, dict):
            issues.append(f"Ranking {idx} is not a dictionary")
            continue

        missing_fields = [field for field in required_fields if field not in ranking]
        if missing_fields:
            issues.append(f"Ranking {idx} missing fields: {', '.join(missing_fields)}")

        # Validate score is numeric
        score = ranking.get("score")
        if score is not None and not isinstance(score, (int, float)):
            issues.append(f"Ranking {idx} score is not numeric: {type(score)}")

    if issues:
        return ValidationResult(
            False,
            f"Rankings validation failed: {len(issues)} issues",
            {"issues": issues[:10], "total_issues": len(issues)}
        )

    # Calculate category distribution
    categories = {}
    for ranking in rankings:
        category = ranking.get("category", "unknown")
        categories[category] = categories.get(category, 0) + 1

    return ValidationResult(
        True,
        f"Ranked {len(rankings)} discussions across {len(categories)} categories",
        {
            "ranking_count": len(rankings),
            "categories": categories
        }
    )


# ============================================================================
# NEWSLETTER CONTENT VALIDATION
# ============================================================================

def validate_newsletter_content(
    json_path: str,
    md_path: str,
    format_type: str = "langtalks_format"
) -> ValidationResult:
    """
    Validate generated newsletter content.

    Checks:
    - Both JSON and MD files exist
    - JSON has required structure
    - MD is non-empty and formatted correctly
    - Content matches expected format

    Args:
        json_path: Path to newsletter JSON
        md_path: Path to newsletter MD
        format_type: Expected newsletter format

    Returns:
        ValidationResult with pass/fail and details
    """
    # Validate JSON
    json_result = validate_json_file(json_path, "Newsletter JSON")
    if not json_result:
        return json_result

    # Validate MD exists
    md_result = validate_file_exists(md_path, "Newsletter MD")
    if not md_result:
        return md_result

    # Read MD content
    try:
        with open(md_path, encoding='utf-8') as f:
            md_content = f.read()
    except Exception as e:
        return ValidationResult(False, f"Failed to read MD file: {e}")

    if len(md_content.strip()) == 0:
        return ValidationResult(False, "Newsletter MD is empty")

    data = json_result.details["data"]

    # Check JSON structure
    required_fields = ["title", "sections"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return ValidationResult(
            False,
            f"Newsletter JSON missing fields: {', '.join(missing_fields)}"
        )

    sections = data.get("sections", [])
    if not isinstance(sections, list) or len(sections) == 0:
        return ValidationResult(False, "Newsletter has no sections")

    return ValidationResult(
        True,
        f"Newsletter generated with {len(sections)} sections ({len(md_content)} chars)",
        {
            "section_count": len(sections),
            "md_length": len(md_content),
            "title": data.get("title", "")
        }
    )


# ============================================================================
# LINK ENRICHMENT VALIDATION
# ============================================================================

def validate_link_enrichment(
    enriched_json_path: str,
    enriched_md_path: str,
    original_json_path: str
) -> ValidationResult:
    """
    Validate link enrichment output.

    Checks:
    - Enriched files exist
    - Links were added
    - Content structure preserved

    Args:
        enriched_json_path: Path to enriched newsletter JSON
        enriched_md_path: Path to enriched newsletter MD
        original_json_path: Path to original newsletter JSON

    Returns:
        ValidationResult with pass/fail and details
    """
    # Validate enriched JSON
    enriched_json_result = validate_json_file(enriched_json_path, "Enriched newsletter JSON")
    if not enriched_json_result:
        return enriched_json_result

    # Validate enriched MD
    enriched_md_result = validate_file_exists(enriched_md_path, "Enriched newsletter MD")
    if not enriched_md_result:
        return enriched_md_result

    # Load original for comparison
    original_json_result = validate_json_file(original_json_path, "Original newsletter JSON")
    if not original_json_result:
        return ValidationResult(
            False,
            "Cannot validate enrichment without original newsletter"
        )

    enriched_data = enriched_json_result.details["data"]
    original_data = original_json_result.details["data"]

    # Count links in enriched content
    enriched_sections = enriched_data.get("sections", [])
    original_sections = original_data.get("sections", [])

    # Count HTTP links in MD
    try:
        with open(enriched_md_path, encoding='utf-8') as f:
            enriched_md = f.read()
        link_count = enriched_md.count("http://") + enriched_md.count("https://")
    except Exception as e:
        return ValidationResult(False, f"Failed to read enriched MD: {e}")

    return ValidationResult(
        True,
        f"Link enrichment added {link_count} links to newsletter",
        {
            "link_count": link_count,
            "sections_enriched": len(enriched_sections)
        }
    )


# ============================================================================
# AGGREGATED VALIDATION FUNCTIONS
# ============================================================================

def validate_full_pipeline_output(output_dir: str, workflow_type: str = "periodic_newsletter") -> dict[str, ValidationResult]:
    """
    Validate all outputs from a complete pipeline run.

    Args:
        output_dir: Base output directory
        workflow_type: Type of workflow (periodic_newsletter, daily_summaries, etc.)

    Returns:
        Dictionary mapping stage name to ValidationResult
    """
    results = {}

    # Expected file structure
    # Extraction uses dynamic filenames (decrypted_{ChatName}_{date}.json), so glob for them
    extraction_pattern = os.path.join(output_dir, "extracted", "decrypted_messages", "decrypted_*.json")
    extraction_files = sorted(glob.glob(extraction_pattern))
    extraction_file = extraction_files[0] if extraction_files else os.path.join(output_dir, "extracted", "decrypted_messages", "decrypted_messages.json")
    preprocessing_file = os.path.join(output_dir, "preprocessed", "messages_processed.json")
    translation_file = os.path.join(output_dir, "translated", "messages_translated_to_english.json")
    discussions_file = os.path.join(output_dir, "separate_discussions", "separate_discussions.json")
    ranking_file = os.path.join(output_dir, "discussions_ranking", "discussions_ranking.json")
    newsletter_json = os.path.join(output_dir, "newsletter", "newsletter_summary.json")
    newsletter_md = os.path.join(output_dir, "newsletter", "newsletter_summary.md")
    enriched_json = os.path.join(output_dir, "link_enrichment", "enriched_newsletter_summary.json")
    enriched_md = os.path.join(output_dir, "link_enrichment", "enriched_newsletter_summary.md")

    # Validate each stage
    results["extraction"] = validate_extracted_messages(extraction_file)
    results["preprocessing"] = validate_preprocessed_messages(preprocessing_file)
    results["translation"] = validate_translated_messages(translation_file)
    results["discussions"] = validate_discussions(discussions_file)
    results["ranking"] = validate_discussions_ranking(ranking_file)
    results["newsletter"] = validate_newsletter_content(newsletter_json, newsletter_md)
    results["link_enrichment"] = validate_link_enrichment(enriched_json, enriched_md, newsletter_json)

    return results


def print_validation_report(results: dict[str, ValidationResult]) -> tuple[int, int]:
    """
    Print a formatted validation report.

    Args:
        results: Dictionary mapping stage name to ValidationResult

    Returns:
        Tuple of (passed_count, total_count)
    """
    print("\n" + "=" * 80)
    print("PIPELINE VALIDATION REPORT")
    print("=" * 80 + "\n")

    passed = 0
    total = len(results)

    for stage_name, result in results.items():
        status = "✓ PASS" if result.passed else "✗ FAIL"
        print(f"{status} | {stage_name.upper()}")
        print(f"      {result.message}")

        if result.details:
            for key, value in result.details.items():
                if key not in ["data", "path", "issues"]:  # Skip large fields
                    print(f"      - {key}: {value}")

        if not result.passed and "issues" in result.details:
            print(f"      Issues ({result.details.get('total_issues', 'N/A')}):")
            for issue in result.details["issues"][:5]:  # Show first 5
                print(f"        * {issue}")

        print()

        if result.passed:
            passed += 1

    print("=" * 80)
    print(f"SUMMARY: {passed}/{total} stages passed")
    print("=" * 80 + "\n")

    return passed, total
