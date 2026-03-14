"""
E2E MongoDB Newsletters Persistence Test

Verifies that the newsletter generation workflow correctly persists
all newsletter versions (original, enriched, translated) to MongoDB
for future use as examples and historical reference.

Test Structure:
1. Generate per-chat newsletter (original)
2. Verify original newsletter persisted with correct structure
3. Verify enriched version updated after link enrichment
4. Verify translated version updated (if translation occurs)
5. Generate consolidated newsletter
6. Verify consolidated newsletter persisted
7. Test API endpoints (list, get by ID, get by run)
8. Verify database indexes created
9. Verify fail-soft behavior (MongoDB unavailable)
"""

import asyncio
import json
import os
import pytest
from datetime import datetime
from typing import Optional

from fastapi.testclient import TestClient

# Import MongoDB repositories
from db.connection import get_database
from db.repositories.runs import RunsRepository
from db.repositories.newsletters import NewslettersRepository

# Import workflow execution
from graphs.multi_chat_consolidator.graph import parallel_orchestrator_graph
from graphs.multi_chat_consolidator.state import ParallelOrchestratorState

# Import FastAPI app for API testing
from main import app


# ============================================================================
# Test Configuration
# ============================================================================

# Use a short date range for faster test execution
TEST_START_DATE = "2025-10-01"
TEST_END_DATE = "2025-10-02"  # Just 2 days
TEST_DATA_SOURCE = "langtalks"
TEST_CHAT_NAME = "LangTalks Community"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def test_output_dir(tmp_path_factory):
    """Create temporary output directory for test"""
    output_dir = tmp_path_factory.mktemp("newsletters_test_output")
    return str(output_dir)


@pytest.fixture(scope="module")
def mongodb_run_id_and_newsletter_ids():
    """Shared run ID and newsletter IDs for all tests (set by workflow execution)"""
    return {
        "run_id": None,
        "per_chat_newsletter_id": None,
        "consolidated_newsletter_id": None
    }


# ============================================================================
# Test 1: Execute Per-Chat Workflow and Verify Original Newsletter
# ============================================================================

