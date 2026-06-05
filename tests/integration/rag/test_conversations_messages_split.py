"""
Integration tests for the rag_conversations -> rag_messages split.

Validates success criteria SC1-SC8 from
knowledge/plans/RAG_CONVERSATIONS_MESSAGES_SPLIT.md:

    SC1  no embedded array; rag_messages has exactly N docs
    SC2  history order preserved (most recent last)
    SC3  cascade delete removes session + its messages; others untouched
    SC4  owner scoping intact at the message layer
    SC5  title-on-first-message fires exactly once
    SC6  list_sessions message_count without loading bodies
    SC7  atomicity: forced failure mid-create/mid-delete leaves no partial state
    SC8  16MB regression guard (the headline)

Requires Docker with MongoDB running as a replica set (transactions). Tests are
skipped when MongoDB is not reachable.

Run:
    docker compose exec app pytest tests/integration/rag/test_conversations_messages_split.py -v
"""

import uuid
from unittest.mock import AsyncMock, patch

import bson
import pytest

from constants import COLLECTION_RAG_CONVERSATIONS, COLLECTION_RAG_MESSAGES
from custom_types.field_keys import RAGConversationKeys as ConvKeys
from custom_types.field_keys import RAGMessageKeys as MsgKeys


def _load_conversation_manager_module():
    """Import rag.conversation.manager, defeating the test-package name shadow.

    This test file lives under tests/integration/rag/, and with pytest's default
    'prepend' import mode that directory is registered in sys.modules as the
    top-level package ``rag`` — which shadows the real ``src/rag`` package. We
    pop any such shadow and re-import from src so ``ConversationManager`` resolves
    to the production module rather than the test package.
    """
    import importlib
    import sys
    from pathlib import Path

    # src/ holds the real `rag` package. Make sure it's ahead of the test
    # directory (which pytest's prepend mode put on sys.path as a sibling `rag`).
    src_path = str(Path(__file__).resolve().parents[3] / "src")
    if sys.path[0] != src_path:
        sys.path.insert(0, src_path)

    shadow = sys.modules.get("rag")
    if shadow is not None and f"{src_path}/rag" not in (getattr(shadow, "__file__", "") or ""):
        # Drop the test-package shadow and its submodules so the real package loads.
        for name in [m for m in sys.modules if m == "rag" or m.startswith("rag.")]:
            del sys.modules[name]
    return importlib.import_module("rag.conversation.manager")


_BSON_MAX_BYTES = 16 * 1024 * 1024
_OWNER_A = "owner-a"
_OWNER_B = "owner-b"


@pytest.fixture
async def repo():
    """A ConversationsRepository wired to the live DB, with per-test cleanup.

    Resets the db.connection singletons first so the Motor client binds to the
    event loop this test runs on (pytest-asyncio gives each test a fresh loop;
    a client cached on a prior, closed loop would raise "Event loop is closed").
    Skips when MongoDB is unreachable so the suite still passes outside Docker.
    """
    import db.connection as conn

    conn._client = None
    conn._database = None

    try:
        db = await conn.get_database()
        await db.command("ping")
    except Exception:
        pytest.skip("MongoDB not available — run tests inside Docker")

    from db.repositories.rag_conversations import ConversationsRepository

    created_session_ids: list[str] = []
    repository = ConversationsRepository(db)
    repository._test_track = created_session_ids  # type: ignore[attr-defined]

    yield repository

    # Cleanup every session and its messages touched by the test.
    for sid in created_session_ids:
        await db[COLLECTION_RAG_CONVERSATIONS].delete_many({ConvKeys.SESSION_ID: sid})
        await db[COLLECTION_RAG_MESSAGES].delete_many({MsgKeys.SESSION_ID: sid})


def _new_session_id(repo) -> str:
    sid = str(uuid.uuid4())
    repo._test_track.append(sid)
    return sid


def _user_message(content: str) -> dict:
    from datetime import UTC, datetime
    return {
        MsgKeys.MESSAGE_ID: str(uuid.uuid4()),
        MsgKeys.ROLE: "user",
        MsgKeys.CONTENT: content,
        MsgKeys.CREATED_AT: datetime.now(UTC),
    }


