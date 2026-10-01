"""Rebuild the normalised tables from the raw store.

Normalisation is a pure replay: the same raw snapshots always produce the same tables,
so the database can be thrown away and rebuilt at any time.

A dataset that cannot be normalised - missing from the store, malformed, or failing its
data contract - does not stop the build. It is recorded as a :class:`BuildIssue`, the
table simply lacks that season, and the caller decides how loudly to complain.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from front_office.domain.cap_rules import SeasonRules
from front_office.domain.datasets import (
    CONTRACT_FILE,
    CONTRACT_FILE_DATASET,
    NBA_STATS,
    NbaStatsDataset,
    partition_for,
)
from front_office.domain.schema import ContractViolationError, TableContract
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.snapshots import Snapshot
from front_office.domain.tables import finance as finance_tables
from front_office.domain.tables import players as player_tables
from front_office.domain.tables import teams as team_tables
from front_office.processing.cap_rules import cap_rules_frame
from front_office.processing.contracts import (
    ContractFileError,
    build_contracts,
    describe_unmatched,
)
from front_office.processing.nba_stats import players, playoffs, teams
from front_office.processing.nba_stats.resultsets import PayloadError
from front_office.rawstore import RawStore, RawStoreError

D = NbaStatsDataset
REGULAR, PLAYOFFS, PLAY_IN = SeasonType.REGULAR, SeasonType.PLAYOFFS, SeasonType.PLAY_IN
ALL_SEASONS = "all seasons"

_BUILD_ERRORS = (
    PayloadError,
    playoffs.BracketError,
    ContractViolationError,
    RawStoreError,
    ContractFileError,
)

NBA_STATS_TABLES: tuple[TableContract, ...] = (
    team_tables.TEAMS,
    team_tables.TEAM_SEASONS,
    team_tables.TEAM_GAMES,
    team_tables.PLAYOFF_RESULTS,
    player_tables.PLAYERS,
    player_tables.PLAYER_SEASONS,
    player_tables.PLAYER_GAME_LOGS,
    player_tables.TEAM_ROSTERS,
    player_tables.PLAYER_ON_OFF,
)
FINANCE_TABLES: tuple[TableContract, ...] = (
    finance_tables.SALARY_CAP_RULES,
    finance_tables.CONTRACTS,
    finance_tables.CONTRACT_YEARS,
)
BUILT_TABLES: tuple[TableContract, ...] = (*NBA_STATS_TABLES, *FINANCE_TABLES)
"""Every table normalisation produces, in an order where references come first."""


class IssueSeverity(StrEnum):
    ERROR = "error"
    """Part of a table could not be built; that data is missing."""
    NOTE = "note"
    """The table was built, but the source needed an adjustment worth knowing about."""


@dataclass(frozen=True, slots=True)
class BuildIssue:
    """Something a reader of the data should know about how a table was built."""

    scope: str
    """The season the issue belongs to, or ``"all seasons"``."""
    table: str
    message: str
    severity: IssueSeverity = IssueSeverity.ERROR

    def __str__(self) -> str:
        return f"{self.severity.value}: {self.table} [{self.scope}]: {self.message}"


@dataclass(slots=True)
class NormalizedTables:
    frames: dict[str, pd.DataFrame]
    issues: list[BuildIssue] = field(default_factory=list)

    def __getitem__(self, table: str) -> pd.DataFrame:
        return self.frames[table]

    @property
    def errors(self) -> list[BuildIssue]:
        return [issue for issue in self.issues if issue.severity is IssueSeverity.ERROR]

    @property
    def notes(self) -> list[BuildIssue]:
        return [issue for issue in self.issues if issue.severity is IssueSeverity.NOTE]


class _Missing(Exception):
    """A required raw dataset has not been fetched."""


class _Builder:
    def __init__(self, store: RawStore) -> None:
        self.store = store
        self.parts: dict[str, list[pd.DataFrame]] = {t.name: [] for t in NBA_STATS_TABLES}
        self.issues: list[BuildIssue] = []

    def snapshot(
        self,
        dataset: NbaStatsDataset,
        season: Season | None = None,
        season_type: SeasonType | None = None,
        team_id: int | None = None,
    ) -> Snapshot | None:
        partition = partition_for(dataset, season=season, season_type=season_type, team_id=team_id)
        return self.store.latest(NBA_STATS, dataset.value, partition)

    def require(
        self,
        dataset: NbaStatsDataset,
        season: Season | None = None,
        season_type: SeasonType | None = None,
    ) -> Snapshot:
        found = self.snapshot(dataset, season, season_type)
        if found is None:
            wanted = partition_for(dataset, season=season, season_type=season_type)
            where = "/".join(wanted.values()) or ALL_SEASONS
            raise _Missing(f"raw dataset {dataset.value} ({where}) has not been fetched")
        return found

    def team_snapshots(
        self, dataset: NbaStatsDataset, season: Season, season_type: SeasonType | None = None
    ) -> list[Snapshot]:
        """Every per-team snapshot of a dataset for one season."""
        found = []
        for partition in self.store.partitions(NBA_STATS, dataset.value):
            if partition.get("season") != season.label:
                continue
            if season_type is not None and partition.get("season_type") != season_type.value:
                continue
            snapshot = self.store.latest(NBA_STATS, dataset.value, partition)
            if snapshot is not None:
                found.append(snapshot)
        return found

    def attempt(
        self, table: str, scope: str, build: Callable[[list[str]], pd.DataFrame]
    ) -> pd.DataFrame | None:
        """Run one build step; on failure record an issue and return ``None``.

        The step receives a list to which it may add notes about adjustments it made.
        """
        notes: list[str] = []
        try:
            frame = build(notes)
        except (_Missing, *_BUILD_ERRORS) as error:
            self.issues.append(BuildIssue(scope, table, str(error)))
            return None
        self.issues += [BuildIssue(scope, table, note, IssueSeverity.NOTE) for note in notes]
        self.parts[table].append(frame)
        return frame

    def skip(self, table: str, scope: str, because: str) -> None:
        self.issues.append(BuildIssue(scope, table, f"not built: {because}"))


def stored_seasons(store: RawStore) -> list[Season]:
    """Seasons with standings in the raw store, oldest first."""
    partitions = store.partitions(NBA_STATS, D.STANDINGS.value)
    return sorted(Season.parse(partition["season"]) for partition in partitions)


def normalize(
    store: RawStore,
    seasons: Sequence[Season] | None = None,
    season_rules: Sequence[SeasonRules] = (),
) -> NormalizedTables:
    """Build every table from the newest snapshots in the raw store.

    ``season_rules`` are the configured cap rules; they become ``salary_cap_rules`` and
    supply the cap that each contract season's salary is measured against.
    """
    builder = _Builder(store)
    chosen = sorted(seasons) if seasons is not None else stored_seasons(store)

    if chosen:
        newest = chosen[-1]
        builder.attempt(
            "teams",
            ALL_SEASONS,
            lambda notes: teams.build_teams(
                builder.require(D.TEAM_YEARS), builder.require(D.STANDINGS, newest)
            ),
        )
    for season in chosen:
        _normalize_season(builder, season)

    roster_snapshots = [
        snapshot for season in chosen for snapshot in builder.team_snapshots(D.TEAM_ROSTER, season)
    ]
    builder.attempt(
        "players",
        ALL_SEASONS,
        lambda notes: players.build_players(builder.require(D.PLAYER_INDEX), roster_snapshots),
    )

    frames = {}
    for contract in NBA_STATS_TABLES:
        parts = [part for part in builder.parts[contract.name] if not part.empty]
        frames[contract.name] = (
            pd.concat(parts, ignore_index=True) if parts else contract.empty_frame()
        )
    frames.update(_finance_tables(builder, frames, season_rules))
    return NormalizedTables(frames, builder.issues)


def reference_tables(store: RawStore) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(teams, players)`` alone: what a contract file is matched against.

    Raises ``LookupError`` if league data has not been ingested yet.
    """
    seasons = stored_seasons(store)
    builder = _Builder(store)
    try:
        if not seasons:
            raise _Missing("no league data has been ingested")
        team_frame = teams.build_teams(
            builder.require(D.TEAM_YEARS), builder.require(D.STANDINGS, seasons[-1])
        )
        player_frame = players.build_players(builder.require(D.PLAYER_INDEX))
    except _Missing as error:
        raise LookupError(f"{error}; run: fol ingest") from error
    return team_frame, player_frame