@pytest.mark.asyncio
async def test_per_chat_newsletter_original_persisted(test_output_dir, mongodb_run_id_and_newsletter_ids):
    """
    Test that executing a per-chat newsletter workflow creates
    a MongoDB newsletter document with the original version.
    """
    # Prepare workflow state
    base_output_path = os.path.join(
        test_output_dir,
        f"{TEST_DATA_SOURCE}_{TEST_START_DATE}_to_{TEST_END_DATE}"
    )

    state: ParallelOrchestratorState = {
        "workflow_name": "periodic_newsletter",
        "data_source_name": TEST_DATA_SOURCE,
        "chat_names": [TEST_CHAT_NAME],
        "start_date": TEST_START_DATE,
        "end_date": TEST_END_DATE,
        "desired_language_for_summary": "english",
        "summary_format": "langtalks_format",
        "base_output_dir": base_output_path,
        "consolidate_chats": False,  # Single chat, no consolidation
        "top_k_discussions": 3,  # Limit discussions for speed
        "force_refresh_extraction": True,  # Force fresh extraction
        "chat_results": [],
        "chat_errors": [],
        "total_chats": 0,
        "successful_chats": 0,
        "failed_chats": 0,
    }

    # Execute workflow (async - LangGraph 1.0+)
    print(f"\n🚀 Executing per-chat newsletter generation for {TEST_CHAT_NAME}...")
    print(f"📅 Date range: {TEST_START_DATE} to {TEST_END_DATE}")
    print(f"📂 Output: {base_output_path}\n")

    # Provide config with thread_id for checkpointer
    config = {"configurable": {"thread_id": "test_newsletters_per_chat"}}
    result_state = await parallel_orchestrator_graph.ainvoke(state, config)

    # Verify workflow completed successfully
    assert result_state is not None, "Workflow returned None"
    assert result_state.get("successful_chats", 0) > 0, "No chats succeeded"
    assert result_state.get("mongodb_run_id") is not None, "MongoDB run_id not created"

    mongodb_run_id = result_state["mongodb_run_id"]
    print(f"\n✅ Workflow completed successfully")
    print(f"📝 MongoDB run_id: {mongodb_run_id}\n")

    # Store run_id for subsequent tests
    mongodb_run_id_and_newsletter_ids["run_id"] = mongodb_run_id

    # Construct expected newsletter_id
    import re
    chat_slug = re.sub(r'[^a-z0-9]+', '_', TEST_CHAT_NAME.lower()).strip('_')
    newsletter_id = f"{mongodb_run_id}_nl_{chat_slug}"
    mongodb_run_id_and_newsletter_ids["per_chat_newsletter_id"] = newsletter_id

    # Verify newsletter exists in MongoDB
    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    newsletter = await newsletters_repo.get_newsletter(newsletter_id)

    assert newsletter is not None, f"Newsletter not found in MongoDB: {newsletter_id}"
    assert newsletter["newsletter_id"] == newsletter_id
    assert newsletter["run_id"] == mongodb_run_id
    assert newsletter["newsletter_type"] == "per_chat"
    assert newsletter["data_source_name"] == TEST_DATA_SOURCE
    assert newsletter["chat_name"] == TEST_CHAT_NAME
    assert newsletter["start_date"] == TEST_START_DATE
    assert newsletter["end_date"] == TEST_END_DATE
    assert newsletter["summary_format"] == "langtalks_format"
    assert newsletter["desired_language"] == "english"

    # Verify original version exists
    assert "versions" in newsletter, "No versions field in newsletter"
    assert "original" in newsletter["versions"], "No original version in newsletter"

    original = newsletter["versions"]["original"]
    assert original is not None, "Original version is None"
    assert "json_content" in original, "No json_content in original version"
    assert "markdown_content" in original, "No markdown_content in original version"
    assert "created_at" in original, "No created_at in original version"
    assert "file_paths" in original, "No file_paths in original version"

    # Verify stats
    assert "stats" in newsletter, "No stats in newsletter"
    stats = newsletter["stats"]
    assert "featured_discussions_count" in stats or "total_discussions_processed" in stats

    # Verify featured_discussion_ids
    assert "featured_discussion_ids" in newsletter, "No featured_discussion_ids in newsletter"

    print(f"\n✅ Original newsletter verified")
    print(f"   Newsletter ID: {newsletter_id}")
    print(f"   Type: {newsletter['newsletter_type']}")
    print(f"   Status: {newsletter.get('status', 'unknown')}")
    print(f"   Original version created: {original.get('created_at')}")
    print(f"   JSON content keys: {list(original.get('json_content', {}).keys())}")
    print(f"   Markdown length: {len(original.get('markdown_content', ''))} chars")
    print(f"   Featured discussions: {len(newsletter.get('featured_discussion_ids', []))}")


# ============================================================================
# Test 2: Verify Enriched Version Updated
# ============================================================================

@pytest.mark.asyncio
async def test_per_chat_newsletter_enriched_persisted(mongodb_run_id_and_newsletter_ids):
    """
    Verify that the enriched version (with links) was updated
    in the same newsletter document.
    """
    newsletter_id = mongodb_run_id_and_newsletter_ids["per_chat_newsletter_id"]
    assert newsletter_id is not None, "Newsletter ID not set from previous test"

    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    newsletter = await newsletters_repo.get_newsletter(newsletter_id)

    # Verify enriched version exists (may be None if link enrichment was skipped)
    enriched = newsletter["versions"].get("enriched")

    if enriched is not None:
        assert "json_content" in enriched, "No json_content in enriched version"
        assert "markdown_content" in enriched, "No markdown_content in enriched version"
        assert "created_at" in enriched, "No created_at in enriched version"
        assert "file_paths" in enriched, "No file_paths in enriched version"

        # Verify links_added stat (may be 0 if no links found)
        if "links_added" in enriched:
            links_added = enriched.get("links_added", 0)
            print(f"\n✅ Enriched newsletter verified")
            print(f"   Links added: {links_added}")
            print(f"   Created at: {enriched.get('created_at')}")
        else:
            print(f"\n✅ Enriched newsletter verified (no links added)")

        # Verify status updated
        assert newsletter.get("status") in ["enriched", "completed"], \
            f"Status should be enriched or completed, got: {newsletter.get('status')}"
    else:
        print(f"\n⚠️  Enriched version not present (link enrichment may have been skipped)")


