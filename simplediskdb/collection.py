"""
SimpleDiskDB - A MongoDB-style disk-based database implementation

This module provides a MongoDB-like persistent database implementation using diskcache.
It follows the MongoDB organizational hierarchy:
- Database (DiskDB): The top-level container
- Collections: Named groups of documents (accessed via db.collection_name or db['collection_name'])
- Documents: JSON-like data records within collections

The module is organized in a three-tier hierarchy:
1. Database (DiskDB): The top-level container managing multiple collections
2. Collections: Named groups of documents (like tables in SQL databases)
3. Documents: Individual JSON-like data records stored within collections

Key features:
- MongoDB-like document storage and querying
- Thread-safe operations using locks
- Rich query language supporting $and, $or, $gt, $exists, $nin operators
- Flexible document schema within collections
- Sorting and pagination support via sort and limit parameters
- Projection support to retrieve specific fields
- Data persistence across application restarts

"""
from diskcache import Cache
import operator
from typing import Any, List
from threading import RLock
from pathlib import Path
from bson import ObjectId
from datetime import datetime
import shutil


class Collection:
    """Collection class representing a MongoDB-like collection."""

    def __init__(self, name: str, cache_dir: Path):
        """Initialize a collection.

        Args:
            name: Name of the collection
            cache_dir: Path to the collection's cache directory
        """
        self.name = name
        self._cache_dir = cache_dir / name
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(self._cache_dir))
        self._lock = RLock()

    def insert_one(self, document: Any) -> str:
        """Add data to base with auto-generated ObjectId.
        Args:
            data (dict): Data to store (must be JSON serializable)
        Returns:
            str: ObjectId of the inserted document
        """
        with self._lock:
            # Convert to dict if needed
            if hasattr(document, '__dict__'):
                data_dict = document.__dict__.copy()
            else:
                data_dict = document.copy() if isinstance(
                    document, dict) else {'value': document}

            # Generate new ObjectId
            _id = str(ObjectId())

            # Add MongoDB-style metadata
            if isinstance(data_dict, dict):
                data_dict['_id'] = _id
                # Use MongoDB-style timestamps
                now = datetime.now()
                data_dict['created_at'] = now
                data_dict['last_updated_at'] = now

            # Store data
            self._cache.set(_id, data_dict)
            return _id

    def insert_many(self, documents: List[Any]) -> List[str]:
        """Add multiple documents to base with auto-generated ObjectId.
        Args:
                documents: List of documents to store (must be JSON serializable)
        Returns:
                List[str]: List of ObjectIds of the inserted documents
        """
        return [self.insert_one(document) for document in documents]

    def update_one(self, query: dict, update: dict):
        """Update a single document matching the query.
        Args:
                query: MongoDB-style query to match the document to update
                update: MongoDB-style update to apply to the matched document
        Returns:
                bool: True if a document was updated, False otherwise
        """
        with self._lock:
            for key in self._cache.iterkeys():
                doc = self._cache.get(key)
                if doc and all(doc.get(k) == v for k, v in query.items()):
                    doc.update(update)
                    self._cache[key] = doc
                    return True
            return False

    def update_many(self, query: dict, update: dict):
        """Update multiple documents matching the query.
        Args:
                query: MongoDB-style query to match the documents to update
                update: MongoDB-style update to apply to the matched documents
        Returns:
                bool: True if any documents were updated, False otherwise
        """
        with self._lock:
            updated = False
            for key in self._cache.iterkeys():
                doc = self._cache.get(key)
                if doc and all(doc.get(k) == v for k, v in query.items()):
                    doc.update(update)
                    self._cache[key] = doc
                    updated = True
        return updated

    def delete_one(self, query: dict):
        """Delete a single document matching the query.
        Args:
                query: MongoDB-style query to match the document to delete
        Returns:
                bool: True if a document was deleted, False otherwise
        """
        with self._lock:
            for key in self._cache.iterkeys():
                doc = self._cache.get(key)
                if doc and all(doc.get(k) == v for k, v in query.items()):
                    del self._cache[key]
                    return True
            return False

    def delete_many(self, query: dict):
        """Delete multiple documents matching the query.
        Args:
                query: MongoDB-style query to match the documents to delete
        Returns:
                bool: True if any documents were deleted, False otherwise
        """
        with self._lock:
            deleted = False
            for key in self._cache.iterkeys():
                doc = self._cache.get(key)
                if doc and all(doc.get(k) == v for k, v in query.items()):
                    del self._cache[key]
                    deleted = True
        return deleted

    def _match(self, doc, query):
        op_map = {
            "$gt": operator.gt,
            "$lt": operator.lt,
            "$gte": operator.ge,
            "$lte": operator.le,
            "$eq": operator.eq,
            "$ne": operator.ne,
            "$in": lambda a, b: a in b,
            "$nin": lambda a, b: a not in b,
        }
        for key, condition in query.items():
            if isinstance(condition, dict):  # operator query
                for op, val in condition.items():
                    if op not in op_map or not op_map[op](doc.get(key), val):
                        return False
            else:  # direct match
                if doc.get(key) != condition:
                    return False
        return True

    def _projection(self, projection: dict, results: list):
        if projection is not None:
            include = {k for k, v in projection.items() if v}
            exclude = {k for k, v in projection.items() if not v}
            for i in range(len(results)):
                results[i] = {
                    k: v for k, v in results[i].items()
                    if (include and k in include) or (exclude and k not in exclude)
                }
        return results

    def _sort(self, sort: list, results: list):
        if sort:
            for field, direction in reversed(sort):
                results.sort(key=lambda x: x.get(field, None),
                             reverse=(direction == -1))
        return results

    def query(self, query: dict = None, projection: dict = None, sort: list = None, many=False):
        """
        Find documents with support for query operators, field projection, and sorting.

        Args:
            query (dict): MongoDB-style query. e.g., {"age": {"$gt": 25}, "status": "active"}
            projection (dict): Fields to include/exclude. e.g., {"name": 1, "_id": 0}
            sort (list): List of tuples to sort by. e.g., [("age", 1), ("name", -1)]

        Returns:
            list: List of matched and transformed documents.
        """
        # Start filtering
        keys = self._cache.iterkeys()
        results = []
        for key in keys:
            doc = self._cache.get(key)
            if doc and self._match(doc, query or {}):
                results.append(doc)
                if not many:
                    break
        results = self._projection(projection, results)
        results = self._sort(sort, results)
        return results

    def find_one(self, query: dict = None, projection: dict = None, sort: list = None):
        """Find a single document matching the query.
        Args:
                query: MongoDB-style query to match the document to find
                projection: Fields to include/exclude. e.g., {"name": 1, "_id": 0}
                sort: List of tuples to sort by. e.g., [("age", 1), ("name", -1)]
        Returns:
                dict: The matched document, or None if no document was found
        """
        return self.query(query, projection, sort, many=False)

    def find_many(self, query: dict = None, projection: dict = None, sort: list = None):
        """Find multiple documents matching the query.
        Args:
                query: MongoDB-style query to match the documents to find
                projection: Fields to include/exclude. e.g., {"name": 1, "_id": 0}
                sort: List of tuples to sort by. e.g., [("age", 1), ("name", -1)]
        Returns:
                list: List of matched documents
        """
        return self.query(query, projection=projection, sort=sort, many=True)

    def drop(self):
        """Drop the collection, removing all documents and the collection directory."""
        self.delete_many({})
        self._cache.close()
        shutil.rmtree(self._cache_dir)
