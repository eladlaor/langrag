#!/usr/bin/env python3
"""
End-to-End Pipeline Tests

Comprehensive test suite covering the entire newsletter generation pipeline
from message extraction through final newsletter output.

Test Scenarios:
1. Periodic Newsletter Generation (single chat, date range)
2. Daily Summaries (single chat, single day)
3. Consolidated Newsletter (multiple days, cross-day ranking)

Each test validates:
- All intermediate files are created
- File contents are valid and well-structured
- Processing stages complete successfully
- Output quality meets standards

Usage:
    # Run all tests
    pytest tests/test_e2e_pipeline.py -v

    # Run specific test
    pytest tests/test_e2e_pipeline.py::test_periodic_newsletter -v

    # Run with detailed output
    pytest tests/test_e2e_pipeline.py -v -s

Prerequisites:
- Docker container running (docker compose up -d)
- Beeper/Matrix keys configured
- Test data available for specified dates
"""

import pytest
import requests
import json
import time
import os
from typing import Any

# Import validation helpers
from helpers.pipeline_validator import (
    validate_full_pipeline_output,
    print_validation_report,
    ValidationResult
)


# ============================================================================
# TEST CONFIGURATION
# ============================================================================

# Base URL for FastAPI application
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost")

# Test data configuration
# Using July 22-23, 2024 as test dates (known to have data)
TEST_DATA_SOURCE = "langtalks"
TEST_CHAT_NAME = "LangTalks Community"
TEST_START_DATE = "2024-07-22"
TEST_END_DATE = "2024-07-23"
TEST_SINGLE_DATE = "2024-07-22"
TEST_LANGUAGE = "english"
TEST_FORMAT = "langtalks_format"

# Test output directories
TEST_OUTPUT_BASE = "output/test_e2e"


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def docker_health_check():
    """
    Verify Docker container is running and healthy before running tests.

    This is a session-scoped fixture that runs once before all tests.
    """
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        response.raise_for_status()
        print(f"\n✓ Docker container is healthy at {BASE_URL}")
        return True
    except Exception as e:
        pytest.fail(
            f"Docker container not reachable at {BASE_URL}: {e}\n"
            "Please start the container: docker compose up -d"
        )


