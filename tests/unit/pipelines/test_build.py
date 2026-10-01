"""Building the database from a private copy of the fixture raw store."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from front_office import __version__
from front_office.config import Settings
from front_office.domain.datasets import NbaStatsDataset
from front_office.domain.schema import validate_frame
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables import LEAGUE_TABLES
from front_office.domain.tables.operations import BUILD_ISSUES, CHECK_RESULTS, RAW_SNAPSHOTS
from front_office.pipelines.build import (
    build_database,
    checks_frame,
    database_status,
    issues_frame,
    log_fetches,
    snapshots_frame,
)
from front_office.pipelines.ingest import FetchOutcome, FetchRequest, FetchStatus
from front_office.pipelines.normalize import BuildIssue, IssueSeverity
from front_office.quality import CheckResult, Severity
from front_office.rawstore import RawStore
from front_office.storage import Database, OperationsLog, RosterRepository, Warehouse
from tests.conftest import BUILD_TOOK, BUILT_AT, FIXTURE_RAW

D = NbaStatsDataset


@pytest.fixture
def lab(settings: Settings) -> Settings:
    """A throwaway project whose raw store is a copy of the fixture store."""
    shutil.copytree(FIXTURE_RAW, settings.raw_dir)
    return settings


def read(settings: Settings, table: str, where: dict | None = None) -> pd.DataFrame:
    with Database(settings.database_path) as database:
        return Warehouse(database).read(table, where)


class TestBuild:
    def test_loads_every_league_table_from_the_raw_store(
        self, built_readonly: Settings, first_build_report, normalized
    ) -> None:
        report = first_build_report
        assert report.loaded and report.build_id == 1
        assert report.refused_because is None
        with Database(built_readonly.database_path) as database:
            counts = Warehouse(database).row_counts()
        for contract in LEAGUE_TABLES:
            assert counts[contract.name] == len(normalized[contract.name]), contract.name
        assert report.rows_loaded == sum(counts.values())

    def test_the_build_report_is_stored_with_the_data(
        self, built_readonly: Settings, first_build_report
    ) -> None:
        lab, report = built_readonly, first_build_report
        issues = read(lab, "build_issues")
        assert validate_frame(issues, BUILD_ISSUES) == []
        assert issues["issue_number"].tolist() == [1, 2, 3]
        assert issues["severity"].tolist() == ["note", "note", "note"]
        assert issues["table_name"].tolist() == ["team_seasons", "team_games", "contracts"]

        checks = read(lab, "check_results")
        assert validate_frame(checks, CHECK_RESULTS) == []
        assert len(checks) == len(report.data.checks)
        failed = checks[~checks["passed"]].set_index("check_name")
        assert failed.loc["team_games.points_add_up", "failures"] == 2
        assert "game_id=0029600070" in failed.loc["team_games.points_add_up", "examples"]
        assert checks[checks["passed"]]["examples"].isna().all()

    def test_the_newest_snapshot_of_every_slice_is_recorded(self, built_readonly: Settings) -> None:
        snapshots = read(built_readonly, "raw_snapshots")
        assert validate_frame(snapshots, RAW_SNAPSHOTS) == []
        assert len(snapshots) == 42
        assert (snapshots["versions"] == 1).all()
        logs = snapshots[snapshots["dataset"] == "team_game_logs"]
        assert set(logs["season"]) == {"1996-97", "2012-13", "2025-26", "2026-27"}
        assert snapshots.loc[snapshots["dataset"] == "team_years", "season"].isna().all()

    def test_each_build_is_recorded_in_the_history(self, built_lab: Settings) -> None:
        lab = built_lab
        build_database(lab)
        with Database(lab.database_path) as database:
            builds = OperationsLog(database).builds()
        assert builds["build_id"].tolist() == [2, 1]
        first = builds.iloc[1]
        assert first["started_at"] == pd.Timestamp(BUILT_AT)
        assert first["finished_at"] == pd.Timestamp(BUILT_AT + BUILD_TOOK)
        assert builds.iloc[0]["started_at"] > first["finished_at"]
        assert first["lab_version"] == __version__
        assert (first["build_errors"], first["build_notes"]) == (0, 3)
        # The fixture holds player logs for two teams only, so two checks fail on it.
        assert (first["check_errors"], first["check_warnings"]) == (2, 2)
        assert first["status"] == "problems"

    def test_a_build_with_problems_still_loads_and_says_so(
        self, built_readonly: Settings, first_build_report
    ) -> None:
        assert first_build_report.loaded
        assert not first_build_report.ok
        assert len(read(built_readonly, "teams")) == 30

    def test_a_missing_dataset_is_recorded_as_a_build_error(self, lab: Settings) -> None:
        shutil.rmtree(lab.raw_dir / "nba_stats" / "team_season_advanced" / "season=2012-13")
        report = build_database(lab)
        assert report.loaded
        issues = read(lab, "build_issues", {"severity": "error"})
        assert issues["table_name"].tolist() == ["team_seasons"]
        assert issues["scope"].tolist() == ["2012-13"]
        assert set(read(lab, "team_seasons")["season"]) == {"1996-97", "2025-26"}
        with Database(lab.database_path) as database:
            assert OperationsLog(database).latest_build()["build_errors"] == 1

    def test_imported_contracts_are_loaded(self, lab: Settings, tmp_path) -> None:
        from datetime import date

        from front_office.pipelines.contracts import import_contract_file

        path = tmp_path / "contracts.csv"
        path.write_text("player,team,2026-27\nJayson Tatum,BOS,40000000\n", encoding="utf-8")
        import_contract_file(lab, path, source_label="invented", as_of=date(2026, 10, 1))
        build_database(lab)
        years = read(lab, "contract_years")
        assert years["salary"].tolist() == [40_000_000]
        assert len(read(lab, "salary_cap_rules")) == 3


class TestRefusal:
    def test_a_build_that_would_empty_a_table_is_refused(self, built_lab: Settings) -> None:
        lab = built_lab
        shutil.rmtree(lab.raw_dir / "nba_stats" / "player_index")
        report = build_database(lab)
        assert not report.loaded
        assert not report.ok
        assert "would empty players" in report.refused_because
        assert "--force" in report.refused_because
        assert len(read(lab, "players")) > 0
        with Database(lab.database_path) as database:
            assert len(OperationsLog(database).builds()) == 1

    def test_force_loads_anyway(self, built_lab: Settings) -> None:
        lab = built_lab
        shutil.rmtree(lab.raw_dir / "nba_stats" / "player_index")
        report = build_database(lab, force=True)
        assert report.loaded
        assert len(read(lab, "players")) == 0

    def test_a_first_build_is_never_refused(self, settings: Settings) -> None:
        report = build_database(settings)  # an empty raw store
        assert report.loaded
        assert read(settings, "teams").empty

    def test_an_empty_table_staying_empty_is_fine(self, built_lab: Settings) -> None:
        assert read(built_lab, "contracts").empty
        assert build_database(built_lab).loaded


class TestKeptData:
    def test_rosters_survive_a_rebuild(self, built_lab: Settings) -> None:
        lab = built_lab
        with Database(lab.database_path) as database:
            rosters = RosterRepository(database)
            roster_id = rosters.create("Mine", stats_season="2025-26", payroll_season="2026-27")
            rosters.set_player(roster_id, 1628369, slot="SF", assumed_salary=40_000_000)
        build_database(lab)
        with Database(lab.database_path) as database:
            rosters = RosterRepository(database)
            assert rosters.get(roster_id)["name"] == "Mine"
            assert rosters.players(roster_id)["assumed_salary"].tolist() == [40_000_000]


class TestStatus:
    def test_before_any_database_exists(self, settings: Settings) -> None:
        status = database_status(settings)
        assert not status.exists
        assert not settings.database_path.exists()  # asking must not create it

    def test_after_a_build(self, built_readonly: Settings) -> None:
        status = database_status(built_readonly)
        assert status.exists and status.is_current
        assert status.row_counts["teams"] == 30
        assert status.latest_build["build_id"] == 1

    def test_a_database_with_no_build_yet(self, settings: Settings) -> None:
        with Database(settings.database_path):
            pass
        status = database_status(settings)
        assert status.exists and not status.is_current
        assert status.row_counts == {}
        assert status.latest_build is None


class TestReportFrames:
    def test_issues_are_numbered_in_order(self) -> None:
        issues = [
            BuildIssue("2012-13", "team_games", "one game left out", IssueSeverity.NOTE),
            BuildIssue("all seasons", "players", "missing"),
        ]
        frame = issues_frame(issues)
        assert frame["issue_number"].tolist() == [1, 2]
        assert frame["severity"].tolist() == ["note", "error"]
        assert frame["scope"].tolist() == ["2012-13", "all seasons"]

    def test_no_issues_gives_an_empty_conforming_frame(self) -> None:
        frame = issues_frame([])
        assert len(frame) == 0
        assert tuple(frame.columns) == BUILD_ISSUES.column_names

    def test_check_examples_are_joined_one_per_line(self) -> None:
        checks = [
            CheckResult("t.passing", "t", "Fine.", Severity.ERROR, 10, 0),
            CheckResult("t.failing", "t", "Not fine.", Severity.WARNING, 10, 2, ("a=1", "a=2")),
        ]
        frame = checks_frame(checks).set_index("check_name")
        assert bool(frame.loc["t.passing", "passed"]) and pd.isna(
            frame.loc["t.passing", "examples"]
        )
        assert not bool(frame.loc["t.failing", "passed"])
        assert frame.loc["t.failing", "examples"] == "a=1\na=2"
        assert frame.loc["t.failing", "severity"] == "warning"

    def test_snapshots_of_an_empty_store(self, tmp_path) -> None:
        frame = snapshots_frame(RawStore(tmp_path / "nothing"))
        assert len(frame) == 0
        assert tuple(frame.columns) == RAW_SNAPSHOTS.column_names


class TestFetchLogging:
    def outcome(self, status: FetchStatus, minute: int, **extra) -> FetchOutcome:
        started = datetime(2026, 10, 1, 12, minute, tzinfo=UTC)
        request = FetchRequest(D.TEAM_GAME_LOGS, Season(2025), SeasonType.REGULAR)
        return FetchOutcome(request, status, started, started + timedelta(seconds=3), **extra)

    def test_attempts_that_reached_the_source_are_recorded(self, settings: Settings) -> None:
        recorded = log_fetches(
            settings,
            [
                self.outcome(FetchStatus.STORED, 0, rows=2460),
                self.outcome(FetchStatus.SKIPPED, 1),
                self.outcome(FetchStatus.UNCHANGED, 2, rows=2460),
                self.outcome(FetchStatus.FAILED, 3, error="timed out"),
            ],
        )
        assert recorded == 3
        with Database(settings.database_path) as database:
            fetches = OperationsLog(database).fetches()
        assert fetches["status"].tolist() == ["failed", "unchanged", "stored"]
        newest = fetches.iloc[0]
        assert (newest["source"], newest["dataset"]) == ("nba_stats", "team_game_logs")
        assert newest["partition_key"] == "season=2025-26/season_type=regular"
        assert newest["season"] == "2025-26"
        assert newest["error"] == "timed out" and pd.isna(newest["rows"])
        assert newest["started_at"] == pd.Timestamp("2026-10-01 12:03:00")
        assert fetches.iloc[2]["rows"] == 2460

    def test_a_run_of_only_skips_records_nothing_and_creates_no_database(
        self, settings: Settings
    ) -> None:
        assert log_fetches(settings, [self.outcome(FetchStatus.SKIPPED, 0)]) == 0
        assert not settings.database_path.exists()

    def test_times_are_stored_as_utc(self, settings: Settings) -> None:
        from datetime import timezone

        eastern = timezone(timedelta(hours=-4))
        started = datetime(2026, 10, 1, 8, 0, tzinfo=eastern)
        request = FetchRequest(D.TEAM_YEARS)
        log_fetches(
            settings, [FetchOutcome(request, FetchStatus.STORED, started, started, rows=45)]
        )
        with Database(settings.database_path) as database:
            fetch = OperationsLog(database).fetches().iloc[0]
        assert fetch["started_at"] == pd.Timestamp("2026-10-01 12:00:00")
        assert fetch["partition_key"] == "_all"
        assert pd.isna(fetch["season"])
