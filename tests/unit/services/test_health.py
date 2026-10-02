"""The Data Health service: freshness, failures, coverage and gaps."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from front_office.config import Settings
from front_office.domain.tables import ALL_TABLES
from front_office.services import Gap, Lab, LabNotBuilt, SourceStatus
from front_office.services.health import (
    ABSENT,
    FAILING,
    INFO,
    OK,
    STALE,
    WARNING,
    _missing_between,
    describe_age,
)

TODAY = date(2026, 10, 1)


def newest_fetch(lab: Lab) -> datetime:
    return pd.Timestamp(lab.read("raw_snapshots")["fetched_at"].max()).to_pydatetime()


def attempt(status: str, minutes: int, *, error: str | None = None) -> dict:
    """One fetch of the 2026-27 standings, ``minutes`` after noon."""
    moment = datetime(2026, 10, 2, 12, 0) + timedelta(minutes=minutes)
    return {
        "source": "nba_stats",
        "dataset": "standings",
        "partition_key": "season=2026-27",
        "season": "2026-27",
        "status": status,
        "rows": None if status == "failed" else 30,
        "error": error,
        "started_at": moment,
        "finished_at": moment + timedelta(seconds=2),
    }


class TestSources:
    def test_a_recent_fetch_is_ok(self, lab: Lab) -> None:
        now = newest_fetch(lab) + timedelta(hours=3)
        stats, contracts = lab.health.sources(now=now)
        assert isinstance(stats, SourceStatus)
        assert (stats.source, stats.title, stats.state) == ("nba_stats", "stats.nba.com", OK)
        assert stats.detail == "Newest fetch was 3 hours ago."
        assert stats.newest_fetch == newest_fetch(lab)
        assert (stats.slices, stats.failing) == (42, 0)
        assert contracts.source == "contract_file"

    def test_older_than_the_refresh_interval_is_stale(self, lab: Lab) -> None:
        now = newest_fetch(lab) + timedelta(days=2, hours=1)
        stats = lab.health.sources(now=now)[0]
        assert stats.state == STALE
        assert stats.detail == (
            "Newest fetch was 2 days ago, older than the 12-hour refresh interval. Run: fol refresh"
        )

    def test_the_interval_is_the_configured_one(self, lab: Lab) -> None:
        assert lab.settings.ingestion.refresh_after_hours == 12
        fetched = newest_fetch(lab)
        assert lab.health.sources(now=fetched + timedelta(hours=11, minutes=59))[0].state == OK
        assert lab.health.sources(now=fetched + timedelta(hours=12, minutes=1))[0].state == STALE

    def test_a_slice_whose_last_fetch_failed_makes_the_source_failing(
        self, scratch_lab: Lab
    ) -> None:
        scratch_lab.operations.record_fetches(
            [attempt("stored", 0), attempt("failed", 5, error="timed out")]
        )
        stats = scratch_lab.health.sources(now=newest_fetch(scratch_lab))[0]
        assert (stats.state, stats.failing) == (FAILING, 1)
        assert stats.detail == "1 dataset slice failed at the last attempt. Run: fol refresh"

    def test_a_later_success_clears_the_failure(self, scratch_lab: Lab) -> None:
        scratch_lab.operations.record_fetches(
            [attempt("failed", 0, error="timed out"), attempt("unchanged", 5)]
        )
        stats = scratch_lab.health.sources(now=newest_fetch(scratch_lab))[0]
        assert (stats.state, stats.failing) == (OK, 0)
        assert len(scratch_lab.health.failed_fetches()) == 0

    def test_without_a_contract_file_the_contract_source_is_absent(self, lab: Lab) -> None:
        contracts = lab.health.sources(now=newest_fetch(lab))[1]
        assert (contracts.title, contracts.state) == ("Contract file", ABSENT)
        assert contracts.newest_fetch is None and contracts.slices == 0
        assert "No contract file has been imported" in contracts.detail

    def test_an_imported_contract_file_states_its_source(self, contract_lab: Lab) -> None:
        contracts = contract_lab.health.sources(now=newest_fetch(contract_lab))[1]
        assert contracts.state == OK
        assert contracts.detail == (
            "11 contracts for 10 players, current as of 2026-10-01. Source as stated at "
            "import: invented for tests."
        )
        assert contracts.slices == 1 and contracts.newest_fetch is not None

    def test_an_unbuilt_lab_says_so(self, settings: Settings) -> None:
        with Lab(settings) as empty, pytest.raises(LabNotBuilt):
            empty.health.sources()


class TestDatasets:
    def test_one_row_per_dataset_in_ingest_order(self, lab: Lab) -> None:
        datasets = lab.health.datasets()
        assert len(datasets) == 13
        assert datasets["dataset"].tolist()[:3] == ["team_years", "player_index", "standings"]
        assert set(datasets["source"]) == {"nba_stats"}
        assert datasets["description"].notna().all()
        assert (datasets["failing"] == 0).all()

    def test_slices_seasons_and_fetch_times(self, lab: Lab) -> None:
        logs = lab.health.datasets().set_index("dataset").loc["team_game_logs"]
        assert logs["slices"] == 10
        assert (logs["first_season"], logs["last_season"]) == ("1996-97", "2026-27")
        assert logs["oldest_fetch"] <= logs["newest_fetch"]
        index = lab.health.datasets().set_index("dataset").loc["player_index"]
        assert index["slices"] == 1 and pd.isna(index["first_season"])

    def test_the_contract_file_is_a_dataset_too(self, contract_lab: Lab) -> None:
        datasets = contract_lab.health.datasets()
        assert len(datasets) == 14
        last = datasets.iloc[-1]
        assert (last["source"], last["dataset"]) == ("contract_file", "contracts")
        assert "supplied by the user" in last["description"]

    def test_failing_slices_are_counted_per_dataset(self, scratch_lab: Lab) -> None:
        scratch_lab.operations.record_fetches([attempt("failed", 0, error="boom")])
        datasets = scratch_lab.health.datasets().set_index("dataset")
        assert datasets.loc["standings", "failing"] == 1
        assert datasets["failing"].sum() == 1


class TestFetchesAndBuilds:
    def test_failed_fetches_are_the_slices_still_failing(self, scratch_lab: Lab) -> None:
        other = attempt("failed", 10, error="blocked") | {"partition_key": "season=2025-26"}
        scratch_lab.operations.record_fetches(
            [attempt("failed", 0, error="timed out"), attempt("stored", 5), other]
        )
        failed = scratch_lab.health.failed_fetches()
        assert failed["partition_key"].tolist() == ["season=2025-26"]
        assert failed["error"].tolist() == ["blocked"]

    def test_fetch_history_newest_first(self, scratch_lab: Lab) -> None:
        scratch_lab.operations.record_fetches([attempt("stored", 0), attempt("unchanged", 5)])
        history = scratch_lab.health.fetches()
        assert history["status"].tolist() == ["unchanged", "stored"]
        assert len(scratch_lab.health.fetches(limit=1)) == 1

    def test_builds_newest_first_with_duration(self, lab: Lab) -> None:
        builds = lab.health.builds()
        assert len(builds) == 1
        build = builds.iloc[0]
        assert (build["build_id"], build["seconds"]) == (1, 9.0)
        assert build["build_notes"] == 3

    def test_a_second_build_is_listed_first(self, contract_lab: Lab) -> None:
        assert contract_lab.health.builds()["build_id"].tolist() == [2, 1]


class TestIssuesAndChecks:
    def test_issues_of_the_last_build(self, lab: Lab) -> None:
        issues = lab.health.issues()
        assert len(issues) == 3
        assert set(issues["severity"]) == {"note"}
        assert "never played" in " ".join(issues["message"])

    def test_errors_are_listed_before_notes(self, scratch_lab: Lab) -> None:
        with scratch_lab.database.begin() as connection:
            issues = scratch_lab.database.table("build_issues")
            connection.execute(
                issues.insert().values(
                    issue_number=99,
                    table_name="team_seasons",
                    scope="2025-26",
                    severity="error",
                    message="dataset missing",
                )
            )
        assert scratch_lab.health.issues()["severity"].iloc[0] == "error"
        assert scratch_lab.health.issues()["issue_number"].iloc[0] == 99

    def test_checks_list_failures_first_errors_before_warnings(self, lab: Lab) -> None:
        checks = lab.health.checks()
        assert len(checks) == 45
        failed = checks[~checks["passed"]]
        assert checks["passed"].tolist() == [False] * len(failed) + [True] * (45 - len(failed))
        assert failed["severity"].tolist() == sorted(failed["severity"].tolist())
        assert "error" in set(failed["severity"]) and "warning" in set(failed["severity"])


class TestTables:
    def test_every_table_with_rows_and_seasons(self, lab: Lab) -> None:
        tables = lab.health.tables()
        assert tables["table"].tolist() == [contract.name for contract in ALL_TABLES]
        rows = tables.set_index("table")
        seasons = rows.loc["team_seasons"]
        assert (seasons["rows"], seasons["seasons"]) == (89, 3)
        assert (seasons["first_season"], seasons["last_season"]) == ("1996-97", "2025-26")
        assert rows.loc["teams", "rows"] == 30 and rows.loc["teams", "seasons"] == 0
        assert rows.loc["contracts", "rows"] == 0
        assert rows["description"].notna().all()

    def test_kept_tables_are_counted_too(self, scratch_lab: Lab) -> None:
        scratch_lab.builder.create("One")
        rows = scratch_lab.health.tables().set_index("table")
        assert rows.loc["custom_rosters", "rows"] == 1
        assert rows.loc["builds", "rows"] == 2
        assert rows.loc["contract_years", "seasons"] == 3


class TestGaps:
    def test_what_the_fixture_lab_lacks(self, lab: Lab) -> None:
        gaps = lab.health.gaps(today=TODAY)
        assert all(isinstance(gap, Gap) for gap in gaps)
        assert [(gap.area, gap.severity) for gap in gaps] == [
            ("Team statistics", WARNING),
            ("Contracts", WARNING),
            ("Player statistics", INFO),
            ("Current season", INFO),
        ]
        messages = {gap.area: gap.message for gap in gaps}
        assert messages["Team statistics"] == (
            "No team statistics for 27 seasons between 1997-98 and 2024-25."
        )
        assert "fol contracts import" in messages["Contracts"]
        assert messages["Player statistics"].startswith("Player statistics cover 2025-26")
        assert messages["Current season"] == (
            "2026-27 has no games in the data yet; the newest season with statistics is 2025-26."
        )

    def test_with_contracts_the_gap_is_the_seasons_without_a_cap(self, contract_lab) -> None:
        gaps = {gap.area: gap for gap in contract_lab.health.gaps(today=TODAY)}
        assert "Contracts" not in gaps
        assert gaps["Cap rules"].severity == INFO
        assert gaps["Cap rules"].message.startswith(
            "No cap rules are configured for 2027-28, 2028-29"
        )

    def test_during_the_newest_season_there_is_no_current_season_gap(self, lab: Lab) -> None:
        areas = [gap.area for gap in lab.health.gaps(today=date(2026, 3, 1))]
        assert "Current season" not in areas

    def test_tables_from_another_version_are_a_warning(self, scratch_lab: Lab) -> None:
        with scratch_lab.database.begin() as connection:
            connection.execute(scratch_lab.database.meta.update().values(value="0" * 12))
        gaps = scratch_lab.health.gaps(today=TODAY)
        assert (gaps[0].area, gaps[0].severity) == ("Database", WARNING)
        assert gaps[0].message.endswith("Run: fol build")

    def test_parts_that_could_not_be_built_are_a_warning(self, scratch_lab: Lab) -> None:
        with scratch_lab.database.begin() as connection:
            builds = scratch_lab.database.table("builds")
            connection.execute(builds.update().values(build_errors=2))
        gaps = {gap.area: gap for gap in scratch_lab.health.gaps(today=TODAY)}
        assert gaps["Build"].severity == WARNING
        assert gaps["Build"].message.startswith("2 table parts could not be built")


class TestHelpers:
    @pytest.mark.parametrize(
        ("age", "text"),
        [
            (timedelta(seconds=20), "less than a minute"),
            (timedelta(minutes=1), "1 minute"),
            (timedelta(minutes=59), "59 minutes"),
            (timedelta(hours=1), "1 hour"),
            (timedelta(hours=23, minutes=59), "23 hours"),
            (timedelta(days=1), "1 day"),
            (timedelta(days=40), "40 days"),
            (timedelta(seconds=-5), "less than a minute"),
        ],
    )
    def test_ages_read_in_the_largest_unit_that_fits(self, age: timedelta, text: str) -> None:
        assert describe_age(age) == text

    def test_missing_seasons_between_the_first_and_last(self) -> None:
        assert _missing_between(["2021-22", "2022-23", "2023-24"]) == []
        assert _missing_between(["2020-21", "2022-23", "2024-25"]) == ["2021-22", "2023-24"]
        assert _missing_between(["1999-00"]) == []
        assert _missing_between([]) == []
