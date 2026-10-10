"""Storage layer: the database schema and the repositories that read and write it.

Tables are built from the domain data contracts. Other layers never write SQL; they call
a repository. May import: domain.
"""

from front_office.storage.database import Database, StorageError
from front_office.storage.documents import DocumentHit, search_sections
from front_office.storage.operations import OperationsLog
from front_office.storage.rosters import RosterNotFound, RosterRepository
from front_office.storage.warehouse import Warehouse

__all__ = [
    "Database",
    "DocumentHit",
    "OperationsLog",
    "RosterNotFound",
    "RosterRepository",
    "StorageError",
    "Warehouse",
    "search_sections",
]
