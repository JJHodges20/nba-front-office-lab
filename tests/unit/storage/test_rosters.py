from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from front_office.domain.schema import validate_frame
from front_office.domain.tables.rosters import CUSTOM_ROSTERS, ROSTER_PLAYERS
from front_office.storage import Database, RosterNotFound, RosterRepository, StorageError

TATUM, BROWN, WHITE = 1628369, 1627759, 1628401


class Clock:
    """Hands out strictly increasing moments, so ordering by time is deterministic."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with Database(tmp_path / "lab.sqlite") as opened:
        yield opened


@pytest.fixture
def rosters(database: Database) -> RosterRepository:
    return RosterRepository(database, now=Clock())


def new_roster(rosters: RosterRepository, name: str = "Budget contender") -> int:
    return rosters.create(name, stats_season="2025-26", payroll_season="2026-27")


class TestRosters:
    def test_create_and_get(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        roster = rosters.get(roster_id)
        assert roster["name"] == "Budget contender"
        assert (roster["stats_season"], roster["payroll_season"]) == ("2025-26", "2026-27")
        assert roster["notes"] is None
        assert roster["created_at"] == roster["updated_at"]

    def test_ids_are_assigned_in_order(self, rosters: RosterRepository) -> None:
        assert [new_roster(rosters, f"Roster {n}") for n in range(3)] == [1, 2, 3]

    def test_names_are_tidied(self, rosters: RosterRepository) -> None:
        assert rosters.get(new_roster(rosters, "  Two   words "))["name"] == "Two words"

    @pytest.mark.parametrize("name", ["", "   ", "x" * 81])
    def test_bad_names_are_refused(self, rosters: RosterRepository, name: str) -> None:
        with pytest.raises(StorageError):
            new_roster(rosters, name)

    def test_seasons_are_validated(self, rosters: RosterRepository) -> None:
        with pytest.raises(ValueError, match="not a season label"):
            rosters.create("x", stats_season="2025", payroll_season="2026-27")

    def test_list_is_most_recently_changed_first(self, rosters: RosterRepository) -> None:
        first, second = new_roster(rosters, "First"), new_roster(rosters, "Second")
        listed = rosters.list()
        assert validate_frame(listed, CUSTOM_ROSTERS) == []
        assert listed["roster_id"].tolist() == [second, first]
        rosters.set_player(first, TATUM)
        assert rosters.list()["roster_id"].tolist() == [first, second]

    def test_list_of_nothing_is_an_empty_conforming_frame(self, rosters: RosterRepository) -> None:
        listed = rosters.list()
        assert len(listed) == 0
        assert tuple(listed.columns) == CUSTOM_ROSTERS.column_names

    def test_update_changes_only_what_is_given(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        created = rosters.get(roster_id)["created_at"]
        rosters.update(roster_id, name="Renamed", notes="  Needs a rim protector.  ")
        roster = rosters.get(roster_id)
        assert roster["name"] == "Renamed"
        assert roster["notes"] == "Needs a rim protector."
        assert roster["stats_season"] == "2025-26"
        assert roster["created_at"] == created
        assert roster["updated_at"] > created

    def test_blank_notes_are_stored_as_null(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        rosters.update(roster_id, notes="something")
        rosters.update(roster_id, notes="   ")
        assert rosters.get(roster_id)["notes"] is None

    def test_update_seasons(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        rosters.update(roster_id, stats_season="2024-25", payroll_season="2025-26")
        roster = rosters.get(roster_id)
        assert (roster["stats_season"], roster["payroll_season"]) == ("2024-25", "2025-26")
        with pytest.raises(ValueError):
            rosters.update(roster_id, payroll_season="next year")

    def test_delete_removes_the_roster_and_its_players(self, rosters: RosterRepository) -> None:
        keep, drop = new_roster(rosters, "Keep"), new_roster(rosters, "Drop")
        rosters.set_player(keep, TATUM)
        rosters.set_player(drop, TATUM)
        rosters.set_player(drop, BROWN)
        rosters.delete(drop)
        assert rosters.list()["roster_id"].tolist() == [keep]
        assert rosters.players(keep)["player_id"].tolist() == [TATUM]
        with pytest.raises(RosterNotFound):
            rosters.players(drop)

    @pytest.mark.parametrize(
        "action",
        [
            lambda r: r.get(99),
            lambda r: r.players(99),
            lambda r: r.update(99, name="x"),
            lambda r: r.delete(99),
            lambda r: r.set_player(99, TATUM),
            lambda r: r.remove_player(99, TATUM),
            lambda r: r.clear(99),
        ],
    )
    def test_a_missing_roster_is_reported(self, rosters: RosterRepository, action) -> None:
        with pytest.raises(RosterNotFound, match="no roster with id 99"):
            action(rosters)


class TestPlayers:
    def test_added_players_default_to_the_bench(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        rosters.set_player(roster_id, TATUM)
        players = rosters.players(roster_id)
        assert validate_frame(players, ROSTER_PLAYERS) == []
        row = players.iloc[0]
        assert (row["player_id"], row["slot"]) == (TATUM, "BENCH")
        assert pd.isna(row["assumed_salary"])

    def test_players_are_listed_in_the_order_added(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        for player_id in (WHITE, TATUM, BROWN):
            rosters.set_player(roster_id, player_id)
        assert rosters.players(roster_id)["player_id"].tolist() == [WHITE, TATUM, BROWN]

    def test_setting_a_player_again_changes_him_in_place(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        rosters.set_player(roster_id, TATUM)
        rosters.set_player(roster_id, BROWN)
        added = rosters.players(roster_id).set_index("player_id").loc[TATUM, "added_at"]
        rosters.set_player(roster_id, TATUM, slot="SF", assumed_salary=40_000_000)
        players = rosters.players(roster_id).set_index("player_id")
        assert len(players) == 2
        assert (players.loc[TATUM, "slot"], players.loc[TATUM, "assumed_salary"]) == (
            "SF",
            40_000_000,
        )
        assert players.loc[TATUM, "added_at"] == added
        assert players.index.tolist() == [TATUM, BROWN]

    def test_an_assumed_salary_can_be_cleared(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        rosters.set_player(roster_id, TATUM, assumed_salary=1_000_000)
        rosters.set_player(roster_id, TATUM)
        assert pd.isna(rosters.players(roster_id).iloc[0]["assumed_salary"])

    def test_a_zero_salary_is_allowed_and_distinct_from_none(
        self, rosters: RosterRepository
    ) -> None:
        roster_id = new_roster(rosters)
        rosters.set_player(roster_id, TATUM, assumed_salary=0)
        assert rosters.players(roster_id).iloc[0]["assumed_salary"] == 0

    @pytest.mark.parametrize("slot", ["G", "bench", "", "CENTER"])
    def test_unknown_slots_are_refused(self, rosters: RosterRepository, slot: str) -> None:
        roster_id = new_roster(rosters)
        with pytest.raises(StorageError, match="slot must be one of"):
            rosters.set_player(roster_id, TATUM, slot=slot)
        assert len(rosters.players(roster_id)) == 0

    def test_a_negative_salary_is_refused(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        with pytest.raises(StorageError, match="cannot be negative"):
            rosters.set_player(roster_id, TATUM, assumed_salary=-1)

    def test_remove_and_clear(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        for player_id in (TATUM, BROWN, WHITE):
            rosters.set_player(roster_id, player_id)
        rosters.remove_player(roster_id, BROWN)
        assert rosters.players(roster_id)["player_id"].tolist() == [TATUM, WHITE]
        rosters.remove_player(roster_id, BROWN)  # removing an absent player is not an error
        rosters.clear(roster_id)
        assert len(rosters.players(roster_id)) == 0

    def test_the_same_player_can_be_on_several_rosters(self, rosters: RosterRepository) -> None:
        one, two = new_roster(rosters, "One"), new_roster(rosters, "Two")
        rosters.set_player(one, TATUM, slot="SF")
        rosters.set_player(two, TATUM, slot="PF")
        assert rosters.players(one).iloc[0]["slot"] == "SF"
        assert rosters.players(two).iloc[0]["slot"] == "PF"

    def test_changing_players_marks_the_roster_as_updated(self, rosters: RosterRepository) -> None:
        roster_id = new_roster(rosters)
        stamps = [rosters.get(roster_id)["updated_at"]]
        rosters.set_player(roster_id, TATUM)
        stamps.append(rosters.get(roster_id)["updated_at"])
        rosters.remove_player(roster_id, TATUM)
        stamps.append(rosters.get(roster_id)["updated_at"])
        rosters.clear(roster_id)
        stamps.append(rosters.get(roster_id)["updated_at"])
        assert stamps == sorted(set(stamps))

    def test_numpy_ids_are_accepted(self, rosters: RosterRepository) -> None:
        import numpy as np

        roster_id = new_roster(rosters)
        rosters.set_player(roster_id, np.int64(TATUM))
        assert rosters.players(roster_id)["player_id"].tolist() == [TATUM]


def test_rosters_survive_reopening_the_database(tmp_path: Path) -> None:
    path = tmp_path / "lab.sqlite"
    with Database(path) as first:
        rosters = RosterRepository(first)
        roster_id = rosters.create("Persistent", stats_season="2025-26", payroll_season="2026-27")
        rosters.set_player(roster_id, TATUM, slot="SF")
    with Database(path) as second:
        rosters = RosterRepository(second)
        assert rosters.get(roster_id)["name"] == "Persistent"
        assert rosters.players(roster_id)["slot"].tolist() == ["SF"]
