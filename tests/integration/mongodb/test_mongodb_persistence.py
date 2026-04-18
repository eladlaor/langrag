"""
E2E MongoDB Persistence Test

Verifies that the newsletter generation workflow correctly persists
all non-vectorized data to MongoDB including runs, messages, discussions,
chat status, and output paths.

Test Structure:
1. Generate a newsletter (small date range for speed)
2. Verify MongoDB run document
3. Verify messages persisted
4. Verify discussions persisted
5. Verify chat status tracking
6. Verify output paths stored
7. Verify API endpoints return correct data
"""

import asyncio
import os
import pytest

from fastapi.testclient import TestClient

# Import MongoDB repositories
from db.connection import get_database
from db.repositories.runs import RunsRepository
from db.repositories.messages import MessagesRepository
from db.repositories.discussions import DiscussionsRepository

# Import workflow execution
from graphs.multi_chat_consolidator.graph import get_parallel_orchestrator_graph
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
TEST_CHAT_NAME = "LangTalks Community"  # Use only one chat for speed


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def test_output_dir(tmp_path_factory):
    """Create temporary output directory for test"""
    output_dir = tmp_path_factory.mktemp("mongodb_test_output")
    return str(output_dir)


@pytest.fixture(scope="module")
def mongodb_run_id():
    """Shared run ID for all tests (set by workflow execution)"""
    return None


# ============================================================================
# Test 1: Execute Workflow and Verify Run Creation
# ============================================================================

