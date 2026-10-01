"""Summarise what the raw store holds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from front_office.config.settings import Settings
from front_office.rawstore import RawStore


@dataclass(frozen=True, slots=True)
class RawDatasetStatus:
    source: str
    dataset: str
    partitions: int
    snapshots: int
    first_season: str | None
    last_season: str | None
    newest_fetch: datetime


def raw_inventory(settings: Settings) -> list[RawDatasetStatus]:
    """One entry per stored dataset, in source and dataset order."""
    return store_inventory(RawStore(settings.raw_dir))


def store_inventory(store: RawStore) -> list[RawDatasetStatus]:
    inventory = []
    for source, dataset in store.datasets():
        partitions = store.partitions(source, dataset)
        versions = [
            version
            for partition in partitions
            for version in store.versions(source, dataset, partition)
        ]
        seasons = sorted({partition["season"] for partition in partitions if "season" in partition})
        inventory.append(
            RawDatasetStatus(
                source=source,
                dataset=dataset,
                partitions=len(partitions),
                snapshots=len(versions),
                first_season=seasons[0] if seasons else None,
                last_season=seasons[-1] if seasons else None,
                newest_fetch=max(version.fetched_at for version in versions),
            )
        )
    return inventory