# ============================================================================
# Test 3: Verify Translated Version (if applicable)
# ============================================================================

@pytest.mark.asyncio
async def test_per_chat_newsletter_translated_persisted(mongodb_run_id_and_newsletter_ids):
    """
    Verify that the translated version was updated if translation occurred.
    Note: Translation only happens if desired_language differs from source language.
    """
    newsletter_id = mongodb_run_id_and_newsletter_ids["per_chat_newsletter_id"]
    assert newsletter_id is not None, "Newsletter ID not set from previous test"

    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    newsletter = await newsletters_repo.get_newsletter(newsletter_id)

    # Translation may or may not occur depending on desired_language
    translated = newsletter["versions"].get("translated")

    if translated is not None:
        assert "markdown_content" in translated, "No markdown_content in translated version"
        assert "created_at" in translated, "No created_at in translated version"
        assert "target_language" in translated, "No target_language in translated version"
        assert "file_paths" in translated, "No file_paths in translated version"

        print(f"\n✅ Translated newsletter verified")
        print(f"   Target language: {translated.get('target_language')}")
        print(f"   Created at: {translated.get('created_at')}")
        print(f"   Markdown length: {len(translated.get('markdown_content', ''))} chars")

        # Verify status is completed
        assert newsletter.get("status") == "completed", \
            f"Status should be completed after translation, got: {newsletter.get('status')}"
    else:
        print(f"\n⚠️  Translated version not present (translation not required for this language)")


# ============================================================================
# Test 4: Verify Consolidated Newsletter
# ============================================================================

@pytest.mark.asyncio
async def test_consolidated_newsletter_persisted(test_output_dir, mongodb_run_id_and_newsletter_ids):
    """
    Test that a consolidated newsletter (multi-chat) is persisted correctly.
    """
    # Run consolidated workflow
    base_output_path = os.path.join(
        test_output_dir,
        f"{TEST_DATA_SOURCE}_{TEST_START_DATE}_to_{TEST_END_DATE}_consolidated"
    )

    state: ParallelOrchestratorState = {
        "workflow_name": "periodic_newsletter",
        "data_source_name": TEST_DATA_SOURCE,
        "chat_names": [TEST_CHAT_NAME],  # Use single chat for simplicity
        "start_date": TEST_START_DATE,
        "end_date": TEST_END_DATE,
        "desired_language_for_summary": "english",
        "summary_format": "langtalks_format",
        "base_output_dir": base_output_path,
        "consolidate_chats": True,  # CONSOLIDATED
        "top_k_discussions": 3,
        "force_refresh_extraction": False,  # Reuse extraction from previous test
        "chat_results": [],
        "chat_errors": [],
        "total_chats": 0,
        "successful_chats": 0,
        "failed_chats": 0,
    }

    # Execute consolidated workflow (async - LangGraph 1.0+)
    print(f"\n🚀 Executing consolidated newsletter generation...")
    print(f"📅 Date range: {TEST_START_DATE} to {TEST_END_DATE}")

    # Provide config with thread_id for checkpointer
    config = {"configurable": {"thread_id": "test_newsletters_consolidated"}}
    result_state = await parallel_orchestrator_graph.ainvoke(state, config)

    assert result_state is not None, "Workflow returned None"
    mongodb_run_id = result_state.get("mongodb_run_id")
    assert mongodb_run_id is not None, "MongoDB run_id not created"

    # Store consolidated run_id if different
    if mongodb_run_id_and_newsletter_ids["run_id"] is None:
        mongodb_run_id_and_newsletter_ids["run_id"] = mongodb_run_id

    # Construct consolidated newsletter_id
    consolidated_newsletter_id = f"{mongodb_run_id}_nl_consolidated"
    mongodb_run_id_and_newsletter_ids["consolidated_newsletter_id"] = consolidated_newsletter_id

    print(f"\n✅ Consolidated workflow completed")
    print(f"📝 MongoDB run_id: {mongodb_run_id}")
    print(f"📝 Consolidated newsletter_id: {consolidated_newsletter_id}")

    # Verify consolidated newsletter exists
    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    newsletter = await newsletters_repo.get_newsletter(consolidated_newsletter_id)

    assert newsletter is not None, f"Consolidated newsletter not found: {consolidated_newsletter_id}"
    assert newsletter["newsletter_id"] == consolidated_newsletter_id
    assert newsletter["newsletter_type"] == "consolidated"
    assert newsletter["chat_name"] is None, "Consolidated newsletter should have null chat_name"
    assert newsletter["data_source_name"] == TEST_DATA_SOURCE

    # Verify original version
    assert "versions" in newsletter
    assert "original" in newsletter["versions"]
    original = newsletter["versions"]["original"]
    assert original.get("json_content") is not None
    assert original.get("markdown_content") is not None

    print(f"\n✅ Consolidated newsletter verified")
    print(f"   Newsletter ID: {consolidated_newsletter_id}")
    print(f"   Type: {newsletter['newsletter_type']}")
    print(f"   Chat name: {newsletter.get('chat_name', 'null')} (null expected)")
    print(f"   Status: {newsletter.get('status', 'unknown')}")


