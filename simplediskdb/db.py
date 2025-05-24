"""
Module for MongoDB-style persistent database operations.

This module provides a MongoDB-like persistent database implementation using diskcache.
It follows the MongoDB hierarchy of database -> collections -> documents, offering a
familiar interface for developers experienced with MongoDB while providing local
disk-based storage.

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

Usage:
    from diskcache_db.db import DiskDB

    # Get a database instance
    db = DiskDB()

    # Create collections
    tasks = db.add_collection('tasks')
    users = db.add_collection('users')

    # Insert documents
    tasks.insert_one({
        "task_id": "T123",
        "status": "pending",
        "priority": 1,
        "assigned_to": "john",
        "files": ["doc1.pdf", "doc2.txt"]
    })

    # Bulk insert
    users.insert_many([
        {"name": "John", "role": "admin"},
        {"name": "Jane", "role": "user"}
    ])

    # Example 1: Complex query with AND, OR, and comparison operators
    results = tasks.find(
        conditions={
            "$and": [
                {"status": "pending"},
                {"$or": [
                    {"priority": {"$gt": 0}},
                    {"priority": 0}
                ]},
                {"files": {"$exists": True}},
                {"task_id": {"$nin": ["T123", "T456"]}}
            ]
        },
        sort=[("priority", -1), ("created_at", 1)],
        limit=10
    )

    # Example 2: Simple OR query with projection
    results = tasks.find(
        conditions={
            "$or": [
                {"status": "failed"},
                {"status": "pending"}
            ]
        },
        projection={"task_id": 1, "status": 1, "files": 1},
        sort=[("_added_at", -1)],
        limit=20
    )

    # Access collections using dot notation or dictionary style
    same_tasks = db.tasks  # or db['tasks']
    print(list(results))

This module is designed to provide a flexible and efficient data storage solution
for various components of the application, ensuring data persistence and
offering powerful querying capabilities.
"""

import argparse
from datetime import datetime, timedelta
from logging import getLogger, StreamHandler, Formatter
from pathlib import Path
from threading import Lock, RLock
from typing import Dict, List, Optional, Union

from .collection import Collection
from .exceptions import NoCollectionError

logger = getLogger('simplediskdb')
logger.setLevel('DEBUG')
formatter = Formatter(
    "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
handler = StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)


class DiskDB:
    """A MongoDB-style persistent database implementation.

    DiskDB implements a MongoDB-like interface for disk-based document storage.
    It follows the MongoDB organizational hierarchy:
    - Database (DiskDB): The top-level container
    - Collections: Named groups of documents (accessed via db.collection_name or db['collection_name'])
    - Documents: JSON-like data records within collections

    Example:
        db = DiskDB()
        users = db.add_collection('users')  # Create a new collection
        users.insert_one({'name': 'John', 'age': 30})  # Insert a document

        # Query with MongoDB-style operators
        results = users.find(
            conditions={'age': {'$gt': 25}},
            projection={'name': 1},
            sort=[('age', -1)],
            limit=10
        )
    """

    _instances: Dict[str, 'DiskDB'] = {}
    _instances_lock = Lock()  # Lock for singleton instance creation

    def __init__(self, base_directory: Union[str, Path] = None):
        """
        Initialize the database with a directory for storage.

        Args:
            base_directory: Path to the directory where the cache will be stored
        """
        if base_directory is None:
            base_directory = Path(Path.home() / '.simplediskdb')
        elif isinstance(base_directory, Path):
            base_directory = base_directory / '.simplediskdb'
        elif isinstance(base_directory, str):
            base_directory = Path(base_directory) / '.simplediskdb'
        else:
            raise ValueError("base_directory must be a string or Path object")

        # Ensure directories exist
        base_directory.mkdir(parents=True, exist_ok=True)
        self._base_dir = base_directory

        self.collections = dict()
        collection_names = self.list_collections()
        for name in collection_names:
            self.collections[name] = Collection(name, self._base_dir)

        self._lock = RLock()  # Reentrant lock for thread safety

    def __getattr__(self, name: str) -> Collection:
        """Get a collection by its name using dot notation."""
        return self.get_collection(name)

    def __getitem__(self, name: str) -> Collection:
        """Get a collection by its name using dictionary notation."""
        return self.get_collection(name)

    def get_collection(self, name: str) -> Collection:
        """Get or create a collection.

        Args:
            name: Name of the collection

        Returns:
            Collection instance
        """
        with self._lock:
            if name not in self.collections:
                raise NoCollectionError(name)
            return self.collections[name]

    def list_collections(self) -> List[str]:
        """List all collections in the database."""
        collections = []
        for item in self._base_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.') and any(file.name.endswith('.db') for file in item.iterdir()):
                collections.append(item.name)
        return collections

    def drop_collection(self, name: str) -> None:
        """Drop a collection from the database."""
        with self._lock:
            if name in self.collections:
                collection = self.collections[name]
                collection.drop()
            else:
                logger.warning(f"Collection '{name}' not found.")

    def add_collection(self, name: str) -> Collection:
        """Add a collection to the database."""
        with self._lock:
            if name not in self.collections:
                self.collections[name] = Collection(name, self._base_dir)
            return self.collections[name]

    def __enter__(self):
        """Context manager entry."""
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._lock.release()


