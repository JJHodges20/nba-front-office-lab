"""Fetch raw datasets from stats.nba.com into the raw store.

This module decides *what* to fetch and *whether it is due*; the provider does the
fetching and the raw store does the keeping. One failed request never stops a run: it is
recorded and the run carries on, so a flaky endpoint costs one dataset, not a season.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from front_office.config.settings import Settings
from front_office.domain.datasets import NBA_STATS, NbaStatsDataset, partition_for
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot, partition_key
from front_office.processing.nba_stats.resultsets import PayloadError, row_count, standings_team_ids
from front_office.providers.nba_stats import NbaStatsProvider, ProviderError
from front_office.rawstore import RawStore, RawStoreError, StoredSnapshot

FIRST_PLAY_IN_SEASON = Season(2019)
"""The play-in began with a single game in the 2019-20 bubble; none exist before it."""

D = NbaStatsDataset


class SnapshotProvider(Protocol):
    def fetch(
        self,
        dataset: NbaStatsDataset,
        *,
        season: Season | None = None,
        season_type: SeasonType | None = None,
        team_id: int | None = None,
        reference_season: Season | None = None,
    ) -> Snapshot: ...


@dataclass(frozen=True, slots=True)
class FetchRequest:
    dataset: NbaStatsDataset
    season: Season | None = None
    season_type: SeasonType | None = None
    team_id: int | None = None
    reference_season: Season | None = None

    @property
    def partition(self) -> dict[str, str]:
        return partition_for(
            self.dataset, season=self.season, season_type=self.season_type, team_id=self.team_id
        )

    @property
    def partition_key(self) -> str:
        return partition_key(self.partition)

    def describe(self) -> str:
        return f"{self.dataset.value}/{self.partition_key}"


class FetchStatus(StrEnum):
    STORED = "stored"
    """New data was fetched and saved."""
    UNCHANGED = "unchanged"
    """Fetched, but identical to the newest stored snapshot."""
    SKIPPED = "skipped"
    """Not fetched: the stored snapshot is still current."""
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    request: FetchRequest
    status: FetchStatus
    started_at: datetime
    finished_at: datetime
    rows: int | None = None
    stored: StoredSnapshot | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Decides whether a stored snapshot is still good enough."""

    refresh_after: timedelta
    force: bool = False

    def is_due(self, request: FetchRequest, newest: StoredSnapshot | None, now: datetime) -> bool:
        if self.force or newest is None:
            return True
        if request.season is not None and _season_was_over(request.season, newest.fetched_at):
            # Fetched after the season's league year closed: the data is final.
            return False
        return now - newest.fetched_at >= self.refresh_after


def _season_was_over(season: Season, moment: datetime) -> bool:
    return Season.league_year_on(moment.date()) > season


def global_requests(current: Season) -> list[FetchRequest]:
    """Datasets that are not split by season."""
    return [
        FetchRequest(D.TEAM_YEARS),
        FetchRequest(D.PLAYER_INDEX, reference_season=current),
    ]


def league_requests(season: Season, *, players: bool) -> list[FetchRequest]:
    """League-wide datasets for one season: a single request covers every team or player."""
    regular, playoffs, play_in = SeasonType.REGULAR, SeasonType.PLAYOFFS, SeasonType.PLAY_IN
    requests = [
        FetchRequest(D.STANDINGS, season),
        FetchRequest(D.TEAM_SEASON_BASE, season, regular),
        FetchRequest(D.TEAM_SEASON_ADVANCED, season, regular),
        FetchRequest(D.TEAM_SEASON_OPPONENT, season, regular),
        FetchRequest(D.TEAM_GAME_LOGS, season, regular),
        FetchRequest(D.TEAM_GAME_LOGS, season, playoffs),
    ]
    if season >= FIRST_PLAY_IN_SEASON:
        requests.append(FetchRequest(D.TEAM_GAME_LOGS, season, play_in))
    if players:
        for season_type in (regular, playoffs):
            requests += [
                FetchRequest(D.PLAYER_SEASON_BASE, season, season_type),
                FetchRequest(D.PLAYER_SEASON_ADVANCED, season, season_type),
                FetchRequest(D.PLAYER_SEASON_STARTERS, season, season_type),
                FetchRequest(D.PLAYER_GAME_LOGS, season, season_type),
            ]
    return requests


def team_requests(season: Season, team_ids: Iterable[int], *, on_off: bool) -> list[FetchRequest]:
    """Per-team datasets for one season: one request per team."""
    requests = []
    for team_id in team_ids:
        requests.append(FetchRequest(D.TEAM_ROSTER, season, team_id=team_id))
        if on_off:
            requests.append(FetchRequest(D.TEAM_ON_OFF, season, SeasonType.REGULAR, team_id))
    return requests