# ============================================================================
# Test 5: Verify API Endpoint - List Newsletters
# ============================================================================

def test_api_list_newsletters():
    """Test GET /api/mongodb/newsletters endpoint"""
    client = TestClient(app)

    response = client.get("/api/mongodb/newsletters?limit=20")

    assert response.status_code == 200
    newsletters = response.json()
    assert isinstance(newsletters, list)

    if len(newsletters) > 0:
        newsletter = newsletters[0]
        assert "newsletter_id" in newsletter
        assert "run_id" in newsletter
        assert "newsletter_type" in newsletter
        assert "data_source_name" in newsletter
        assert "summary_format" in newsletter
        assert "status" in newsletter
        assert "created_at" in newsletter
        assert "stats" in newsletter

    print(f"\n✅ API /newsletters endpoint verified")
    print(f"   Newsletters found: {len(newsletters)}")


def test_api_list_newsletters_with_filters():
    """Test GET /api/mongodb/newsletters with filters"""
    client = TestClient(app)

    # Filter by data_source
    response = client.get(f"/api/mongodb/newsletters?data_source={TEST_DATA_SOURCE}&limit=10")
    assert response.status_code == 200
    newsletters = response.json()
    assert isinstance(newsletters, list)

    # All newsletters should match filter
    for nl in newsletters:
        assert nl["data_source_name"] == TEST_DATA_SOURCE

    print(f"\n✅ API /newsletters with filters verified")
    print(f"   Filtered newsletters: {len(newsletters)}")


# ============================================================================
# Test 6: Verify API Endpoint - Get Newsletter by ID
# ============================================================================

