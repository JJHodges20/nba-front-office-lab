"""File-based raw store.

Layout::

    <root>/<source>/<dataset>/<partition>/<fetched_at>_<hash>.json.gz

Each file is one snapshot: an envelope holding the payload exactly as the provider
returned it, plus its provenance. Files are written once and never changed or deleted
by the lab. When a fetch returns the same payload as the newest stored snapshot of that
partition, no new file is written.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from front_office.domain.snapshots import GLOBAL_PARTITION, Snapshot, partition_key

# Microseconds, so that two snapshots saved in quick succession still sort in order.
_TIMESTAMP = "%Y%m%dT%H%M%S%fZ"
# Snapshots written before the store kept microseconds; still read, never written.
_TIMESTAMP_TO_THE_SECOND = "%Y%m%dT%H%M%SZ"
_SUFFIX = ".json.gz"
_HASH_CHARS = 16


class RawStoreError(RuntimeError):
    """A stored snapshot is unreadable or does not match its location."""


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    """A snapshot on disk, described without loading its payload."""

    path: Path
    source: str
    dataset: str
    partition: Mapping[str, str]
    fetched_at: datetime
    hash_prefix: str

    @property
    def partition_key(self) -> str:
        return partition_key(self.partition)


@dataclass(frozen=True, slots=True)
class SaveResult:
    stored: StoredSnapshot
    created: bool
    """False when the payload matched the newest stored snapshot and nothing was written."""


class RawStore:
    """Append-only store of provider snapshots."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save(self, snapshot: Snapshot) -> SaveResult:
        """Store a snapshot unless it repeats the newest one for its partition."""
        digest = snapshot.content_hash
        newest = self.latest_info(snapshot.source, snapshot.dataset, snapshot.partition)
        if newest is not None and newest.hash_prefix == digest[:_HASH_CHARS]:
            return SaveResult(newest, created=False)

        directory = self._directory(snapshot.source, snapshot.dataset, snapshot.partition)
        name = f"{snapshot.fetched_at.strftime(_TIMESTAMP)}_{digest[:_HASH_CHARS]}{_SUFFIX}"
        path = directory / name
        if path.exists():
            raise RawStoreError(f"refusing to overwrite an existing snapshot: {path}")

        envelope = {
            "source": snapshot.source,
            "dataset": snapshot.dataset,
            "partition": dict(snapshot.partition),
            "fetched_at": snapshot.fetched_at.isoformat(),
            "content_hash": digest,
            "request": dict(snapshot.request),
            "payload": snapshot.payload,
        }
        directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        with open(temporary, "wb") as raw:
            # mtime=0 keeps the compressed bytes identical for identical content.
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                compressed.write(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        os.replace(temporary, path)
        return SaveResult(self._describe(path, snapshot.source, snapshot.dataset), created=True)

    def versions(
        self, source: str, dataset: str, partition: Mapping[str, str]
    ) -> list[StoredSnapshot]:
        """Every stored snapshot of one partition, oldest first."""
        directory = self._directory(source, dataset, partition)
        if not directory.is_dir():
            return []
        found = [self._describe(path, source, dataset) for path in directory.glob(f"*{_SUFFIX}")]
        # Ordered by when each was fetched, not by file name: names written to the
        # second and names written to the microsecond do not sort together.
        return sorted(found, key=lambda stored: (stored.fetched_at, stored.path.name))

    def latest_info(
        self, source: str, dataset: str, partition: Mapping[str, str]
    ) -> StoredSnapshot | None:
        versions = self.versions(source, dataset, partition)
        return versions[-1] if versions else None

    def latest(self, source: str, dataset: str, partition: Mapping[str, str]) -> Snapshot | None:
        """The newest snapshot of one partition, or ``None`` if it was never fetched."""
        info = self.latest_info(source, dataset, partition)
        return self.load(info) if info is not None else None

    def partitions(self, source: str, dataset: str) -> list[dict[str, str]]:
        """Every partition of a dataset that has at least one snapshot."""
        base = self.root / source / dataset
        if not base.is_dir():
            return []
        found = {path.parent.relative_to(base).as_posix() for path in base.rglob(f"*{_SUFFIX}")}
        return [_parse_partition(key) for key in sorted(found)]

    def datasets(self) -> list[tuple[str, str]]:
        """``(source, dataset)`` pairs that have at least one snapshot."""
        if not self.root.is_dir():
            return []
        pairs = []
        for source in sorted(path for path in self.root.iterdir() if path.is_dir()):
            for dataset in sorted(path for path in source.iterdir() if path.is_dir()):
                if next(dataset.rglob(f"*{_SUFFIX}"), None) is not None:
                    pairs.append((source.name, dataset.name))
        return pairs

    def load(self, stored: StoredSnapshot) -> Snapshot:
        """Read a snapshot back, checking it still matches where it was filed."""
        try:
            with gzip.open(stored.path, "rb") as compressed:
                envelope = json.loads(compressed.read().decode("utf-8"))
        except (OSError, ValueError) as error:
            raise RawStoreError(f"cannot read snapshot {stored.path}: {error}") from error
        try:
            snapshot = Snapshot(
                source=envelope["source"],
                dataset=envelope["dataset"],
                partition=envelope["partition"],
                fetched_at=datetime.fromisoformat(envelope["fetched_at"]),
                payload=envelope["payload"],
                request=envelope.get("request", {}),
            )
            recorded_hash = envelope["content_hash"]
        except (KeyError, TypeError, ValueError) as error:
            raise RawStoreError(
                f"snapshot {stored.path} has a malformed envelope: {error}"
            ) from error

        filed_as = (stored.source, stored.dataset, stored.partition_key)
        if (snapshot.source, snapshot.dataset, snapshot.partition_key) != filed_as:
            raise RawStoreError(f"snapshot {stored.path} is filed under the wrong partition")
        if snapshot.content_hash != recorded_hash:
            raise RawStoreError(f"snapshot {stored.path} does not match its recorded hash")
        return snapshot

    def _directory(self, source: str, dataset: str, partition: Mapping[str, str]) -> Path:
        return self.root / source / dataset / Path(partition_key(partition))

    def _describe(self, path: Path, source: str, dataset: str) -> StoredSnapshot:
        stem = path.name[: -len(_SUFFIX)]
        try:
            timestamp, hash_prefix = stem.split("_", 1)
            # Chosen by length: parsing a to-the-second name with the microsecond format
            # would quietly read its last digit of seconds as a fraction.
            layout = {22: _TIMESTAMP, 16: _TIMESTAMP_TO_THE_SECOND}[len(timestamp)]
            fetched_at = datetime.strptime(timestamp, layout).replace(tzinfo=UTC)
        except (ValueError, KeyError) as error:
            raise RawStoreError(f"unrecognised snapshot file name: {path}") from error
        relative = path.parent.relative_to(self.root / source / dataset).as_posix()
        return StoredSnapshot(
            path=path,
            source=source,
            dataset=dataset,
            partition=_parse_partition(relative),
            fetched_at=fetched_at,
            hash_prefix=hash_prefix,
        )


def _parse_partition(key: str) -> dict[str, str]:
    if key in (GLOBAL_PARTITION, "."):
        return {}
    partition = {}
    for part in key.split("/"):
        name, separator, value = part.partition("=")
        if not separator:
            raise RawStoreError(f"unrecognised partition directory: {key!r}")
        partition[name] = value
    return partition
