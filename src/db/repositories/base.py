"""
Base Repository

Provides common CRUD operations for all repositories.
"""

import logging
from typing import Any, TypeVar, Generic
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel
from pymongo import WriteConcern

from constants import DEFAULT_MAX_QUERY_RESULTS

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    """
    Base repository with common database operations.

    Provides:
    - CRUD operations (create, read, update, delete)
    - Bulk operations
    - Query helpers
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str, write_concern: WriteConcern | None = None):
        """
        Initialize repository with database and collection.

        Args:
            db: AsyncIOMotorDatabase instance
            collection_name: Name of the MongoDB collection
            write_concern: Optional per-collection write concern. Durable-record
                repositories pass WriteConcern(w="majority") so the write
                survives a primary failover; omitting it keeps the driver
                default (w:1), which is correct for caches and ephemeral state.
        """
        self.db = db
        self.collection: AsyncIOMotorCollection = db.get_collection(collection_name, write_concern=write_concern) if write_concern is not None else db[collection_name]
        self.collection_name = collection_name

    async def create(self, document: dict[str, Any]) -> str:
        """
        Insert a new document.

        Args:
            document: Document to insert

        Returns:
            Inserted document ID as string
        """
        try:
            result = await self.collection.insert_one(document)
            logger.debug(f"Created document in {self.collection_name}: {result.inserted_id}")
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Failed to create document in {self.collection_name}: {e}")
            raise

    async def create_many(self, documents: list[dict[str, Any]]) -> list[str]:
        """
        Insert multiple documents.

        Args:
            documents: List of documents to insert

        Returns:
            List of inserted document IDs
        """
        try:
            result = await self.collection.insert_many(documents)
            logger.debug(f"Created {len(result.inserted_ids)} documents in {self.collection_name}")
            return [str(id) for id in result.inserted_ids]
        except Exception as e:
            logger.error(f"Failed to create documents in {self.collection_name}: {e}")
            raise

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """
        Find a single document matching the query.

        Args:
            query: MongoDB query filter

        Returns:
            Document dict or None
        """
        try:
            return await self.collection.find_one(query)
        except Exception as e:
            logger.error(f"Failed to find document in {self.collection_name}: {e}")
            raise

    async def find_by_id(self, id_field: str, id_value: str) -> dict[str, Any] | None:
        """
        Find a document by its ID field.

        Args:
            id_field: Name of the ID field
            id_value: Value to search for

        Returns:
            Document dict or None
        """
        return await self.find_one({id_field: id_value})

    async def find_many(
        self,
        query: dict[str, Any],
        sort: list[tuple] | None = None,
        limit: int = 0,
        skip: int = 0,
        projection: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find multiple documents matching the query.

        Args:
            query: MongoDB query filter
            sort: List of (field, direction) tuples
            limit: Maximum documents to return. 0 means "no explicit limit" — a
                DEFAULT_MAX_QUERY_RESULTS safety ceiling is applied so an
                unbounded query can never materialize an entire collection into
                memory. Pass a positive value for a precise cap.
            skip: Number of documents to skip
            projection: Fields to include/exclude (e.g., {"field": 1, "_id": 0})

        Returns:
            List of document dicts
        """
        try:
            cursor = self.collection.find(query, projection)

            if sort:
                cursor = cursor.sort(sort)
            if skip:
                cursor = cursor.skip(skip)

            # Apply an explicit caller limit, or fall back to the safety ceiling
            # so to_list() is never unbounded.
            effective_limit = limit if limit else DEFAULT_MAX_QUERY_RESULTS
            cursor = cursor.limit(effective_limit)

            results = await cursor.to_list(length=effective_limit)

            # Surface (never silently hide) the case where the safety ceiling
            # clipped a "no explicit limit" query — it means a caller needs to
            # paginate or pass a real limit.
            if not limit and len(results) >= DEFAULT_MAX_QUERY_RESULTS:
                logger.warning(
                    f"find_many on {self.collection_name} hit the DEFAULT_MAX_QUERY_RESULTS "
                    f"ceiling ({DEFAULT_MAX_QUERY_RESULTS}); results truncated. "
                    f"Pass an explicit limit or paginate. query_keys={list(query.keys())}"
                )

            return results
        except Exception as e:
            logger.error(f"Failed to find documents in {self.collection_name}: {e}")
            raise

    async def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> bool:
        """
        Update a single document.

        Args:
            query: MongoDB query filter
            update: Update operations (use $set, etc.)
            upsert: Create document if not exists

        Returns:
            True when the document was modified OR upserted, False otherwise.

            This boolean is the load-bearing contract: callers must treat the
            return value as a bool, NOT as a pymongo ``UpdateResult``. The
            pymongo result is intentionally collapsed here so the abstraction
            does not leak the driver type back to repositories.
        """
        try:
            result = await self.collection.update_one(query, update, upsert=upsert)
            return result.modified_count > 0 or result.upserted_id is not None
        except Exception as e:
            logger.error(f"Failed to update document in {self.collection_name}: {e}")
            raise

    async def update_many(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
    ) -> int:
        """
        Update multiple documents.

        Args:
            query: MongoDB query filter
            update: Update operations

        Returns:
            Number of modified documents
        """
        try:
            result = await self.collection.update_many(query, update)
            return result.modified_count
        except Exception as e:
            logger.error(f"Failed to update documents in {self.collection_name}: {e}")
            raise

    async def delete_one(self, query: dict[str, Any]) -> bool:
        """
        Delete a single document.

        Args:
            query: MongoDB query filter

        Returns:
            True if document was deleted
        """
        try:
            result = await self.collection.delete_one(query)
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to delete document in {self.collection_name}: {e}")
            raise

    async def delete_many(self, query: dict[str, Any]) -> int:
        """
        Delete multiple documents.

        Args:
            query: MongoDB query filter

        Returns:
            Number of deleted documents
        """
        try:
            result = await self.collection.delete_many(query)
            return result.deleted_count
        except Exception as e:
            logger.error(f"Failed to delete documents in {self.collection_name}: {e}")
            raise

    async def count(self, query: dict[str, Any] = None) -> int:
        """
        Count documents matching the query.

        Args:
            query: MongoDB query filter (None = count all)

        Returns:
            Document count
        """
        try:
            return await self.collection.count_documents(query or {})
        except Exception as e:
            logger.error(f"Failed to count documents in {self.collection_name}: {e}")
            raise

    async def exists(self, query: dict[str, Any]) -> bool:
        """
        Check if any document matches the query.

        Uses find_one with _id-only projection for efficiency
        instead of count_documents which scans the entire matching set.

        Args:
            query: MongoDB query filter

        Returns:
            True if at least one document exists
        """
        try:
            return (await self.collection.find_one(query, {"_id": 1})) is not None
        except Exception as e:
            logger.error(f"Failed to check existence in {self.collection_name}: {e}")
            raise