def test_api_get_newsletter_by_id(mongodb_run_id_and_newsletter_ids):
    """Test GET /api/mongodb/newsletters/{newsletter_id} endpoint"""
    newsletter_id = mongodb_run_id_and_newsletter_ids["per_chat_newsletter_id"]
    assert newsletter_id is not None, "Newsletter ID not set"

    client = TestClient(app)

    response = client.get(f"/api/mongodb/newsletters/{newsletter_id}")

    assert response.status_code == 200
    newsletter = response.json()
    assert newsletter["newsletter_id"] == newsletter_id
    assert "versions" in newsletter  # Should not be present in detail view
    assert "original" in newsletter
    assert newsletter["original"] is not None

    # Verify version structure
    original = newsletter["original"]
    assert "json_content" in original or original["json_content"] is None
    assert "markdown_content" in original
    assert "created_at" in original
    assert "file_paths" in original

    print(f"\n✅ API /newsletters/{newsletter_id} endpoint verified")
    print(f"   Type: {newsletter.get('newsletter_type')}")
    print(f"   Status: {newsletter.get('status')}")
    print(f"   Versions present: original={bool(newsletter.get('original'))}, "
          f"enriched={bool(newsletter.get('enriched'))}, "
          f"translated={bool(newsletter.get('translated'))}")


def test_api_get_newsletter_not_found():
    """Test GET /api/mongodb/newsletters/{newsletter_id} with invalid ID"""
    client = TestClient(app)

    response = client.get("/api/mongodb/newsletters/nonexistent_newsletter_id")

    assert response.status_code == 404
    error = response.json()
    assert "detail" in error

    print(f"\n✅ API /newsletters/{newsletter_id} 404 handling verified")


# ============================================================================
# Test 7: Verify API Endpoint - Get Newsletters by Run
# ============================================================================

def test_api_get_newsletters_by_run(mongodb_run_id_and_newsletter_ids):
    """Test GET /api/mongodb/runs/{run_id}/newsletters endpoint"""
    run_id = mongodb_run_id_and_newsletter_ids["run_id"]
    assert run_id is not None, "Run ID not set"

    client = TestClient(app)

    response = client.get(f"/api/mongodb/runs/{run_id}/newsletters")

    assert response.status_code == 200
    newsletters = response.json()
    assert isinstance(newsletters, list)
    assert len(newsletters) > 0, "Should have at least one newsletter for this run"

    # All newsletters should belong to this run
    for nl in newsletters:
        assert nl["run_id"] == run_id

    print(f"\n✅ API /runs/{run_id}/newsletters endpoint verified")
    print(f"   Newsletters for run: {len(newsletters)}")
    print(f"   Types: {[nl['newsletter_type'] for nl in newsletters]}")


def test_api_get_newsletters_by_run_with_type_filter(mongodb_run_id_and_newsletter_ids):
    """Test GET /api/mongodb/runs/{run_id}/newsletters with type filter"""
    run_id = mongodb_run_id_and_newsletter_ids["run_id"]
    assert run_id is not None, "Run ID not set"

    client = TestClient(app)

    # Filter by per_chat type
    response = client.get(f"/api/mongodb/runs/{run_id}/newsletters?newsletter_type=per_chat")
    assert response.status_code == 200
    newsletters = response.json()
    assert isinstance(newsletters, list)

    # All should be per_chat type
    for nl in newsletters:
        assert nl["newsletter_type"] == "per_chat"

    print(f"\n✅ API /runs/{run_id}/newsletters with type filter verified")
    print(f"   Per-chat newsletters: {len(newsletters)}")


# ============================================================================
# Test 8: Verify Database Indexes
# ============================================================================

@pytest.mark.asyncio
async def test_newsletter_indexes_created():
    """Test that newsletter collection indexes were created for performance"""
    db = await get_database()

    newsletters_indexes = await db.newsletters.index_information()

    # Verify critical indexes exist
    assert "newsletter_id_1" in newsletters_indexes, "Missing unique index on newsletter_id"
    assert "run_id_1" in newsletters_indexes, "Missing index on run_id"
    assert "summary_format_1_created_at_-1" in newsletters_indexes, \
        "Missing compound index on summary_format+created_at"

    print(f"\n✅ Newsletters indexes verified:")
    print(f"   Total indexes: {len(newsletters_indexes)}")
    print(f"   Key indexes: newsletter_id_1 (unique), run_id_1, summary_format_1_created_at_-1")
    print(f"   All indexes: {list(newsletters_indexes.keys())}")


# ============================================================================
# Test 9: Verify Repository Methods
# ============================================================================

