"""
Discussions Repository

Manages discussion records extracted from WhatsApp chats.
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Any

from bson.binary import Binary, BinaryVectorDtype
from pymongo.asynchronous.database import AsyncDatabase

from db.repositories.base import BaseRepository
from constants import COLLECTION_DISCUSSIONS, DEFAULT_EMBEDDING_MODEL, DISCUSSION_VECTOR_INDEX_NAME
from custom_types.db_schemas import DiscussionDocument
from custom_types.field_keys import DbFieldKeys, DiscussionKeys

logger = logging.getLogger(__name__)

# $vectorSearch tuning for discussion similarity. The multiplier scales the HNSW
# candidate pool with the requested top_k (more candidates -> higher recall,
# higher latency); the cap is a latency guardrail mirroring the RAG hybrid path.
_NUM_CANDIDATES_MULTIPLIER = 10
_MAX_NUM_CANDIDATES = 1000
# Intermediate field holding the raw (normalized) Atlas vectorSearchScore.
_VECTOR_SCORE_FIELD = "_vector_score"
_VECTOR_SCORE_REF = f"${_VECTOR_SCORE_FIELD}"
# Field name returned to callers, holding the raw-cosine similarity.
_SIMILARITY_FIELD = "similarity"
# Embedding fields are attached at the storage boundary (as BinData), not dumped
# from the model. Names match DiscussionDocument's field names.
_EMBEDDING_FIELDS = {DbFieldKeys.EMBEDDING, DbFieldKeys.EMBEDDING_MODEL, DbFieldKeys.EMBEDDING_TIMESTAMP}


class DiscussionsRepository(BaseRepository):
    """
    Repository for discussion storage and retrieval.

    Stores:
    - Discussion metadata (title, nutshell, chat name)
    - Ranking scores
    - Message counts
    - Links to messages
    """

    # Projection that drops the large embedding from read/list paths. A 1536-float
    # embedding is ~6KB of BSON per doc; list views never need it, only the
    # vector-search index and similarity queries do.
    _EXCLUDE_EMBEDDING_PROJECTION = {DbFieldKeys.EMBEDDING: 0}

    def __init__(self, db: AsyncDatabase):
        super().__init__(db, COLLECTION_DISCUSSIONS)

    async def create_discussion(
        self,
        discussion_id: str,
        run_id: str,
        chat_name: str,
        title: str,
        nutshell: str,
        message_ids: list[str],
        ranking_score: float = 0.0,
        first_message_timestamp: int = None,
        metadata: dict[str, Any] = None,
        generate_embedding: bool = True,
    ) -> str:
        """
        Create a new discussion record with optional embedding generation.

        Args:
            discussion_id: Unique identifier for the discussion
            run_id: Associated pipeline run ID
            chat_name: Source chat name
            title: Discussion title
            nutshell: Brief summary
            message_ids: List of message IDs in this discussion
            ranking_score: Relevance ranking score (0-10)
            first_message_timestamp: Timestamp of first message
            metadata: Additional metadata
            generate_embedding: Auto-generate embedding for semantic search (default: True)

        Returns:
            Inserted document ID
        """
        # Generate embedding for semantic search (fail-soft).
        # embed_text() is synchronous (OpenAI API call), offload to thread.
        embedding: list[float] | None = None
        embedding_model: str | None = None
        embedding_timestamp: datetime | None = None
        if generate_embedding:
            try:
                from utils.embedding import EmbeddingProviderFactory

                embedder = EmbeddingProviderFactory.create()
                discussion_text = f"{title}. {nutshell}"
                embedding = await asyncio.to_thread(embedder.embed_text, discussion_text)

                if embedding:
                    embedding_model = DEFAULT_EMBEDDING_MODEL
                    embedding_timestamp = datetime.now(UTC)
                    logger.info(f"Generated embedding for discussion: {discussion_id}, " f"dimension={len(embedding)}")
                else:
                    logger.warning(f"Failed to generate embedding for discussion: {discussion_id}")

            except Exception as e:
                logger.error(f"Embedding generation failed for discussion {discussion_id}: {e}. " "Proceeding without embedding (fail-soft).")

        # Build the document THROUGH the Pydantic model so the schema is the
        # single source of truth. The embedding fields are storage-boundary
        # concerns (the embedding is persisted as BinData, not the model's
        # logical list[float]), so they are excluded from the dump here and
        # attached below only when an embedding was actually generated. This
        # uses targeted exclusion rather than a blanket exclude_none so a future
        # field carrying a meaningful None is never silently dropped.
        discussion = DiscussionDocument(
            discussion_id=discussion_id,
            run_id=run_id,
            chat_name=chat_name,
            title=title,
            nutshell=nutshell,
            message_ids=message_ids,
            message_count=len(message_ids),
            ranking_score=ranking_score,
            first_message_timestamp=first_message_timestamp,
            metadata=metadata or {},
        )
        document = discussion.model_dump(exclude=_EMBEDDING_FIELDS)

        # Persist the embedding as BSON Binary subtype 9 (FLOAT32) for parity
        # with rag_chunks: ~2x smaller than a 1536-element BSON array and the
        # representation $vectorSearch's scalar-quantized index expects.
        if embedding:
            document[DbFieldKeys.EMBEDDING] = Binary.from_vector(list(embedding), dtype=BinaryVectorDtype.FLOAT32)
            document[DbFieldKeys.EMBEDDING_MODEL] = embedding_model
            document[DbFieldKeys.EMBEDDING_TIMESTAMP] = embedding_timestamp

        return await self.create(document)

    @staticmethod
    def _attach_embedding(document: dict[str, Any], embedding: list[float] | None, embedding_model: str) -> None:
        """Attach an embedding to a built discussion document as BSON Binary.

        Stored as subtype-9 FLOAT32 BinData for parity with rag_chunks (~2x
        smaller than a 1536-element BSON array, and the representation the
        scalar-quantized $vectorSearch index expects). No-op when embedding is
        None (fail-soft embedding: the discussion is still stored, just without
        a vector — it simply won't surface in similarity search until re-embedded).
        """
        if embedding:
            document[DbFieldKeys.EMBEDDING] = Binary.from_vector(list(embedding), dtype=BinaryVectorDtype.FLOAT32)
            document[DbFieldKeys.EMBEDDING_MODEL] = embedding_model
            document[DbFieldKeys.EMBEDDING_TIMESTAMP] = datetime.now(UTC)

    async def create_discussions_bulk(
        self,
        discussions: list[dict[str, Any]],
        generate_embeddings: bool = True,
    ) -> int:
        """Upsert many discussions in one bulk_write, embedding them in one batch.

        Replaces the former per-discussion loop (one OpenAI call + one insert
        each) with a single batched embedding call and a single ordered=False
        bulk upsert. Keyed on discussion_id so a re-run patches rather than
        duplicates.

        Fail-fast: a bulk write error propagates (with per-op details) instead
        of being masked as a partial count. Embedding remains fail-soft per
        discussion — a None embedding stores the discussion without a vector.

        Args:
            discussions: Pre-built discussion dicts. Each MUST carry the keys
                produced by RunTracker.store_discussions: discussion_id, run_id,
                chat_name, title, nutshell, message_ids, ranking_score,
                first_message_timestamp, metadata.
            generate_embeddings: When True, embed `title. nutshell` per discussion.

        Returns:
            Number of documents inserted or modified.
        """
        if not discussions:
            return 0

        from pymongo import UpdateOne
        from pymongo.errors import BulkWriteError

        embeddings: list[list[float] | None] = [None] * len(discussions)
        embedding_model = DEFAULT_EMBEDDING_MODEL
        if generate_embeddings:
            try:
                from utils.embedding import EmbeddingProviderFactory

                embedder = EmbeddingProviderFactory.create()
                texts = [f"{d.get(DbFieldKeys.TITLE, '')}. {d.get(DbFieldKeys.NUTSHELL, '')}" for d in discussions]
                # Single batched OpenAI call for the whole chat's discussions,
                # offloaded since embed_texts_batch is synchronous.
                embeddings = await asyncio.to_thread(embedder.embed_texts_batch, texts)
            except Exception as e:
                # Fail-soft embedding: store the discussions without vectors.
                logger.error(f"Batch embedding failed for {len(discussions)} discussions; storing without vectors (fail-soft): {e}")
                embeddings = [None] * len(discussions)

        operations = []
        for disc, embedding in zip(discussions, embeddings):
            document = DiscussionDocument(
                discussion_id=disc[DbFieldKeys.DISCUSSION_ID],
                run_id=disc[DbFieldKeys.RUN_ID],
                chat_name=disc[DbFieldKeys.CHAT_NAME],
                title=disc.get(DbFieldKeys.TITLE, ""),
                nutshell=disc.get(DbFieldKeys.NUTSHELL, ""),
                message_ids=disc.get(DbFieldKeys.MESSAGE_IDS, []),
                message_count=len(disc.get(DbFieldKeys.MESSAGE_IDS, [])),
                ranking_score=disc.get(DbFieldKeys.RANKING_SCORE, 0.0),
                first_message_timestamp=disc.get(DiscussionKeys.FIRST_MESSAGE_TIMESTAMP),
                metadata=disc.get(DbFieldKeys.METADATA, {}),
            ).model_dump(exclude=_EMBEDDING_FIELDS)
            self._attach_embedding(document, embedding, embedding_model)
            operations.append(
                UpdateOne(
                    {DbFieldKeys.DISCUSSION_ID: document[DbFieldKeys.DISCUSSION_ID]},
                    {"$set": document},
                    upsert=True,
                )
            )

        try:
            result = await self.collection.bulk_write(operations, ordered=False)
        except BulkWriteError as e:
            logger.error(f"Bulk upsert of {len(operations)} discussions failed: {e.details}")
            raise
        total = result.upserted_count + result.modified_count
        logger.info(f"Bulk-upserted {total} discussions (inserted={result.upserted_count}, updated={result.modified_count})")
        return total

    async def get_discussion(self, discussion_id: str) -> dict[str, Any] | None:
        """Get a discussion by its ID."""
        return await self.find_by_id(DbFieldKeys.DISCUSSION_ID, discussion_id)

    async def get_discussions_by_run(
        self,
        run_id: str,
        sort_by_ranking: bool = True,
        limit: int = 0,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get all discussions for a run.

        Args:
            run_id: Pipeline run ID
            sort_by_ranking: Sort by ranking score descending (default) or by creation date
            limit: Maximum discussions to return (0 = no limit)
            offset: Number of discussions to skip for pagination
        """
        sort = [(DbFieldKeys.RANKING_SCORE, -1)] if sort_by_ranking else [(DbFieldKeys.CREATED_AT, 1)]
        return await self.find_many({DbFieldKeys.RUN_ID: run_id}, sort=sort, limit=limit, skip=offset, projection=self._EXCLUDE_EMBEDDING_PROJECTION)

    async def get_top_discussions(
        self,
        run_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get top-ranked discussions for a run."""
        return await self.find_many(
            {DbFieldKeys.RUN_ID: run_id},
            sort=[(DbFieldKeys.RANKING_SCORE, -1)],
            limit=limit,
            projection=self._EXCLUDE_EMBEDDING_PROJECTION,
        )

    async def update_ranking(
        self,
        discussion_id: str,
        ranking_score: float,
    ) -> bool:
        """Update the ranking score for a discussion."""
        return await self.update_one(
            {DbFieldKeys.DISCUSSION_ID: discussion_id},
            {"$set": {DbFieldKeys.RANKING_SCORE: ranking_score}},
        )

    async def find_similar_discussions(
        self,
        query_embedding: list[float],
        run_ids: list[str],
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Find historical discussions semantically similar to a query embedding.

        Runs the similarity ENTIRELY server-side via $vectorSearch over the
        DISCUSSION_VECTOR_INDEX_NAME index, pre-filtering to the given run_ids
        inside the $vectorSearch stage. Embeddings never leave the server; only
        the top-k candidate metadata + a `similarity` score are returned. This
        replaces the former O(N) pattern of pulling up to 1000 full embeddings
        to the client and scoring them in a Python loop.

        Args:
            query_embedding: The embedding to compare against (raw float list).
            run_ids: Previous-run IDs to restrict the search to.
            top_k: Maximum number of candidates to return.
            min_score: RAW COSINE relevance floor in [-1, 1]; candidates below it
                are dropped. This is the same scale as the retired client-side
                cosine comparison, so callers keep reasoning in raw cosine.

        Returns:
            List of dicts with discussion metadata and a `similarity` float,
            sorted by descending similarity. `similarity` is RAW COSINE (not the
            normalized Atlas score), again matching the old contract. No
            `embedding` field.

        Note on score domains: Atlas `$vectorSearch` with `similarity:"cosine"`
        exposes `vectorSearchScore` as the NORMALIZED score `(1 + cosine) / 2` in
        [0, 1], NOT raw cosine. We therefore convert the raw-cosine `min_score`
        into that domain for the `$match`, and convert the score back to raw
        cosine (`2 * score - 1`) before returning, so nothing outside this method
        ever has to know about the normalization.
        """
        if not run_ids:
            return []

        try:
            query_vector_bin = Binary.from_vector(list(query_embedding), dtype=BinaryVectorDtype.FLOAT32)
            num_candidates = min(top_k * _NUM_CANDIDATES_MULTIPLIER, _MAX_NUM_CANDIDATES)
            # Raw cosine floor -> normalized vectorSearchScore floor.
            normalized_min_score = (1.0 + min_score) / 2.0

            pipeline = [
                {
                    "$vectorSearch": {
                        "index": DISCUSSION_VECTOR_INDEX_NAME,
                        "path": DbFieldKeys.EMBEDDING,
                        "queryVector": query_vector_bin,
                        "numCandidates": num_candidates,
                        "limit": top_k,
                        "filter": {DbFieldKeys.RUN_ID: {"$in": run_ids}},
                    }
                },
                {"$addFields": {_VECTOR_SCORE_FIELD: {"$meta": "vectorSearchScore"}}},
                {"$match": {_VECTOR_SCORE_FIELD: {"$gte": normalized_min_score}}},
                # Convert normalized score back to raw cosine for the caller.
                {"$addFields": {_SIMILARITY_FIELD: {"$subtract": [{"$multiply": [_VECTOR_SCORE_REF, 2.0]}, 1.0]}}},
                {
                    "$project": {
                        "_id": 0,
                        DbFieldKeys.DISCUSSION_ID: 1,
                        DbFieldKeys.TITLE: 1,
                        DbFieldKeys.NUTSHELL: 1,
                        DbFieldKeys.RUN_ID: 1,
                        DbFieldKeys.CHAT_NAME: 1,
                        DbFieldKeys.CREATED_AT: 1,
                        _SIMILARITY_FIELD: 1,
                    }
                },
            ]

            results = await self.collection.aggregate(pipeline).to_list(top_k)
            logger.info(f"Vector-searched {len(results)} similar discussions across {len(run_ids)} run_ids (raw_cosine_min_score={min_score:.2f})")
            return results

        except Exception as e:
            logger.error(f"Failed to vector-search similar discussions: {e}, run_ids={run_ids[:3]}...")
            raise
