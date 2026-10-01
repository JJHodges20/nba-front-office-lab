"""Builders shared by tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from front_office.domain.datasets import NBA_STATS, NbaStatsDataset, partition_for
from front_office.domain.snapshots import Snapshot
from front_office.providers.nba_stats import ProviderError

FETCHED_AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
TEAMS = [1610612738, 1610612752]
D = NbaStatsDataset


def stats_payload(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    name: str = "ResultSet",
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A payload shaped like a stats.nba.com response with one result set."""
    return {
        "resource": "test",
        "parameters": dict(parameters or {}),
        "resultSets": [{"name": name, "headers": list(headers), "rowSet": [list(r) for r in rows]}],
    }


def snapshot(
    dataset: str,
    payload: Mapping[str, Any],
    partition: Mapping[str, str] | None = None,
    *,
    fetched_at: datetime = FETCHED_AT,
    source: str = NBA_STATS,
) -> Snapshot:
    return Snapshot(
        source=source,
        dataset=dataset,
        partition=dict(partition or {}),
        fetched_at=fetched_at,
        payload=payload,
        request={"endpoint": "Test", "parameters": {}},
    )


class FakeProvider:
    """Serves canned payloads and records what was asked for."""

    def __init__(self, *, clock: Clock, games_played: bool = True) -> None:
        self.clock = clock
        self.games_played = games_played
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.fail: set[NbaStatsDataset] = set()
        self.revision = 0

    def fetch(self, dataset, *, season=None, season_type=None, team_id=None, reference_season=None):
        partition = partition_for(dataset, season=season, season_type=season_type, team_id=team_id)
        self.calls.append((dataset.value, partition))
        if dataset in self.fail:
            raise ProviderError(f"{dataset.value} is down")
        if dataset is D.STANDINGS:
            payload = stats_payload(["TeamID"], [[team] for team in TEAMS])
        elif dataset is D.TEAM_SEASON_BASE and not self.games_played:
            payload = stats_payload(["TEAM_ID", "GP"], [])
        else:
            payload = stats_payload(["TEAM_ID", "GP"], [[TEAMS[0], 82 + self.revision]])
        return Snapshot(NBA_STATS, dataset.value, partition, self.clock.now(), payload)


class Clock:
    def __init__(self, start: datetime) -> None:
        self.moment = start

    def now(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)