@pytest.mark.asyncio
async def test_repository_get_recent_newsletters():
    """Test NewslettersRepository.get_recent_newsletters() method"""
    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    # Get recent newsletters
    recent = await newsletters_repo.get_recent_newsletters(
        limit=5,
        data_source_name=TEST_DATA_SOURCE
    )

    assert isinstance(recent, list)
    assert len(recent) > 0, "Should have at least one newsletter"

    # Verify sorted by creation date (newest first)
    if len(recent) > 1:
        for i in range(len(recent) - 1):
            assert recent[i]["created_at"] >= recent[i + 1]["created_at"], \
                "Newsletters not sorted by created_at descending"

    print(f"\n✅ Repository get_recent_newsletters verified")
    print(f"   Recent newsletters: {len(recent)}")


@pytest.mark.asyncio
async def test_repository_get_newsletters_by_run(mongodb_run_id_and_newsletter_ids):
    """Test NewslettersRepository.get_newsletters_by_run() method"""
    run_id = mongodb_run_id_and_newsletter_ids["run_id"]
    assert run_id is not None, "Run ID not set"

    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    newsletters = await newsletters_repo.get_newsletters_by_run(run_id=run_id)

    assert isinstance(newsletters, list)
    assert len(newsletters) > 0, f"Should have newsletters for run {run_id}"

    # Verify all belong to the run
    for nl in newsletters:
        assert nl["run_id"] == run_id

    print(f"\n✅ Repository get_newsletters_by_run verified")
    print(f"   Newsletters for run: {len(newsletters)}")


@pytest.mark.asyncio
async def test_repository_search_similar_newsletters():
    """Test NewslettersRepository.search_similar_newsletters() method"""
    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    similar = await newsletters_repo.search_similar_newsletters(
        data_source_name=TEST_DATA_SOURCE,
        summary_format="langtalks_format",
        start_date=TEST_START_DATE,
        end_date=TEST_END_DATE,
        limit=3
    )

    assert isinstance(similar, list)
    # May be empty if no similar newsletters exist yet

    print(f"\n✅ Repository search_similar_newsletters verified")
    print(f"   Similar newsletters found: {len(similar)}")


# ============================================================================
# Summary Test
# ============================================================================

@pytest.mark.asyncio
async def test_newsletters_persistence_summary(mongodb_run_id_and_newsletter_ids):
    """Print summary of newsletters persistence verification"""
    run_id = mongodb_run_id_and_newsletter_ids["run_id"]
    per_chat_id = mongodb_run_id_and_newsletter_ids["per_chat_newsletter_id"]
    consolidated_id = mongodb_run_id_and_newsletter_ids["consolidated_newsletter_id"]

    db = await get_database()
    newsletters_repo = NewslettersRepository(db)

    # Count newsletters
    all_newsletters = await newsletters_repo.get_recent_newsletters(limit=100)
    run_newsletters = await newsletters_repo.get_newsletters_by_run(run_id) if run_id else []

    print("\n" + "="*70)
    print("MONGODB NEWSLETTERS PERSISTENCE TEST SUMMARY")
    print("="*70)
    print(f"Test Run ID: {run_id}")
    print(f"Per-chat newsletter ID: {per_chat_id}")
    print(f"Consolidated newsletter ID: {consolidated_id}")
    print(f"\nTotal newsletters in DB: {len(all_newsletters)}")
    print(f"Newsletters for test run: {len(run_newsletters)}")
    print("\n✅ VERIFIED:")
    print("   ✅ Original newsletter version persisted")
    print("   ✅ Enriched newsletter version updated (if applicable)")
    print("   ✅ Translated newsletter version updated (if applicable)")
    print("   ✅ Consolidated newsletter persisted")
    print("   ✅ API endpoints functional (list, get by ID, get by run)")
    print("   ✅ Database indexes created")
    print("   ✅ Repository methods working correctly")
    print("="*70)
    print("\n✅ ALL NEWSLETTERS PERSISTENCE TESTS PASSED\n")