def load_example_data():
    db = DiskDB(base_directory=Path.home())
    example_data = {
        "users": [
            {"name": "John Doe", "age": 26, "email": "john@example.com", "roles": ["user"], "active": True, "last_login": datetime.now() - timedelta(days=2)},
            {"name": "Jane Doe", "age": 22, "email": "jane@example.com", "roles": ["admin", "user"], "active": True, "preferences": {"theme": "dark", "notifications": True}},
            {"name": "Bob Smith", "age": 18, "email": "bob@example.com", "roles": ["user"], "active": False, "deactivated_at": datetime.now() - timedelta(days=30)},
            {"name": "Alice Johnson", "age": 25, "email": "alice@example.com", "roles": ["moderator"], "joined": datetime.now(), "skills": ["python", "javascript", "mongodb"]},
            {"name": "Eve Wilson", "age": 33, "email": "eve@example.com", "roles": ["user", "admin"], "active": True, "department": "Engineering"},
            {"name": "Charlie Brown", "age": 28, "email": "charlie@example.com", "roles": ["user"], "active": True, "location": {"city": "San Francisco", "country": "USA"}},
            {"name": "David Lee", "age": 31, "email": "david@example.com", "roles": ["user"], "active": True, "projects": ["alpha", "beta", "gamma"]}
        ],
        "products": [
            {"name": "Laptop Pro X1", "price": 1299.99, "in_stock": True, "categories": ["electronics", "computers"], "specs": {"cpu": "i7", "ram": "16GB", "storage": "512GB SSD"}, "ratings": [4.5, 4.8, 4.2]},
            {"name": "Wireless Mouse M1", "price": 29.99, "in_stock": False, "categories": ["electronics", "accessories"], "color_options": ["black", "white", "gray"], "warranty_months": 12},
            {"name": "Coffee Maker Pro", "price": 89.99, "in_stock": True, "categories": ["appliances", "kitchen"], "features": ["programmable", "auto-shutoff", "built-in grinder"]},
            {"name": "Smart Watch S2", "price": 199.99, "in_stock": True, "categories": ["electronics", "wearables"], "sensors": ["heart_rate", "gps", "accelerometer"], "water_resistant": True},
            {"name": "Desk Lamp LED", "price": 34.99, "in_stock": True, "categories": ["lighting", "office"], "color_temperature": [2700, 4000, 6500], "dimmable": True}
        ],
        "orders": [
            {"order_id": "ORD001", "user_email": "john@example.com", "items": [{"product": "Laptop Pro X1", "quantity": 1}, {"product": "Wireless Mouse M1", "quantity": 2}], "status": "delivered", "total": 1359.97, "created_at": datetime.now() - timedelta(days=15)},
            {"order_id": "ORD002", "user_email": "alice@example.com", "items": [{"product": "Smart Watch S2", "quantity": 1}], "status": "processing", "total": 199.99, "created_at": datetime.now() - timedelta(hours=12)},
            {"order_id": "ORD003", "user_email": "eve@example.com", "items": [{"product": "Coffee Maker Pro", "quantity": 1}, {"product": "Desk Lamp LED", "quantity": 2}], "status": "shipped", "total": 159.97, "created_at": datetime.now() - timedelta(days=3)}
        ],
        "reviews": [
            {"product": "Laptop Pro X1", "user_email": "john@example.com", "rating": 4.5, "title": "Great laptop!", "content": "Excellent performance and battery life", "verified_purchase": True, "helpful_votes": 12, "created_at": datetime.now() - timedelta(days=10)},
            {"product": "Smart Watch S2", "user_email": "alice@example.com", "rating": 5.0, "title": "Perfect fitness companion", "content": "Accurate sensors and great battery life", "verified_purchase": True, "helpful_votes": 8, "created_at": datetime.now() - timedelta(days=5)},
            {"product": "Coffee Maker Pro", "user_email": "eve@example.com", "rating": 4.0, "title": "Good but noisy", "content": "Makes great coffee but grinder is a bit loud", "verified_purchase": True, "helpful_votes": 3, "created_at": datetime.now() - timedelta(days=2)}
        ]
    }
    for collection, documents in example_data.items():
        collection = db.add_collection(collection)
        collection.insert_many(documents)
    logger.info("Loaded example data. Collections: %s", list(example_data.keys()))

def delete_example_data():
    db = DiskDB(base_directory=Path.home())
    for collection in db.list_collections():
        db.drop_collection(collection)
    logger.info("Deleted example data. Collections: %s", db.list_collections())


def main():
    parser = argparse.ArgumentParser(
        description='Simple disk database - MongoDB-style disk-based database')
    parser.add_argument('--load-example', action='store_true',
                        help='Load example data into the database')
    parser.add_argument('--delete-example', action='store_true',
                        help='Delete all example data from the database')
    args = parser.parse_args()

    if args.load_example:
        load_example_data()
    elif args.delete_example:
        delete_example_data()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()