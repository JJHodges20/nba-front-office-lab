"""Raw store -> normalised tables -> quality checks, end to end on the fixture store."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.domain.schema import validate_frame
from front_office.domain.seasons import Season
from front_office.pipelines.check import check_store
from front_office.pipelines.normalize import (
    BUILT_TABLES,
    NBA_STATS_TABLES,
    IssueSeverity,
    normalize,
    stored_seasons,
)
from front_office.rawstore import RawStore
from tests.conftest import FIXTURE_RAW

TEAM_TABLES = {"teams", "team_seasons", "team_games", "playoff_results"}


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    """A private copy of the fixture store that a test may remove files from."""
    shutil.copytree(FIXTURE_RAW, tmp_path / "raw")
    return RawStore(tmp_path / "raw")


def remove(store: RawStore, *parts: str) -> None:
    shutil.rmtree(store.root.joinpath("nba_stats", *parts))


class TestFixtureStore:
    def test_seasons_in_the_store(self, fixture_store: RawStore) -> None:
        assert [season.label for season in stored_seasons(fixture_store)] == [
            "1996-97",
            "2012-13",
            "2025-26",
            "2026-27",
        ]

    def test_every_table_is_built_and_satisfies_its_contract(self, normalized) -> None:
        assert set(normalized.frames) == {contract.name for contract in BUILT_TABLES}
        for contract in BUILT_TABLES:
            assert validate_frame(normalized[contract.name], contract) == [], contract.name
        for contract in NBA_STATS_TABLES:
            assert len(normalized[contract.name]) > 0, contract.name

    def test_cap_rules_are_tabulated_from_configuration(self, normalized) -> None:
        assert normalized["salary_cap_rules"]["season"].tolist() == [
            "2024-25",
            "2025-26",
            "2026-27",
        ]

    def test_without_a_contract_file_the_contract_tables_are_empty_and_say_why(
        self, normalized
    ) -> None:
        assert len(normalized["contracts"]) == 0
        assert len(normalized["contract_years"]) == 0
        note = normalized.notes[-1]
        assert (note.table, note.scope) == ("contracts", "all seasons")
        assert "no contract file has been imported" in note.message

    def test_row_counts(self, normalized) -> None:
        counts = {name: len(frame) for name, frame in normalized.frames.items()}
        assert counts["teams"] == 30
        assert counts["team_seasons"] == 29 + 30 + 30  # 2026-27 has not started
        assert counts["playoff_results"] == 45
        assert counts["team_games"] == (2378 + 144) + (2458 + 170) + (2460 + 170 + 12)

    def test_nothing_fails_and_the_two_source_quirks_are_noted(self, normalized) -> None:
        assert normalized.errors == []
        assert [(note.table, note.scope, note.severity) for note in normalized.notes] == [
            ("team_seasons", "1996-97", IssueSeverity.NOTE),
            ("team_games", "2012-13", IssueSeverity.NOTE),
            ("contracts", "all seasons", IssueSeverity.NOTE),
        ]
        assert "rounded" in normalized.notes[0].message
        assert "0021201214" in normalized.notes[1].message
        assert str(normalized.notes[1]).startswith("note: team_games [2012-13]:")

    def test_outcomes_are_attached_to_team_seasons(self, normalized) -> None:
        seasons = normalized["team_seasons"]
        champions = seasons[seasons["won_championship"].fillna(False).astype(bool)]
        assert champions.set_index("season")["team_name"].to_dict() == {
            "1996-97": "Chicago Bulls",
            "2012-13": "Miami Heat",
            "2025-26": "New York Knicks",
        }
        assert seasons["won_championship"].notna().all()

    def test_play_in_participation(self, normalized) -> None:
        seasons = normalized["team_seasons"]
        play_in = seasons.groupby("season")["made_play_in"].sum().to_dict()
        assert play_in == {"1996-97": 0, "2012-13": 0, "2025-26": 8}

    def test_the_unstarted_season_contributes_only_rosters(self, normalized) -> None:
        for table in ("team_seasons", "team_games", "player_seasons", "player_game_logs"):
            assert "2026-27" not in set(normalized[table]["season"]), table
        assert "2026-27" in set(normalized["team_rosters"]["season"])

    def test_building_twice_gives_identical_tables(
        self, fixture_store, normalized, season_rules
    ) -> None:
        again = normalize(fixture_store, season_rules=season_rules)
        for name, frame in normalized.frames.items():
            assert frame.equals(again[name]), name

    def test_a_subset_of_seasons_can_be_built(self, fixture_store: RawStore) -> None:
        result = normalize(fixture_store, [Season(2012)])
        assert set(result["team_seasons"]["season"]) == {"2012-13"}
        assert len(result["teams"]) == 30
        assert result.errors == []
        assert len(result["player_seasons"]) == 0


class TestMissingData:
    def test_an_empty_store_builds_empty_tables(self, tmp_path: Path) -> None:
        result = normalize(RawStore(tmp_path / "nothing"))
        assert all(len(frame) == 0 for frame in result.frames.values())
        assert [(issue.table, issue.scope) for issue in result.errors] == [
            ("players", "all seasons")
        ]
        assert "player_index" in result.errors[0].message

    def test_a_missing_dataset_costs_one_table_for_one_season(self, store: RawStore) -> None:
        remove(store, "team_season_advanced", "season=2012-13")
        result = normalize(store)
        assert [(issue.table, issue.scope) for issue in result.errors] == [
            ("team_seasons", "2012-13")
        ]
        assert (
            "team_season_advanced (2012-13/regular) has not been fetched"
            in result.errors[0].message
        )
        assert set(result["team_seasons"]["season"]) == {"1996-97", "2025-26"}
        assert "2012-13" in set(result["team_games"]["season"])
        assert "2012-13" in set(result["playoff_results"]["season"])

    def test_missing_game_logs_cost_everything_that_depends_on_them(self, store: RawStore) -> None:
        remove(store, "team_game_logs", "season=2025-26", "season_type=regular")
        result = normalize(store)
        failed = {(issue.table, issue.scope) for issue in result.errors}
        assert failed == {
            ("team_games", "2025-26"),
            ("playoff_results", "2025-26"),
            ("team_seasons", "2025-26"),
            ("player_game_logs", "2025-26"),
        }
        skipped = [issue for issue in result.errors if issue.table == "playoff_results"]
        assert skipped[0].message == "not built: team_games could not be built"
        # Tables that do not depend on the game logs are unaffected.
        assert "2025-26" in set(result["player_seasons"]["season"])
        assert "2025-26" in set(result["team_rosters"]["season"])
        assert set(result["team_seasons"]["season"]) == {"1996-97", "2012-13"}

    def test_a_corrupt_snapshot_is_reported_not_raised(self, store: RawStore) -> None:
        directory = store.root / "nba_stats" / "standings" / "season=2012-13"
        next(directory.glob("*.json.gz")).write_bytes(b"corrupt")
        result = normalize(store)
        assert [(issue.table, issue.scope) for issue in result.errors] == [
            ("team_seasons", "2012-13")
        ]
        assert "cannot read snapshot" in result.errors[0].message

    def test_a_malformed_payload_is_reported_not_raised(self, store: RawStore) -> None:
        snapshot = store.latest(
            "nba_stats", "team_game_logs", {"season": "2012-13", "season_type": "playoffs"}
        )
        result_set = snapshot.payload["resultSets"][0]
        broken = {
            **snapshot.payload,
            "resultSets": [{**result_set, "rowSet": result_set["rowSet"][:-1]}],
        }
        remove(store, "team_game_logs", "season=2012-13", "season_type=playoffs")
        store.save(
            type(snapshot)(
                snapshot.source, snapshot.dataset, snapshot.partition, snapshot.fetched_at, broken
            )
        )
        result = normalize(store)
        errors = {issue.table: issue.message for issue in result.errors if issue.scope == "2012-13"}
        assert "without exactly two team rows" in errors["team_games"]
        assert set(errors) == {"team_games", "playoff_results", "team_seasons"}

    def test_the_newest_snapshot_wins(self, store: RawStore) -> None:
        from datetime import timedelta

        partition = {"season": "2025-26"}
        standings = store.latest("nba_stats", "standings", partition)
        result_set = standings.payload["resultSets"][0]
        rank = result_set["headers"].index("PlayoffRank")
        team = result_set["headers"].index("TeamID")
        rows = [list(row) for row in result_set["rowSet"]]
        changed_team = rows[0][team]
        rows[0][rank] = 15
        newer = type(standings)(
            standings.source,
            standings.dataset,
            standings.partition,
            standings.fetched_at + timedelta(days=1),
            {**standings.payload, "resultSets": [{**result_set, "rowSet": rows}]},
        )
        assert store.save(newer).created
        seasons = normalize(store)["team_seasons"]
        row = seasons[(seasons["season"] == "2025-26") & (seasons["team_id"] == changed_team)].iloc[
            0
        ]
        assert row["conference_rank"] == 15


class TestCheckStore:
    def test_report_on_the_fixture_store(self, fixture_store: RawStore) -> None:
        report = check_store(fixture_store)
        assert report.tables.errors == []
        assert {check.check for check in report.check_warnings} == {
            "team_games.points_add_up",
            "team_seasons.ratings_are_consistent",
        }
        # The fixture holds player logs for two teams only, so the two checks that need
        # every team's players fail on it by construction; nothing else does.
        assert {check.check for check in report.check_errors} == {
            "player_game_logs.points_sum_to_team_points",
            "player_game_logs.logged_games_have_players",
        }
        assert not report.ok
        assert len(report.failed_checks) == 4

    def test_a_store_with_missing_data_is_not_ok(self, store: RawStore) -> None:
        remove(store, "team_season_base", "season=2012-13")
        report = check_store(store)
        assert not report.ok
        assert [issue.table for issue in report.tables.errors] == ["team_seasons"]