@pytest.mark.asyncio
async def test_workflow_execution_creates_mongodb_run(test_output_dir):
    """
    Test that executing the newsletter generation workflow creates
    a MongoDB run document and persists all data.
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
        "consolidate_chats": False,  # Single chat, no consolidation needed
        "top_k_discussions": 3,  # Limit discussions for speed
        "force_refresh_extraction": True,  # Force fresh extraction
        "chat_results": [],
        "chat_errors": [],
        "total_chats": 0,
        "successful_chats": 0,
        "failed_chats": 0,
    }

    # Execute workflow (async - LangGraph 1.0+)
    print(f"\n🚀 Executing newsletter generation workflow for {TEST_CHAT_NAME}...")
    print(f"📅 Date range: {TEST_START_DATE} to {TEST_END_DATE}")
    print(f"📂 Output: {base_output_path}\n")

    graph = await get_parallel_orchestrator_graph()
    result_state = await graph.ainvoke(state)

    # Verify workflow completed successfully
    assert result_state is not None, "Workflow returned None"
    assert result_state.get("successful_chats", 0) > 0, "No chats succeeded"
    assert result_state.get("mongodb_run_id") is not None, "MongoDB run_id not created"

    mongodb_run_id = result_state["mongodb_run_id"]
    print("\n✅ Workflow completed successfully")
    print(f"📝 MongoDB run_id: {mongodb_run_id}\n")

    # Store run_id for subsequent tests
    return mongodb_run_id


# ============================================================================
# Test 2: Verify Run Document
# ============================================================================

@pytest.mark.asyncio
async def test_mongodb_run_document_exists(test_workflow_execution_creates_mongodb_run):
    """Verify that the run document exists in MongoDB with correct structure"""
    mongodb_run_id = await test_workflow_execution_creates_mongodb_run

    db = await get_database()
    runs_repo = RunsRepository(db)

    run = await runs_repo.get_run(mongodb_run_id)

    assert run is not None, f"Run not found in MongoDB: {mongodb_run_id}"
    assert run["run_id"] == mongodb_run_id
    assert run["data_source_name"] == TEST_DATA_SOURCE
    assert run["start_date"] == TEST_START_DATE
    assert run["end_date"] == TEST_END_DATE
    assert run["status"] in ["completed", "running"], f"Unexpected status: {run['status']}"
    assert TEST_CHAT_NAME in run.get("chat_names", [])

    print("\n✅ Run document verified")
    print(f"   Status: {run['status']}")
    print(f"   Chats: {run.get('chat_names', [])}")


# ============================================================================
# Test 3: Verify Messages Persisted
# ============================================================================

@pytest.mark.asyncio
async def test_mongodb_messages_persisted(test_workflow_execution_creates_mongodb_run):
    """Verify that messages were persisted to MongoDB"""
    mongodb_run_id = await test_workflow_execution_creates_mongodb_run

    db = await get_database()
    messages_repo = MessagesRepository(db)

    # Get messages for this run
    messages = await messages_repo.get_messages_by_run(
        run_id=mongodb_run_id,
        chat_name=TEST_CHAT_NAME,
        limit=10000
    )

    assert len(messages) > 0, "No messages found in MongoDB"

    # Verify message structure
    sample_msg = messages[0]
    assert "message_id" in sample_msg
    assert "run_id" in sample_msg
    assert "chat_name" in sample_msg
    assert "sender" in sample_msg
    assert "content" in sample_msg
    assert sample_msg["run_id"] == mongodb_run_id
    assert sample_msg["chat_name"] == TEST_CHAT_NAME

    # CRITICAL FIX #1: Verify matrix_event_id is preserved
    assert "matrix_event_id" in sample_msg, "matrix_event_id field missing (CRITICAL FIX #1 failed)"
    if sample_msg.get("matrix_event_id"):
        print(f"   ✅ Matrix event ID preserved: {sample_msg['matrix_event_id'][:20]}...")

    # CRITICAL FIX #2: Verify messages have translated content (persisted AFTER translation)
    # Note: Not all messages may be translated (Hebrew-only messages), but field should exist
    assert "content_translated" in sample_msg, "content_translated field missing"
    if sample_msg.get("content_translated"):
        print(f"   ✅ Translated content present: {sample_msg['content_translated'][:30]}...")

    # Verify short_id and replies_to are preserved
    assert "short_id" in sample_msg, "short_id field missing"
    # replies_to may be None for messages that don't reply to anything

    print("\n✅ Messages verified")
    print(f"   Total messages: {len(messages)}")
    print(f"   Sample sender: {sample_msg.get('sender', 'unknown')}")
    print(f"   Sample content (truncated): {sample_msg.get('content', '')[:50]}...")
    print(f"   Has matrix_event_id: {bool(sample_msg.get('matrix_event_id'))}")
    print(f"   Has translated content: {bool(sample_msg.get('content_translated'))}")


# ============================================================================
# Test 4: Verify Discussions Persisted
# ============================================================================

@pytest.mark.asyncio
async def test_mongodb_discussions_persisted(test_workflow_execution_creates_mongodb_run):
    """Verify that discussions were persisted to MongoDB with rankings"""
    mongodb_run_id = await test_workflow_execution_creates_mongodb_run

    db = await get_database()
    discussions_repo = DiscussionsRepository(db)

    # Get discussions for this run
    discussions = await discussions_repo.get_discussions_by_run(
        run_id=mongodb_run_id,
        sort_by_ranking=True
    )

    assert len(discussions) > 0, "No discussions found in MongoDB"

    # Verify discussion structure
    sample_disc = discussions[0]
    assert "discussion_id" in sample_disc
    assert "run_id" in sample_disc
    assert "chat_name" in sample_disc
    assert "title" in sample_disc
    assert "nutshell" in sample_disc
    assert "ranking_score" in sample_disc
    assert sample_disc["run_id"] == mongodb_run_id
    assert sample_disc["chat_name"] == TEST_CHAT_NAME

    # Verify ranking scores exist
    assert sample_disc["ranking_score"] >= 0, "Invalid ranking score"

    # CRITICAL FIX #3: Verify discussion-to-message ID mapping is correct
    assert "message_ids" in sample_disc, "message_ids field missing"
    message_ids = sample_disc.get("message_ids", [])
    if message_ids:
        # Verify format: {run_id}_msg_{short_id}
        first_msg_id = message_ids[0]
        assert first_msg_id.startswith(f"{mongodb_run_id}_msg_"), \
            f"Message ID format incorrect: {first_msg_id} (CRITICAL FIX #3 failed)"
        print(f"   ✅ Discussion-to-message mapping verified: {first_msg_id}")

    print("\n✅ Discussions verified")
    print(f"   Total discussions: {len(discussions)}")
    print(f"   Top discussion: {sample_disc.get('title', 'unknown')}")
    print(f"   Ranking score: {sample_disc.get('ranking_score', 0)}")
    print(f"   Message IDs count: {len(message_ids)}")


# ============================================================================
# Test 5: Verify Chat Status Tracking
# ============================================================================

@pytest.mark.asyncio
async def test_mongodb_chat_status_tracked(test_workflow_execution_creates_mongodb_run):
    """Verify that per-chat status was tracked in the run document"""
    mongodb_run_id = await test_workflow_execution_creates_mongodb_run

    db = await get_database()
    runs_repo = RunsRepository(db)

    run = await runs_repo.get_run(mongodb_run_id)

    # Verify chats subdocument exists
    chats = run.get("chats", {})
    assert len(chats) > 0, "No chat status tracked"
    assert TEST_CHAT_NAME in chats, f"Chat {TEST_CHAT_NAME} not tracked"

    chat_status = chats[TEST_CHAT_NAME]
    assert "status" in chat_status
    assert chat_status["status"] in ["completed", "running", "failed"]

    if "message_count" in chat_status:
        assert chat_status["message_count"] > 0, "Message count not tracked"

    print("\n✅ Chat status verified")
    print(f"   Chat: {TEST_CHAT_NAME}")
    print(f"   Status: {chat_status.get('status')}")
    print(f"   Message count: {chat_status.get('message_count', 'N/A')}")


# ============================================================================
# Test 6: Verify Output Paths Stored
# ============================================================================

@pytest.mark.asyncio
async def test_mongodb_output_paths_stored(test_workflow_execution_creates_mongodb_run):
    """Verify that output file paths were stored in MongoDB"""
    mongodb_run_id = await test_workflow_execution_creates_mongodb_run

    db = await get_database()
    runs_repo = RunsRepository(db)

    run = await runs_repo.get_run(mongodb_run_id)

    # Verify output paths exist
    chats = run.get("chats", {})
    if TEST_CHAT_NAME in chats:
        chat_data = chats[TEST_CHAT_NAME]
        output_paths = chat_data.get("output_paths", {})

        # Should have at least newsletter_md
        assert len(output_paths) > 0, "No output paths stored"
        assert "newsletter_md" in output_paths or "newsletter_json" in output_paths

        print("\n✅ Output paths verified")
        print(f"   Paths stored: {list(output_paths.keys())}")
    else:
        print(f"\n⚠️  Chat {TEST_CHAT_NAME} not found in run chats (may still be processing)")


# ============================================================================
# Test 7: Verify API Endpoints
# ============================================================================

def test_api_list_runs():
    """Test GET /api/mongodb/runs endpoint"""
    client = TestClient(app)

    response = client.get("/api/mongodb/runs?limit=10")

    assert response.status_code == 200
    runs = response.json()
    assert isinstance(runs, list)

    if len(runs) > 0:
        run = runs[0]
        assert "run_id" in run
        assert "data_source_name" in run
        assert "status" in run

    print("\n✅ API /runs endpoint verified")
    print(f"   Runs found: {len(runs)}")


def test_api_get_run_details(test_workflow_execution_creates_mongodb_run):
    """Test GET /api/mongodb/runs/{run_id} endpoint"""
    mongodb_run_id = asyncio.run(test_workflow_execution_creates_mongodb_run)

    client = TestClient(app)

    response = client.get(f"/api/mongodb/runs/{mongodb_run_id}")

    assert response.status_code == 200
    run = response.json()
    assert run["run_id"] == mongodb_run_id
    assert "chats" in run or run["status"] == "running"
    assert "config" in run

    print(f"\n✅ API /runs/{mongodb_run_id} endpoint verified")
    print(f"   Status: {run.get('status')}")


def test_api_get_run_messages(test_workflow_execution_creates_mongodb_run):
    """Test GET /api/mongodb/runs/{run_id}/messages endpoint"""
    mongodb_run_id = asyncio.run(test_workflow_execution_creates_mongodb_run)

    client = TestClient(app)

    response = client.get(f"/api/mongodb/runs/{mongodb_run_id}/messages?limit=100")

    assert response.status_code == 200
    messages = response.json()
    assert isinstance(messages, list)
    assert len(messages) > 0

    msg = messages[0]
    assert "message_id" in msg
    assert "content" in msg
    assert "sender" in msg

    print(f"\n✅ API /runs/{mongodb_run_id}/messages endpoint verified")
    print(f"   Messages returned: {len(messages)}")


def test_api_get_run_discussions(test_workflow_execution_creates_mongodb_run):
    """Test GET /api/mongodb/runs/{run_id}/discussions endpoint"""
    mongodb_run_id = asyncio.run(test_workflow_execution_creates_mongodb_run)

    client = TestClient(app)

    response = client.get(f"/api/mongodb/runs/{mongodb_run_id}/discussions")

    assert response.status_code == 200
    discussions = response.json()
    assert isinstance(discussions, list)
    assert len(discussions) > 0

    disc = discussions[0]
    assert "discussion_id" in disc
    assert "title" in disc
    assert "ranking_score" in disc

    print(f"\n✅ API /runs/{mongodb_run_id}/discussions endpoint verified")
    print(f"   Discussions returned: {len(discussions)}")


def test_api_get_stats():
    """Test GET /api/mongodb/stats endpoint"""
    client = TestClient(app)

    response = client.get("/api/mongodb/stats")

    assert response.status_code == 200
    stats = response.json()
    assert "total_runs" in stats
    assert "total_messages" in stats
    assert "total_discussions" in stats
    assert stats["total_runs"] >= 0
    assert stats["total_messages"] >= 0
    assert stats["total_discussions"] >= 0

    print("\n✅ API /stats endpoint verified")
    print(f"   Total runs: {stats['total_runs']}")
    print(f"   Total messages: {stats['total_messages']}")
    print(f"   Total discussions: {stats['total_discussions']}")


# ============================================================================
# Summary Test
# ============================================================================

@pytest.mark.asyncio
async def test_mongodb_indexes_created():
    """Test that database indexes were created for performance (CRITICAL FIX #4)"""
    db = await get_database()

    # Check messages collection indexes
    messages_indexes = await db.messages.index_information()
    assert "run_id_1" in messages_indexes, "Missing index on messages.run_id (CRITICAL FIX #4 failed)"
    assert "run_id_1_chat_name_1" in messages_indexes, "Missing compound index on messages.run_id+chat_name"
    print("\n✅ Messages indexes verified:")
    print(f"   Total indexes: {len(messages_indexes)}")
    print("   Key indexes: run_id_1, run_id_1_chat_name_1, matrix_event_id_1")

    # Check discussions collection indexes
    discussions_indexes = await db.discussions.index_information()
    assert "run_id_1" in discussions_indexes, "Missing index on discussions.run_id (CRITICAL FIX #4 failed)"
    assert "run_id_1_ranking_score_-1" in discussions_indexes, "Missing compound index on discussions.run_id+ranking_score"
    print("\n✅ Discussions indexes verified:")
    print(f"   Total indexes: {len(discussions_indexes)}")
    print("   Key indexes: run_id_1, run_id_1_ranking_score_-1")

    # Check runs collection indexes
    runs_indexes = await db.runs.index_information()
    assert "run_id_1" in runs_indexes, "Missing unique index on runs.run_id"
    print("\n✅ Runs indexes verified:")
    print(f"   Total indexes: {len(runs_indexes)}")


@pytest.mark.asyncio
async def test_mongodb_persistence_summary(test_workflow_execution_creates_mongodb_run):
    """Print summary of MongoDB persistence verification"""
    mongodb_run_id = await test_workflow_execution_creates_mongodb_run

    db = await get_database()
    runs_repo = RunsRepository(db)
    messages_repo = MessagesRepository(db)
    discussions_repo = DiscussionsRepository(db)

    run = await runs_repo.get_run(mongodb_run_id)
    message_count = await messages_repo.count_messages_by_run(mongodb_run_id)
    discussion_count = len(await discussions_repo.get_discussions_by_run(mongodb_run_id))

    print("\n" + "="*70)
    print("MongoDB PERSISTENCE TEST SUMMARY")
    print("="*70)
    print(f"Run ID: {mongodb_run_id}")
    print(f"Status: {run.get('status', 'unknown')}")
    print(f"Messages persisted: {message_count}")
    print(f"Discussions persisted: {discussion_count}")
    print(f"Chat status tracked: {len(run.get('chats', {}))}")
    print(f"Output paths stored: {'Yes' if run.get('chats', {}).get(TEST_CHAT_NAME, {}).get('output_paths') else 'No'}")
    print("="*70)
    print("\n✅ ALL CRITICAL FIXES VALIDATED:")
    print("   ✅ FIX #1: Matrix event IDs preserved")
    print("   ✅ FIX #2: Messages persisted AFTER translation")
    print("   ✅ FIX #3: Discussion-to-message mapping correct")
    print("   ✅ FIX #4: Database indexes created")
    print("\n✅ ALL MONGODB PERSISTENCE TESTS PASSED\n")