def _finance_tables(
    builder: _Builder, frames: dict[str, pd.DataFrame], season_rules: Sequence[SeasonRules]
) -> dict[str, pd.DataFrame]:
    built = {
        "salary_cap_rules": cap_rules_frame(season_rules),
        "contracts": finance_tables.CONTRACTS.empty_frame(),
        "contract_years": finance_tables.CONTRACT_YEARS.empty_frame(),
    }
    try:
        snapshot = builder.store.latest(CONTRACT_FILE, CONTRACT_FILE_DATASET, {})
    except RawStoreError as error:
        builder.issues.append(BuildIssue(ALL_SEASONS, "contracts", str(error)))
        return built
    if snapshot is None:
        builder.issues.append(
            BuildIssue(
                ALL_SEASONS,
                "contracts",
                "no contract file has been imported; salaries and payroll are unavailable",
                IssueSeverity.NOTE,
            )
        )
        return built
    try:
        result = build_contracts(
            snapshot,
            players=frames["players"],
            teams=frames["teams"],
            caps={rules.season: rules.salary_cap for rules in season_rules},
        )
    except _BUILD_ERRORS as error:
        builder.issues.append(BuildIssue(ALL_SEASONS, "contracts", str(error)))
        return built
    left_out = describe_unmatched(result.unmatched)
    if left_out:
        builder.issues.append(BuildIssue(ALL_SEASONS, "contracts", left_out, IssueSeverity.NOTE))
    built["contracts"] = result.contracts
    built["contract_years"] = result.contract_years
    return built


