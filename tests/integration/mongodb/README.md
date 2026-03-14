# MongoDB Persistence Integration Tests

This directory contains E2E integration tests for MongoDB persistence in the newsletter generation workflow.

## What's Tested

- ✅ Run document creation and tracking
- ✅ Message persistence from preprocessing stage
- ✅ Discussion persistence with rankings
- ✅ Per-chat status tracking
- ✅ Output path storage
- ✅ Stage progress tracking
- ✅ MongoDB API endpoints

## Prerequisites

1. **MongoDB running**:
   ```bash
   docker compose up -d mongodb
   ```

2. **Environment configured**:
   - Ensure `.env` or `.env.dev` has valid Beeper credentials
   - MongoDB connection: `MONGODB_URI=mongodb://mongodb:27017/?replicaSet=rs0`

3. **Python dependencies installed**:
   ```bash
   source .venv/bin/activate
   # Dependencies already in pyproject.toml
   ```

## Running Tests

### Run all MongoDB tests:
```bash
pytest tests/integration/mongodb/ -v
```

### Run with output:
```bash
pytest tests/integration/mongodb/test_mongodb_persistence.py -v -s
```

### Run specific test:
```bash
pytest tests/integration/mongodb/test_mongodb_persistence.py::test_workflow_execution_creates_mongodb_run -v -s
```

## Test Structure

### `test_mongodb_persistence.py`

**Test Flow**:
1. Execute newsletter generation workflow (2-day range for speed)
2. Verify MongoDB run document created
3. Verify messages persisted correctly
4. Verify discussions persisted with rankings
5. Verify chat status tracked in run document
6. Verify output file paths stored
7. Test API endpoints return correct data
8. Print summary statistics

**Test Configuration**:
- Date range: 2025-10-01 to 2025-10-02 (2 days for speed)
- Chat: "LangTalks Community"
- Top-K discussions: 3 (limited for speed)
- Force refresh: Enabled (ensures fresh data)

## Expected Output

```
🚀 Executing newsletter generation workflow for LangTalks Community...
📅 Date range: 2025-10-01 to 2025-10-02
📂 Output: /tmp/mongodb_test_output/langtalks_2025-10-01_to_2025-10-02

✅ Workflow completed successfully
📝 MongoDB run_id: langtalks_2025-10-01_to_2025-10-02_a1b2c3d4

✅ Run document verified
   Status: completed
   Chats: ['LangTalks Community']

✅ Messages verified
   Total messages: 145
   Sample sender: User A
   Sample content (truncated): This is a sample message...

✅ Discussions verified
   Total discussions: 8
   Top discussion: RAG for Books: Best Practices
   Ranking score: 9.0

✅ Chat status verified
   Chat: LangTalks Community
   Status: completed
   Message count: 145

✅ Output paths verified
   Paths stored: ['newsletter_md', 'newsletter_json', 'enriched_md']

✅ API /runs endpoint verified
   Runs found: 5

✅ API /runs/{run_id} endpoint verified
   Status: completed

✅ API /runs/{run_id}/messages endpoint verified
   Messages returned: 100

✅ API /runs/{run_id}/discussions endpoint verified
   Discussions returned: 8

✅ API /stats endpoint verified
   Total runs: 5
   Total messages: 645
   Total discussions: 35

======================================================================
MongoDB PERSISTENCE TEST SUMMARY
======================================================================
Run ID: langtalks_2025-10-01_to_2025-10-02_a1b2c3d4
Status: completed
Messages persisted: 145
Discussions persisted: 8
Chat status tracked: 1
Output paths stored: Yes
======================================================================

✅ ALL MONGODB PERSISTENCE TESTS PASSED
```

## Verification in MongoDB

After running tests, you can inspect MongoDB directly:

```bash
docker exec -it langrag-mongodb mongosh

use langrag

# View runs
db.runs.find().pretty()

# Count messages
db.messages.countDocuments()

# View discussions
db.discussions.find().pretty()

# Check specific run
db.runs.findOne({"run_id": "langtalks_2025-10-01_to_2025-10-02_a1b2c3d4"})
```

## Troubleshooting

### MongoDB connection fails
```bash
# Check MongoDB is running
docker compose ps mongodb

# Check logs
docker compose logs mongodb

# Restart if needed
docker compose restart mongodb
```

### Tests timeout
- Reduce date range in test configuration
- Reduce `top_k_discussions` limit
- Check network connectivity to Beeper

### No messages found
- Verify Beeper credentials in `.env`
- Check that chat has messages in the date range
- Try with a different date range

## Test Data Cleanup

Tests use temporary directories and don't pollute production data.
MongoDB data is persistent but separate from production runs.

To clean up test data:
```bash
docker exec -it langrag-mongodb mongosh

use langrag

# Remove test runs (careful!)
db.runs.deleteMany({"run_id": /^langtalks_2025-10-01/})
db.messages.deleteMany({"run_id": /^langtalks_2025-10-01/})
db.discussions.deleteMany({"run_id": /^langtalks_2025-10-01/})
```

## Integration with CI/CD

These tests can be integrated into CI/CD pipelines:

```yaml
# .github/workflows/test.yml
- name: Run MongoDB Integration Tests
  run: |
    docker compose up -d mongodb
    pytest tests/integration/mongodb/ -v
```

**Note**: Requires mock Beeper data or test credentials.
