"""Data Health: how fresh the data is, what failed, what is missing, where it came from.

Everything here is read from the lab's own bookkeeping - the fetch log, the build
history and the last build's report - and from what the tables actually hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from front_office.domain.datasets import CONTRACT_FILE, DATASET_SPECS, NBA_STATS, NbaStatsDataset
from front_office.domain.seasons import Season
from front_office.domain.tables import ALL_TABLES
from front_office.services.lab import Lab

OK = "ok"
STALE = "stale"
FAILING = "failing"
ABSENT = "absent"
SOURCE_STATES = (OK, STALE, FAILING, ABSENT)

WARNING = "warning"
INFO = "info"
MOST_SEASONS_LISTED = 5

SOURCE_TITLES = {NBA_STATS: "stats.nba.com", CONTRACT_FILE: "Contract file"}
_DATASET_DESCRIPTIONS = {spec.dataset.value: spec.description for spec in DATASET_SPECS.values()}
_DATASET_DESCRIPTIONS["contracts"] = "Player contracts, from a file supplied by the user."


def utc_now() -> datetime:
    """Now, as naive UTC: the form every stored datetime takes."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """Where one source of data stands."""

    source: str
    title: str
    state: str
    """One of :data:`SOURCE_STATES`."""
    detail: str
    newest_fetch: datetime | None
    slices: int
    """Dataset slices (a dataset for one season, season type or team) held from the source."""
    failing: int
    """Slices whose most recent fetch failed."""


@dataclass(frozen=True, slots=True)
class Gap:
    """Something the lab does not have, and what that costs."""

    area: str
    severity: str
    """``warning`` for something that should be fixed, ``info`` for a known limit."""
    message: str


class HealthService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    # --- sources ------------------------------------------------------------------------

    def sources(self, now: datetime | None = None) -> tuple[SourceStatus, ...]:
        """The state of each source: stats.nba.com and the contract file."""
        moment = now or utc_now()
        snapshots = self._lab.read("raw_snapshots")
        failed = self.failed_fetches()
        return (
            self._stats_source(snapshots, failed, moment),
            self._contract_source(snapshots),
        )

    def _stats_source(
        self, snapshots: pd.DataFrame, failed: pd.DataFrame, now: datetime
    ) -> SourceStatus:
        held = snapshots[snapshots["source"] == NBA_STATS]
        failing = int((failed["source"] == NBA_STATS).sum())
        title = SOURCE_TITLES[NBA_STATS]
        if held.empty:
            detail = "Nothing has been fetched yet. Run: fol refresh"
            return SourceStatus(NBA_STATS, title, ABSENT, detail, None, 0, failing)

        newest = pd.Timestamp(held["fetched_at"].max()).to_pydatetime()
        age = now - newest
        limit = timedelta(hours=self._lab.settings.ingestion.refresh_after_hours)
        if failing:
            state = FAILING
            subject = "slice" if failing == 1 else "slices"
            detail = f"{failing} dataset {subject} failed at the last attempt. Run: fol refresh"
        elif age > limit:
            state = STALE
            detail = (
                f"Newest fetch was {describe_age(age)} ago, older than the "
                f"{limit.total_seconds() / 3600:g}-hour refresh interval. Run: fol refresh"
            )
        else:
            state = OK
            detail = f"Newest fetch was {describe_age(age)} ago."
        return SourceStatus(NBA_STATS, title, state, detail, newest, len(held), failing)

    def _contract_source(self, snapshots: pd.DataFrame) -> SourceStatus:
        held = snapshots[snapshots["source"] == CONTRACT_FILE]
        title = SOURCE_TITLES[CONTRACT_FILE]
        if held.empty or not self._lab.contracts.available:
            detail = (
                "No contract file has been imported, so salaries, payrolls and cap shares "
                "are unavailable. See docs/CONTRACT_DATA.md."
            )
            return SourceStatus(CONTRACT_FILE, title, ABSENT, detail, None, 0, 0)
        newest = pd.Timestamp(held["fetched_at"].max()).to_pydatetime()
        stated = self._lab.contracts.sources().sort_values("as_of_date").iloc[-1]
        detail = (
            f"{stated['contracts']} contracts for {stated['players']} players, current as of "
            f"{stated['as_of_date']:%Y-%m-%d}. Source as stated at import: "
            f"{stated['source_label']}."
        )
        return SourceStatus(CONTRACT_FILE, title, OK, detail, newest, len(held), 0)

    def datasets(self) -> pd.DataFrame:
        """What is held of each dataset: slices, seasons, and its newest and oldest fetch."""
        snapshots = self._lab.read("raw_snapshots")
        columns = ["source", "dataset", "description", "slices", "first_season", "last_season"]
        columns += ["newest_fetch", "oldest_fetch", "failing"]
        if snapshots.empty:
            return pd.DataFrame(columns=columns)
        grouped = snapshots.groupby(["source", "dataset"], as_index=False)
        table = grouped.agg(
            slices=("partition_key", "size"),
            first_season=("season", "min"),
            last_season=("season", "max"),
            newest_fetch=("fetched_at", "max"),
            oldest_fetch=("fetched_at", "min"),
        )
        failed = self.failed_fetches().groupby(["source", "dataset"]).size()
        keys = pd.MultiIndex.from_frame(table[["source", "dataset"]])
        table["failing"] = failed.reindex(keys, fill_value=0).to_numpy()
        table["description"] = table["dataset"].map(_DATASET_DESCRIPTIONS)
        order = {dataset.value: number for number, dataset in enumerate(NbaStatsDataset)}
        table["order"] = table["dataset"].map(order).fillna(len(order))
        table = table.sort_values(["source", "order"], ascending=[False, True])
        return table[columns].reset_index(drop=True)

    # --- fetches and builds ---------------------------------------------------------------

    def failed_fetches(self) -> pd.DataFrame:
        """Dataset slices whose most recent fetch failed, newest failure first."""
        latest = self._lab.operations.latest_fetch_per_dataset()
        failed = latest[latest["status"] == "failed"]
        return failed.sort_values("finished_at", ascending=False).reset_index(drop=True)

    def fetches(self, limit: int = 200) -> pd.DataFrame:
        """The most recent fetch attempts, newest first."""
        return self._lab.operations.fetches(limit=limit)

    def builds(self, limit: int = 20) -> pd.DataFrame:
        """The most recent builds, newest first, with how long each took."""
        builds = self._lab.operations.builds(limit=limit)
        took = builds["finished_at"] - builds["started_at"]
        builds["seconds"] = took.dt.total_seconds()
        return builds

    def issues(self) -> pd.DataFrame:
        """What the last build could not build (errors first) or had to adjust (notes)."""
        issues = self._lab.read("build_issues", order_by=["issue_number"])
        is_note = (issues["severity"] == "note").astype(int)
        ordered = issues.assign(order=is_note).sort_values(["order", "issue_number"])
        return ordered.drop(columns="order").reset_index(drop=True)

    def checks(self) -> pd.DataFrame:
        """Every quality check of the last build: failures first, errors before warnings."""
        checks = self._lab.read("check_results")
        rank = checks["passed"].astype(int) * 2 + (checks["severity"] == "warning").astype(int)
        ordered = checks.assign(order=rank).sort_values(["order", "check_name"])
        return ordered.drop(columns="order").reset_index(drop=True)

    # --- coverage -------------------------------------------------------------------------

    def tables(self) -> pd.DataFrame:
        """Every table: what it is, how many rows it holds, and the seasons it covers."""
        counts = self._lab.warehouse.row_counts()
        rows = []
        for contract in ALL_TABLES:
            if contract.name in counts:
                count = counts[contract.name]
            else:
                count = len(self._lab.read(contract.name))
            seasons: list[str] = []
            if "season" in contract.column_names:
                seasons = self._lab.warehouse.distinct(contract.name, "season")
            rows.append(
                {
                    "table": contract.name,
                    "domain": contract.domain,
                    "rows": count,
                    "first_season": seasons[0] if seasons else None,
                    "last_season": seasons[-1] if seasons else None,
                    "seasons": len(seasons),
                    "description": contract.description,
                }
            )
        return pd.DataFrame(rows)

    def gaps(self, today: date | None = None) -> tuple[Gap, ...]:
        """What the lab does not have, most serious first."""
        status = self._lab.status()
        day = today or utc_now().date()
        gaps: list[Gap] = []

        if not status.is_current:
            gaps.append(
                Gap(
                    "Database",
                    WARNING,
                    "The tables were built by a different version of the lab. Run: fol build",
                )
            )
        build = self._lab.operations.latest_build()
        if build and build["build_errors"]:
            parts = build["build_errors"]
            gaps.append(
                Gap(
                    "Build",
                    WARNING,
                    f"{parts} table part{'s' if parts != 1 else ''} could not be built in the "
                    "last build; the data they would hold is missing. See the build issues.",
                )
            )

        team_seasons = sorted(status.team_seasons)
        holes = _missing_between(team_seasons)
        if holes:
            listed = ", ".join(holes)
            if len(holes) > MOST_SEASONS_LISTED:
                listed = f"{len(holes)} seasons between {holes[0]} and {holes[-1]}"
            gaps.append(Gap("Team statistics", WARNING, f"No team statistics for {listed}."))

        if not status.has_contracts:
            gaps.append(
                Gap(
                    "Contracts",
                    WARNING,
                    "No contract data. Salaries, payrolls and cap shares are empty until a "
                    "contract file is imported: fol contracts template, then fol contracts "
                    "import.",
                )
            )
        else:
            uncapped = [s for s in sorted(status.contract_seasons) if s not in status.cap_seasons]
            if uncapped:
                gaps.append(
                    Gap(
                        "Cap rules",
                        INFO,
                        f"No cap rules are configured for {', '.join(uncapped)}, so salaries "
                        "in those seasons have no cap share.",
                    )
                )

        if team_seasons and not status.player_seasons:
            gaps.append(Gap("Player statistics", WARNING, "No player statistics have been built."))
        elif team_seasons:
            players = sorted(status.player_seasons)
            if players[0] != team_seasons[0]:
                gaps.append(
                    Gap(
                        "Player statistics",
                        INFO,
                        f"Player statistics cover {players[0]} to {players[-1]}; team "
                        f"statistics go back to {team_seasons[0]}. Earlier seasons have team "
                        "data only.",
                    )
                )
            detail = _detail_gap(players, self._lab.warehouse.distinct("player_on_off", "season"))
            if detail is not None:
                gaps.append(detail)

        current = Season.league_year_on(day).label
        if team_seasons and team_seasons[-1] < current:
            gaps.append(
                Gap(
                    "Current season",
                    INFO,
                    f"{current} has no games in the data yet; the newest season with "
                    f"statistics is {team_seasons[-1]}.",
                )
            )
        order = {WARNING: 0, INFO: 1}
        return tuple(sorted(gaps, key=lambda gap: order[gap.severity]))


def _detail_gap(player_seasons: list[str], detail_seasons: list[str]) -> Gap | None:
    """Seasons with player statistics but without the team-by-team detail, if any."""
    if not player_seasons or not detail_seasons:
        return None
    first, last = min(detail_seasons), max(detail_seasons)
    if first == min(player_seasons):
        return None
    return Gap(
        "Player detail",
        INFO,
        f"Rosters and on/off splits cover {first} to {last}. Earlier seasons have player "
        "statistics without them: fetching them takes sixty requests a season.",
    )


def describe_age(age: timedelta) -> str:
    """A span of time in the largest unit that fits: ``3 hours``, ``2 days``."""
    seconds = max(age.total_seconds(), 0)
    for size, unit in ((86_400, "day"), (3_600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return "less than a minute"


def _missing_between(seasons: list[str]) -> list[str]:
    """Seasons absent from an ascending run of season labels."""
    if not seasons:
        return []
    present = set(seasons)
    first, last = Season.parse(seasons[0]), Season.parse(seasons[-1])
    expected = [Season(year).label for year in range(first.start_year, last.start_year + 1)]
    return [label for label in expected if label not in present]