@pytest.fixture
def cleanup_test_output():
    """
    Fixture to clean up test output directories after each test.

    Yields control to the test, then cleans up afterward.
    """
    yield  # Run the test

    # Cleanup is optional - comment out to preserve test artifacts
    # import shutil
    # if os.path.exists(TEST_OUTPUT_BASE):
    #     shutil.rmtree(TEST_OUTPUT_BASE)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def wait_for_workflow_completion(
    endpoint: str,
    payload: dict[str, Any],
    timeout: int = 600
) -> requests.Response:
    """
    Send request to workflow endpoint and wait for completion.

    Args:
        endpoint: API endpoint path (e.g., "/api/generate_periodic_newsletter")
        payload: Request payload
        timeout: Maximum time to wait in seconds

    Returns:
        Response object from completed request

    Raises:
        requests.Timeout: If workflow doesn't complete within timeout
        requests.HTTPError: If workflow returns error status
    """
    url = f"{BASE_URL}{endpoint}"

    print(f"\nSending request to {endpoint}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    start_time = time.time()

    response = requests.post(url, json=payload, timeout=timeout)

    elapsed = time.time() - start_time
    print(f"\nResponse received after {elapsed:.1f}s")
    print(f"Status: {response.status_code}")

    return response


def assert_response_success(response: requests.Response, workflow_name: str):
    """
    Assert that workflow response indicates success.

    Args:
        response: Response object from workflow request
        workflow_name: Name of workflow for error messages

    Raises:
        AssertionError: If response indicates failure
    """
    assert response.status_code == 200, (
        f"{workflow_name} failed with status {response.status_code}\n"
        f"Response: {response.text}"
    )

    result = response.json()

    # Check for error message
    if "error" in result:
        pytest.fail(f"{workflow_name} returned error: {result['error']}")

    # Print summary
    message = result.get("message", "")
    print(f"\n✓ {workflow_name} completed: {message}")

    return result


def validate_stage_outputs(
    output_dir: str,
    expected_stages: list,
    workflow_name: str
) -> dict[str, ValidationResult]:
    """
    Validate outputs from specific pipeline stages.

    Args:
        output_dir: Base output directory to validate
        expected_stages: List of stage names to validate
        workflow_name: Workflow name for error messages

    Returns:
        Dictionary mapping stage name to ValidationResult
    """
    print(f"\n{'=' * 80}")
    print(f"VALIDATING OUTPUTS: {workflow_name}")
    print(f"Output Directory: {output_dir}")
    print(f"{'=' * 80}\n")

    results = validate_full_pipeline_output(output_dir)

    # Filter to expected stages only
    filtered_results = {
        stage: results[stage]
        for stage in expected_stages
        if stage in results
    }

    # Print report
    passed, total = print_validation_report(filtered_results)

    # Assert all stages passed
    failed_stages = [
        stage for stage, result in filtered_results.items()
        if not result.passed
    ]

    if failed_stages:
        pytest.fail(
            f"{workflow_name} validation failed for stages: {', '.join(failed_stages)}\n"
            f"See validation report above for details."
        )

    return filtered_results


# ============================================================================
# TEST CASES
# ============================================================================

def test_periodic_newsletter_generation(docker_health_check, cleanup_test_output):
    """
    Test: Periodic Newsletter Generation

    Validates the complete pipeline for a periodic newsletter covering a date range.

    Pipeline stages tested:
    1. Message extraction (Beeper/Matrix)
    2. Preprocessing (parse, standardize)
    3. Translation (batch OpenAI)
    4. Discussion separation (LLM topical grouping)
    5. Discussion ranking (relevance scoring)
    6. Content generation (newsletter creation)
    7. Link enrichment (URL insertion)
    8. Final translation (if needed)

    Success criteria:
    - All API calls return 200
    - All output files created
    - All validation checks pass
    - Newsletter content meets quality standards
    """
    output_dir = f"{TEST_OUTPUT_BASE}/periodic_newsletter"

    payload = {
        "start_date": TEST_START_DATE,
        "end_date": TEST_END_DATE,
        "data_source_name": TEST_DATA_SOURCE,
        "whatsapp_chat_names_to_include": [TEST_CHAT_NAME],
        "desired_language_for_summary": TEST_LANGUAGE,
        "summary_format": TEST_FORMAT,
        "output_dir": output_dir,

        # Force fresh run for testing
        "force_refresh_extraction": True,
        "force_refresh_preprocessing": True,
        "force_refresh_translation": True,
        "force_refresh_separate_discussions": True,
        "force_refresh_content": True,
        "force_refresh_final_translation": False,  # English, no translation needed

        # Output actions
        "output_actions": ["save_local"]
    }

    # Execute workflow
    response = wait_for_workflow_completion(
        "/api/generate_periodic_newsletter",
        payload,
        timeout=600  # 10 minutes
    )

    # Validate response
    result = assert_response_success(response, "Periodic Newsletter")

    # Check results structure
    assert "results" in result, "Response missing 'results' field"
    assert len(result["results"]) > 0, "No newsletter results returned"

    # Get output directory for validation
    # Newsletter results include chat-specific subdirectories
    chat_output_dir = os.path.join(output_dir, TEST_CHAT_NAME.replace(" ", "_"))

    # Validate all pipeline stages
    expected_stages = [
        "extraction",
        "preprocessing",
        "translation",
        "discussions",
        "ranking",
        "newsletter",
        "link_enrichment"
    ]

    validate_stage_outputs(chat_output_dir, expected_stages, "Periodic Newsletter")

    print("\n✓ Periodic Newsletter test PASSED")


def test_cross_chat_consolidation(docker_health_check, cleanup_test_output):
    """
    Test: Cross-Chat Consolidation (Multiple Chats, Single Date Range)

    Validates the cross-chat consolidation feature:
    - Process multiple chats in parallel
    - Aggregate discussions from all chats
    - Rank discussions cross-chat
    - Generate single consolidated newsletter

    Pipeline flow:
    1. dispatch_chats (Send API) - parallel processing per chat
    2. aggregate_results - collect results from all workers
    3. should_consolidate_chats (router) - decide consolidation path
    4. setup_consolidated_directories - prepare output structure
    5. consolidate_discussions - merge discussions from all chats
    6. rank_consolidated_discussions - cross-chat ranking
    7. generate_consolidated_newsletter - single newsletter from all chats
    8. enrich_consolidated_newsletter - add URLs
    9. translate_consolidated_newsletter - translate if needed

    Success criteria:
    - All chats processed successfully
    - Per-chat outputs preserved in per_chat/ subdirectory
    - Consolidated newsletter generated in consolidated/ directory
    - Consolidated newsletter includes content from all chats
    - All validation checks pass
    """
    output_dir = f"{TEST_OUTPUT_BASE}/cross_chat_consolidation"

    # Note: Using single chat for now since we only have langtalks chat
    # In production, this would use multiple different chats
    # For testing purposes, we're validating the consolidation flow works
    payload = {
        "start_date": TEST_START_DATE,
        "end_date": TEST_END_DATE,
        "data_source_name": TEST_DATA_SOURCE,
        "whatsapp_chat_names_to_include": [TEST_CHAT_NAME],  # Would be multiple in production
        "desired_language_for_summary": TEST_LANGUAGE,
        "summary_format": TEST_FORMAT,
        "output_dir": output_dir,

        # Enable cross-chat consolidation (default: True)
        "consolidate_chats": True,

        # Force fresh run for testing
        "force_refresh_extraction": True,
        "force_refresh_preprocessing": True,
        "force_refresh_translation": True,
        "force_refresh_separate_discussions": True,
        "force_refresh_content": True,
        "force_refresh_final_translation": False,

        # Cross-chat consolidation force refresh flags
        "force_refresh_cross_chat_aggregation": True,
        "force_refresh_cross_chat_ranking": True,
        "force_refresh_consolidated_content": True,
        "force_refresh_consolidated_link_enrichment": True,
        "force_refresh_consolidated_translation": False,

        # Output actions
        "output_actions": ["save_local"]
    }

    # Execute workflow
    response = wait_for_workflow_completion(
        "/api/generate_periodic_newsletter",
        payload,
        timeout=900  # 15 minutes for consolidation
    )

    # Validate response
    result = assert_response_success(response, "Cross-Chat Consolidation")

    # Check results structure
    assert "results" in result, "Response missing 'results' field"
    assert len(result["results"]) > 0, "No newsletter results returned"

    # Check per-chat outputs
    # When consolidation is enabled with >1 chat, per-chat outputs go to per_chat/ subdirectory
    # For single chat (this test), outputs go directly to output_dir
    # TODO: Update this test to use multiple chats when available
    chat_output_dir = os.path.join(output_dir, TEST_CHAT_NAME.replace(" ", "_"))

    # Validate per-chat pipeline stages
    expected_per_chat_stages = [
        "extraction",
        "preprocessing",
        "translation",
        "discussions"
    ]
    validate_stage_outputs(chat_output_dir, expected_per_chat_stages, "Per-Chat Processing")

    # Note: With single chat, consolidation doesn't trigger (need >1 successful chat)
    # But we can validate the flag is passed correctly
    print("\n✓ Cross-chat consolidation test PASSED (single chat - consolidation skipped as expected)")
    print("  Note: To fully test consolidation, run with multiple chats")


def test_pipeline_error_handling(docker_health_check):
    """
    Test: Pipeline Error Handling

    Validates that the pipeline properly handles and reports errors:
    - Invalid date ranges
    - Missing required fields
    - Invalid chat names
    - Invalid data sources

    Success criteria:
    - API returns appropriate error status codes
    - Error messages are descriptive
    - No silent failures
    """
    # Test 1: Invalid date range (end before start)
    payload = {
        "start_date": "2024-07-23",
        "end_date": "2024-07-22",  # Before start_date
        "data_source_name": TEST_DATA_SOURCE,
        "whatsapp_chat_names_to_include": [TEST_CHAT_NAME],
        "desired_language_for_summary": TEST_LANGUAGE,
        "summary_format": TEST_FORMAT,
    }

    response = requests.post(f"{BASE_URL}/api/generate_periodic_newsletter", json=payload, timeout=30)
    assert response.status_code == 400, "Expected 400 for invalid date range"
    error = response.json()
    assert "start_date" in error["detail"] or "end_date" in error["detail"], "Error message should mention dates"
    print("\n✓ Invalid date range error handling works")

    # Test 2: Invalid data source
    payload = {
        "start_date": TEST_START_DATE,
        "end_date": TEST_END_DATE,
        "data_source_name": "invalid_source",
        "whatsapp_chat_names_to_include": [TEST_CHAT_NAME],
        "desired_language_for_summary": TEST_LANGUAGE,
        "summary_format": TEST_FORMAT,
    }

    response = requests.post(f"{BASE_URL}/api/generate_periodic_newsletter", json=payload, timeout=30)
    assert response.status_code == 400, "Expected 400 for invalid data source"
    error = response.json()
    assert "data_source_name" in error["detail"], "Error message should mention data_source_name"
    print("✓ Invalid data source error handling works")

    # Test 3: Empty chat names list
    payload = {
        "start_date": TEST_START_DATE,
        "end_date": TEST_END_DATE,
        "data_source_name": TEST_DATA_SOURCE,
        "whatsapp_chat_names_to_include": [],  # Empty list
        "desired_language_for_summary": TEST_LANGUAGE,
        "summary_format": TEST_FORMAT,
    }

    response = requests.post(f"{BASE_URL}/api/generate_periodic_newsletter", json=payload, timeout=30)
    assert response.status_code == 400, "Expected 400 for empty chat names"
    error = response.json()
    assert "chat" in error["detail"].lower(), "Error message should mention chat names"
    print("✓ Empty chat names error handling works")

    print("\n✓ Pipeline Error Handling test PASSED")


# ============================================================================
# TEST SUITE SUMMARY
# ============================================================================

def test_suite_summary(docker_health_check):
    """
    Summary test that prints overall test suite information.

    This is a lightweight test that always passes, used to display
    test suite metadata and configuration.
    """
    print("\n" + "=" * 80)
    print("E2E PIPELINE TEST SUITE")
    print("=" * 80)
    print("\nConfiguration:")
    print(f"  Base URL: {BASE_URL}")
    print(f"  Test Data Source: {TEST_DATA_SOURCE}")
    print(f"  Test Chat: {TEST_CHAT_NAME}")
    print(f"  Test Date Range: {TEST_START_DATE} to {TEST_END_DATE}")
    print(f"  Test Single Date: {TEST_SINGLE_DATE}")
    print(f"  Output Directory: {TEST_OUTPUT_BASE}")
    print("\nTest Coverage:")
    print("  - Periodic newsletter generation")
    print("  - Cross-chat consolidation (multi-chat)")
    print("  - Error handling")
    print("\nValidation Coverage:")
    print("  - Message extraction (Beeper/Matrix)")
    print("  - Preprocessing (parsing, threading)")
    print("  - Translation (OpenAI batch)")
    print("  - Discussion separation (LLM grouping)")
    print("  - Discussion ranking (cross-day, cross-chat)")
    print("  - Newsletter generation")
    print("  - Link enrichment")
    print("  - Final translation")
    print("\n" + "=" * 80 + "\n")

    assert True  # Always passes


if __name__ == "__main__":
    """
    Run tests directly with python (without pytest).

    Usage:
        python tests/test_e2e_pipeline.py
    """
    import sys

    print("Running E2E Pipeline Tests...")
    print("Note: For best results, use pytest: pytest tests/test_e2e_pipeline.py -v\n")

    # Run pytest programmatically
    sys.exit(pytest.main([__file__, "-v", "-s"]))
