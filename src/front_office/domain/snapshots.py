"""Raw snapshots: what a provider returned for one request.

A snapshot is the unit that moves from a provider, through the raw store, into
processing. It keeps the payload exactly as received together with enough context -
source, dataset, partition, fetch time, the request that produced it - to trace any
stored number back to the response it came from.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_PARTITION_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

GLOBAL_PARTITION = "_all"
"""Directory name for a dataset that is not split by season or team."""


def partition_key(partition: Mapping[str, str]) -> str:
    """Stable path fragment for a partition, e.g. ``season=2025-26/season_type=regular``.

    Keys keep the order they were given in, so a dataset's directories nest the same way
    every time.
    """
    if not partition:
        return GLOBAL_PARTITION
    return "/".join(f"{key}={value}" for key, value in partition.items())


def content_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 of the payload's canonical JSON; equal payloads always hash equally."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One provider response, unchanged, with its provenance."""

    source: str
    dataset: str
    partition: Mapping[str, str]
    fetched_at: datetime
    payload: Mapping[str, Any]
    request: Mapping[str, Any] = field(default_factory=dict)
    """The endpoint and parameters that produced the payload."""

    def __post_init__(self) -> None:
        for label, value in (("source", self.source), ("dataset", self.dataset)):
            if not _NAME.match(value):
                raise ValueError(f"snapshot {label} must be a lowercase identifier: {value!r}")
        for key, value in self.partition.items():
            if not _NAME.match(key):
                raise ValueError(f"partition key must be a lowercase identifier: {key!r}")
            if not isinstance(value, str) or not _PARTITION_VALUE.match(value):
                raise ValueError(f"partition value for {key!r} is not path-safe text: {value!r}")
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        object.__setattr__(self, "fetched_at", self.fetched_at.astimezone(UTC))

    @property
    def partition_key(self) -> str:
        return partition_key(self.partition)

    @property
    def content_hash(self) -> str:
        return content_hash(self.payload)

    def describe(self) -> str:
        return f"{self.source}/{self.dataset}/{self.partition_key}"
