"""
Exceptions raised by the SimpleDiskDB library.

This module contains exceptions that may be raised while interacting with the
SimpleDiskDB library.
"""


class NoCollectionError(Exception):
    """No collection with the given name was found in the database."""
    pass