@dataclass(frozen=True, slots=True)
class IngestPlan:
    """Which seasons to fetch, and which of them at player level."""

    current: Season
    seasons: tuple[Season, ...]
    player_detail: frozenset[Season]


def default_plan(settings: Settings, today: date) -> IngestPlan:
    """Team history from the configured start; player detail for the most recent seasons."""
    current = Season.league_year_on(today)
    detail_from = max(
        current.offset(-settings.seasons.player_detail_seasons), settings.history_start
    )
    return IngestPlan(
        current=current,
        seasons=tuple(Season.span(settings.history_start, current)),
        player_detail=frozenset(Season.span(detail_from, current)),
    )


class Ingestor:
    """Runs fetch requests against a provider and files the results in the raw store."""

    def __init__(
        self,
        provider: SnapshotProvider,
        store: RawStore,
        policy: RefreshPolicy,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        on_outcome: Callable[[FetchOutcome], None] | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._policy = policy
        self._now = now
        self._on_outcome = on_outcome

    def run(self, requests: Iterable[FetchRequest]) -> list[FetchOutcome]:
        return [self._fetch(request) for request in requests]

    def ingest_globals(self, current: Season) -> list[FetchOutcome]:
        return self.run(global_requests(current))

    def ingest_season(self, season: Season, *, players: bool) -> list[FetchOutcome]:
        """Fetch one season: league-wide datasets first, then per-team ones if wanted."""
        outcomes = self.run(league_requests(season, players=players))
        if not players:
            return outcomes

        standings = self._store.latest(NBA_STATS, D.STANDINGS.value, {"season": season.label})
        if standings is None:
            # The standings request failed and nothing is stored: without team ids there
            # is nothing to ask for. The failure is already among the outcomes.
            return outcomes
        team_base = self._store.latest(
            NBA_STATS,
            D.TEAM_SEASON_BASE.value,
            partition_for(D.TEAM_SEASON_BASE, season=season, season_type=SeasonType.REGULAR),
        )
        # On/off splits only exist once games have been played.
        has_games = team_base is not None and row_count(team_base) > 0
        try:
            team_ids = standings_team_ids(standings)
        except PayloadError as error:
            unusable = FetchRequest(D.STANDINGS, season)
            failure = self._finish(unusable, FetchStatus.FAILED, self._now(), error=str(error))
            return [*outcomes, failure]
        return outcomes + self.run(team_requests(season, team_ids, on_off=has_games))

    def _fetch(self, request: FetchRequest) -> FetchOutcome:
        started = self._now()
        newest = self._store.latest_info(NBA_STATS, request.dataset.value, request.partition)
        if not self._policy.is_due(request, newest, started):
            return self._finish(request, FetchStatus.SKIPPED, started, stored=newest)
        try:
            snapshot = self._provider.fetch(
                request.dataset,
                season=request.season,
                season_type=request.season_type,
                team_id=request.team_id,
                reference_season=request.reference_season,
            )
            rows = row_count(snapshot)
            saved = self._store.save(snapshot)
        except (ProviderError, PayloadError, RawStoreError) as error:
            return self._finish(request, FetchStatus.FAILED, started, error=str(error))
        status = FetchStatus.STORED if saved.created else FetchStatus.UNCHANGED
        return self._finish(request, status, started, rows=rows, stored=saved.stored)

    def _finish(
        self,
        request: FetchRequest,
        status: FetchStatus,
        started: datetime,
        *,
        rows: int | None = None,
        stored: StoredSnapshot | None = None,
        error: str | None = None,
    ) -> FetchOutcome:
        outcome = FetchOutcome(request, status, started, self._now(), rows, stored, error)
        if self._on_outcome is not None:
            self._on_outcome(outcome)
        return outcome


def build_ingestor(
    settings: Settings,
    *,
    force: bool = False,
    on_outcome: Callable[[FetchOutcome], None] | None = None,
) -> Ingestor:
    """An ingestor wired to stats.nba.com and the project's raw store."""
    nba = settings.providers.nba_stats
    provider = NbaStatsProvider(
        timeout=nba.timeout_seconds,
        min_interval=nba.min_interval_seconds,
        max_retries=nba.max_retries,
        backoff=nba.backoff_seconds,
    )
    policy = RefreshPolicy(
        refresh_after=timedelta(hours=settings.ingestion.refresh_after_hours), force=force
    )
    return Ingestor(provider, RawStore(settings.raw_dir), policy, on_outcome=on_outcome)
