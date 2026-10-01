"""Raw store: immutable, timestamped snapshots of what providers returned.

Normalised data can always be rebuilt from these files, and a questionable number can
always be traced back to the response it came from. May import: domain.
"""

from front_office.rawstore.store import RawStore, RawStoreError, SaveResult, StoredSnapshot

__all__ = ["RawStore", "RawStoreError", "SaveResult", "StoredSnapshot"]
