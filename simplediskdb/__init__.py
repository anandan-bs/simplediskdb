"""SimpleDiskDB - A MongoDB-style disk-based database implementation"""

from .db import DiskDB
from .collection import Collection
from .exceptions import NoCollectionError

__version__ = '0.1.0'
__all__ = ['DiskDB', 'Collection', 'NoCollectionError']