def _normalize_season(builder: _Builder, season: Season) -> None:
    scope = season.label
    team_games = builder.attempt(
        "team_games", scope, lambda notes: _team_games(builder, season, notes)
    )
    if team_games is None:
        for table in ("playoff_results", "team_seasons"):
            builder.skip(table, scope, "team_games could not be built")
    else:
        series = builder.attempt(
            "playoff_results",
            scope,
            lambda notes: playoffs.build_playoff_results(season, team_games),
        )
        if series is None:
            builder.skip("team_seasons", scope, "playoff_results could not be built")
        else:
            builder.attempt(
                "team_seasons",
                scope,
                lambda notes: _team_seasons(builder, season, team_games, series, notes),
            )
    _normalize_player_detail(builder, season, team_games)


def _team_games(builder: _Builder, season: Season, notes: list[str]) -> pd.DataFrame:
    snapshots = [
        builder.require(D.TEAM_GAME_LOGS, season, REGULAR),
        builder.require(D.TEAM_GAME_LOGS, season, PLAYOFFS),
    ]
    # Play-in games exist only from 2019-20; older seasons simply have no such dataset.
    play_in = builder.snapshot(D.TEAM_GAME_LOGS, season, PLAY_IN)
    if play_in is not None:
        snapshots.append(play_in)
    return teams.build_team_games(snapshots, notes)


def _team_seasons(
    builder: _Builder,
    season: Season,
    team_games: pd.DataFrame,
    series: pd.DataFrame,
    notes: list[str],
) -> pd.DataFrame:
    regular = team_games[team_games["season_type"] == REGULAR.value]
    play_in = team_games[team_games["season_type"] == PLAY_IN.value]
    outcomes = playoffs.postseason_outcomes(
        series, regular["team_id"].unique(), play_in["team_id"].unique()
    )
    return teams.build_team_seasons(
        base=builder.require(D.TEAM_SEASON_BASE, season, REGULAR),
        advanced=builder.require(D.TEAM_SEASON_ADVANCED, season, REGULAR),
        opponent=builder.require(D.TEAM_SEASON_OPPONENT, season, REGULAR),
        standings=builder.require(D.STANDINGS, season),
        regular_season_logs=builder.require(D.TEAM_GAME_LOGS, season, REGULAR),
        outcomes=outcomes,
        notes=notes,
    )


def _normalize_player_detail(
    builder: _Builder, season: Season, team_games: pd.DataFrame | None
) -> None:
    """Player-level tables, for seasons whose player datasets were fetched."""
    scope = season.label
    for season_type in (REGULAR, PLAYOFFS):
        base = builder.snapshot(D.PLAYER_SEASON_BASE, season, season_type)
        if base is not None:
            builder.attempt(
                "player_seasons",
                scope,
                lambda notes, base=base, season_type=season_type: players.build_player_seasons(
                    base=base,
                    advanced=builder.require(D.PLAYER_SEASON_ADVANCED, season, season_type),
                    starters=builder.snapshot(D.PLAYER_SEASON_STARTERS, season, season_type),
                ),
            )
        logs = builder.snapshot(D.PLAYER_GAME_LOGS, season, season_type)
        if logs is None:
            continue
        if team_games is None:
            builder.skip("player_game_logs", scope, "team_games could not be built")
        else:
            builder.attempt(
                "player_game_logs",
                scope,
                lambda notes, logs=logs: players.build_player_game_logs(logs, team_games),
            )

    rosters = builder.team_snapshots(D.TEAM_ROSTER, season)
    if rosters:
        builder.attempt("team_rosters", scope, lambda notes: players.build_team_rosters(rosters))
    on_off = builder.team_snapshots(D.TEAM_ON_OFF, season, REGULAR)
    if on_off:
        builder.attempt("player_on_off", scope, lambda notes: players.build_player_on_off(on_off))