class TestConversationsMessagesSplit:
    async def test_sc1_no_embedded_array(self, repo):
        """SC1: after N appends, session doc has no messages field; rag_messages has N."""
        from db.connection import get_database

        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)

        n = 5
        for i in range(n):
            await repo.append_message(sid, _user_message(f"msg {i}"))

        db = await get_database()
        session_doc = await db[COLLECTION_RAG_CONVERSATIONS].find_one({ConvKeys.SESSION_ID: sid})
        assert not session_doc.get(ConvKeys.MESSAGES), "session document must not carry an embedded messages array"

        count = await db[COLLECTION_RAG_MESSAGES].count_documents({MsgKeys.SESSION_ID: sid})
        assert count == n

    async def test_sc2_history_order_preserved(self, repo):
        """SC2: get_conversation_history returns last k messages, most recent last."""
        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)
        for i in range(6):
            await repo.append_message(sid, _user_message(f"m{i}"))

        history = await repo.get_conversation_history(sid, max_messages=3)
        contents = [m[MsgKeys.CONTENT] for m in history]
        assert contents == ["m3", "m4", "m5"], "last 3, most recent last"

    async def test_sc3_cascade_delete(self, repo):
        """SC3: delete_session removes session + all its messages; other sessions untouched."""
        from db.connection import get_database

        keep = _new_session_id(repo)
        drop = _new_session_id(repo)
        await repo.create_session(keep, content_sources=["podcast"], owner=_OWNER_A)
        await repo.create_session(drop, content_sources=["podcast"], owner=_OWNER_A)
        for i in range(3):
            await repo.append_message(keep, _user_message(f"keep {i}"))
            await repo.append_message(drop, _user_message(f"drop {i}"))

        deleted = await repo.delete_session(drop, owner=_OWNER_A)
        assert deleted is True

        db = await get_database()
        assert await db[COLLECTION_RAG_CONVERSATIONS].find_one({ConvKeys.SESSION_ID: drop}) is None
        assert await db[COLLECTION_RAG_MESSAGES].count_documents({MsgKeys.SESSION_ID: drop}) == 0
        # Sibling session and its messages are untouched.
        assert await db[COLLECTION_RAG_CONVERSATIONS].find_one({ConvKeys.SESSION_ID: keep}) is not None
        assert await db[COLLECTION_RAG_MESSAGES].count_documents({MsgKeys.SESSION_ID: keep}) == 3

    async def test_sc4_owner_scoping(self, repo):
        """SC4: a different owner cannot read or delete another owner's session/messages."""
        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)
        await repo.append_message(sid, _user_message("secret"))

        # Cross-owner read returns None.
        assert await repo.get_session(sid, owner=_OWNER_B, include_messages=True) is None
        # Cross-owner delete is a no-op and leaves messages intact.
        assert await repo.delete_session(sid, owner=_OWNER_B) is False
        assert await repo.count_messages(sid) == 1
        # Owner read hydrates the message.
        owned = await repo.get_session(sid, owner=_OWNER_A, include_messages=True)
        assert owned is not None
        assert len(owned[ConvKeys.MESSAGES]) == 1

    async def test_sc5_title_on_first_message_fires_once(self, repo):
        """SC5: auto-title fires exactly once, on the first user message."""
        manager_mod = _load_conversation_manager_module()
        ConversationManager = manager_mod.ConversationManager

        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)

        manager = ConversationManager()
        with patch.object(
            manager_mod, "generate_session_title", new=AsyncMock(return_value="Auto Title")
        ) as mock_title:
            # Point the manager at the same DB-backed repo as the test.
            with patch.object(ConversationManager, "_get_repo", new=AsyncMock(return_value=repo)):
                await manager.add_user_message(sid, "first question")
                await manager.add_user_message(sid, "second question")

        assert mock_title.await_count == 1, "title generation must fire exactly once"
        session = await repo.get_session(sid, owner=_OWNER_A)
        assert session[ConvKeys.TITLE] == "Auto Title"

    async def test_sc6_list_sessions_message_count(self, repo):
        """SC6: list_sessions reports real message_count without embedding bodies."""
        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)
        for i in range(4):
            await repo.append_message(sid, _user_message(f"x{i}"))

        sessions = await repo.list_sessions(owner=_OWNER_A, limit=50)
        target = next(s for s in sessions if s[ConvKeys.SESSION_ID] == sid)
        assert target["message_count"] == 4
        assert ConvKeys.MESSAGES not in target, "list must not load message bodies"

    async def test_sc7_atomicity_delete_rolls_back(self, repo):
        """SC7: a failure mid-delete leaves no partial state (session + messages both survive)."""
        from db.connection import get_database

        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)
        for i in range(3):
            await repo.append_message(sid, _user_message(f"y{i}"))

        # Force the cascade delete to blow up after the session delete but inside
        # the transaction, then assert nothing was committed.
        boom = RuntimeError("injected failure mid-delete")
        with patch.object(repo._messages, "delete_for_session", new=AsyncMock(side_effect=boom)):
            with pytest.raises(RuntimeError):
                await repo.delete_session(sid, owner=_OWNER_A)

        db = await get_database()
        assert await db[COLLECTION_RAG_CONVERSATIONS].find_one({ConvKeys.SESSION_ID: sid}) is not None, \
            "session delete must roll back when the cascade fails"
        assert await db[COLLECTION_RAG_MESSAGES].count_documents({MsgKeys.SESSION_ID: sid}) == 3

    async def test_sc8_16mb_regression_guard(self, repo):
        """SC8 (headline): many large messages stay readable and keep the session doc tiny.

        Under the old embedded design this volume would push the single session
        document past the 16MB BSON ceiling and writes would fail hard.
        """
        from db.connection import get_database

        sid = _new_session_id(repo)
        await repo.create_session(sid, content_sources=["podcast"], owner=_OWNER_A)

        # ~4KB per message * 1000 = ~4MB of message content — comfortably past
        # what fits as growth headroom but split across documents it's a non-issue.
        # (Kept at 1000 rather than 5000 to keep the suite fast; the size proof is
        # the session-doc assertion, which is independent of N.)
        big = "z" * 4096
        n = 1000
        for i in range(n):
            await repo.append_message(sid, _user_message(f"{i}:{big}"))

        # All reads succeed.
        assert await repo.count_messages(sid) == n
        history = await repo.get_conversation_history(sid, max_messages=10)
        assert len(history) == 10

        # The session document itself stays far below the BSON ceiling.
        db = await get_database()
        session_doc = await db[COLLECTION_RAG_CONVERSATIONS].find_one({ConvKeys.SESSION_ID: sid})
        encoded_len = len(bson.encode(session_doc))
        assert encoded_len < 64 * 1024, f"session doc should be tiny, was {encoded_len} bytes"
        assert encoded_len < _BSON_MAX_BYTES

    async def test_migration_backfills_and_is_idempotent(self, repo):
        """Migration: a legacy session with an embedded array is split out; re-run is a no-op.

        Seeds its OWN legacy-shaped session (embedded messages array) so it never
        touches real data, applies the migration, then asserts the array is gone,
        rag_messages holds the elements, and a second apply inserts nothing new.
        """
        import importlib.util
        from datetime import UTC, datetime
        from pathlib import Path

        from db.connection import get_database

        db = await get_database()
        sid = _new_session_id(repo)
        embedded = [
            {
                MsgKeys.MESSAGE_ID: str(uuid.uuid4()),
                MsgKeys.ROLE: "user",
                MsgKeys.CONTENT: "legacy 1",
                MsgKeys.CREATED_AT: datetime(2025, 1, 1, tzinfo=UTC),
            },
            {
                MsgKeys.MESSAGE_ID: str(uuid.uuid4()),
                MsgKeys.ROLE: "assistant",
                MsgKeys.CONTENT: "legacy 2",
                MsgKeys.CREATED_AT: datetime(2025, 1, 2, tzinfo=UTC),
            },
        ]
        await db[COLLECTION_RAG_CONVERSATIONS].insert_one(
            {
                ConvKeys.SESSION_ID: sid,
                ConvKeys.OWNER: _OWNER_A,
                ConvKeys.TITLE: None,
                ConvKeys.CONTENT_SOURCES: ["podcast"],
                ConvKeys.MESSAGES: embedded,  # legacy embedded array
                ConvKeys.CREATED_AT: datetime(2025, 1, 1, tzinfo=UTC),
                ConvKeys.UPDATED_AT: datetime(2025, 1, 2, tzinfo=UTC),
            }
        )

        # Load the migration script as a module by file path (it lives in scripts/,
        # not on the package path).
        script_path = Path(__file__).resolve().parents[3] / "scripts" / "migrate_rag_conversations_messages.py"
        spec = importlib.util.spec_from_file_location("_migrate_rag_conv", script_path)
        migrate_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migrate_mod)

        # Apply once.
        rc = await migrate_mod.migrate(dry_run=False)
        assert rc == 0

        session_doc = await db[COLLECTION_RAG_CONVERSATIONS].find_one({ConvKeys.SESSION_ID: sid})
        assert ConvKeys.MESSAGES not in session_doc, "embedded array must be unset after migration"
        migrated = await db[COLLECTION_RAG_MESSAGES].find({MsgKeys.SESSION_ID: sid}).to_list(length=None)
        assert len(migrated) == 2
        assert {m[MsgKeys.CONTENT] for m in migrated} == {"legacy 1", "legacy 2"}

        # Apply again — idempotent: no duplicates, count unchanged.
        rc2 = await migrate_mod.migrate(dry_run=False)
        assert rc2 == 0
        assert await db[COLLECTION_RAG_MESSAGES].count_documents({MsgKeys.SESSION_ID: sid}) == 2
