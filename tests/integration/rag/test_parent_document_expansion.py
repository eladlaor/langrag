"""Integration test: server-side $lookup parent-document expansion (D10).

Validates the real $lookup from rag_chunks -> messages keyed by
metadata.message_ids, against a live MongoDB. Inserts a newsletter chunk whose
metadata carries message ids plus the matching message documents, then asserts
RetrievalPipeline._expand_with_parents attaches those messages (time-ordered) as
parent_messages on the chunk.

Requires Docker with MongoDB. Skipped when unavailable.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

_src = str(Path(__file__).resolve().parents[3] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from constants import COLLECTION_MESSAGES, COLLECTION_RAG_CHUNKS  # noqa: E402
from custom_types.field_keys import DbFieldKeys, RAGChunkKeys as Keys, RAGChunkMetadataKeys  # noqa: E402
from tests._helpers.mongo import requires_mongodb  # noqa: E402


async def _fresh_db():
    import db.connection as conn_mod

    conn_mod._client = None
    conn_mod._database = None
    return await conn_mod.get_database()


def _pipeline_instance():
    from rag.retrieval.pipeline import RetrievalPipeline

    pipe = RetrievalPipeline.__new__(RetrievalPipeline)

    class _S:
        parent_messages_per_chunk_cap = 40

    pipe._settings = _S()
    return pipe


@requires_mongodb
async def test_expand_with_parents_lookup_live():
    db = await _fresh_db()
    chunks = db[COLLECTION_RAG_CHUNKS]
    messages = db[COLLECTION_MESSAGES]

    suffix = uuid.uuid4().hex[:8]
    chunk_id = f"pd-chunk-{suffix}"
    m1, m2 = f"pd-m1-{suffix}", f"pd-m2-{suffix}"

    await chunks.insert_one({
        Keys.CHUNK_ID: chunk_id,
        Keys.CONTENT_SOURCE: "newsletter",
        Keys.SOURCE_ID: f"nl-{suffix}",
        Keys.METADATA: {RAGChunkMetadataKeys.MESSAGE_IDS: [m1, m2]},
    })
    await messages.insert_many([
        {DbFieldKeys.MESSAGE_ID: m2, DbFieldKeys.SENDER: "bob", DbFieldKeys.CONTENT: "second", DbFieldKeys.TIMESTAMP: 200},
        {DbFieldKeys.MESSAGE_ID: m1, DbFieldKeys.SENDER: "ana", DbFieldKeys.CONTENT: "first", DbFieldKeys.TIMESTAMP: 100},
    ])

    try:
        pipe = _pipeline_instance()
        chunk_docs = [{Keys.CHUNK_ID: chunk_id, Keys.METADATA: {RAGChunkMetadataKeys.MESSAGE_IDS: [m1, m2]}}]
        await pipe._expand_with_parents(chunk_docs)

        parent = chunk_docs[0][RAGChunkMetadataKeys.PARENT_MESSAGES]
        # Both messages resolved, time-ordered (m1@100 before m2@200).
        assert [m[DbFieldKeys.MESSAGE_ID] for m in parent] == [m1, m2]
        assert parent[0][DbFieldKeys.SENDER] == "ana"
        assert parent[0][DbFieldKeys.CONTENT] == "first"
    finally:
        await chunks.delete_many({Keys.CHUNK_ID: chunk_id})
        await messages.delete_many({DbFieldKeys.MESSAGE_ID: {"$in": [m1, m2]}})
