"""Names to ids, against the fixture build: every team of three seasons, and the players of
Boston and New York (``lab`` is in this directory's conftest)."""

from __future__ import annotations

import pytest

from front_office.services import Lab
from front_office.services.entities import fold
from tests.helpers import BOS, BROWN, HART, NYK, VUCEVIC

BRUCE_BROWN, MINOTT = 1628971, 1631169
CLIPPERS, LAKERS, THUNDER, HORNETS, PELICANS = (
    1610612746,
    1610612747,
    1610612760,
    1610612766,
    1610612740,
)


def ids(candidates) -> set:  # type: ignore[no-untyped-def]
    return {candidate.id for candidate in candidates}


class TestFolding:
    @pytest.mark.parametrize(
        ("text", "folded"),
        [
            ("Nikola Vučević", "nikola vucevic"),
            ("  O'Neal ", "o neal"),
            ("Karl-Anthony Towns", "karl anthony towns"),
            ("L.A.", "l a"),
        ],
    )
    def test_case_accents_and_punctuation_go(self, text: str, folded: str) -> None:
        assert fold(text) == folded


class TestPlayers:
    def test_a_full_name_is_one_player(self, lab: Lab) -> None:
        (only,) = lab.entities.find_players("Jaylen Brown")
        assert (only.id, only.match) == (BROWN, "full name")

    def test_a_shared_last_name_is_every_player_who_has_it(self, lab: Lab) -> None:
        found = lab.entities.find_players("Brown", season="2025-26")
        assert ids(found) == {BROWN, BRUCE_BROWN}
        assert {candidate.match for candidate in found} == {"last name"}

    def test_a_first_name_alone_is_a_last_resort(self, lab: Lab) -> None:
        assert ids(lab.entities.find_players("Josh", season="2025-26")) == {HART, MINOTT}

    def test_accents_need_not_be_typed(self, lab: Lab) -> None:
        assert ids(lab.entities.find_players("Vucevic")) == {VUCEVIC}

    def test_the_detail_says_where_and_when(self, lab: Lab) -> None:
        (brown,) = [c for c in lab.entities.find_players("Brown", "2025-26") if c.id == BROWN]
        assert brown.detail.startswith("BOS, 2016-17 to ")

    def test_a_season_a_player_did_not_play_keeps_the_player(self, lab: Lab) -> None:
        """Asked about 2012-13, Jaylen Brown is still Jaylen Brown; the tool says what is missing."""
        assert ids(lab.entities.find_players("Jaylen Brown", season="2012-13")) == {BROWN}

    def test_an_unknown_name_is_nobody(self, lab: Lab) -> None:
        assert lab.entities.find_players("Nobody Atall") == ()


class TestTeams:
    @pytest.mark.parametrize(
        "text", ["Celtics", "Boston", "Boston Celtics", "BOS", "boston celtics"]
    )
    def test_every_name_of_a_team(self, lab: Lab, text: str) -> None:
        assert ids(lab.entities.find_teams(text)) == {BOS}

    def test_la_is_either_los_angeles_team(self, lab: Lab) -> None:
        assert ids(lab.entities.find_teams("LA")) == {CLIPPERS, LAKERS}
        assert ids(lab.entities.find_teams("Los Angeles")) == {CLIPPERS, LAKERS}
        assert ids(lab.entities.find_teams("Lakers")) == {LAKERS}

    def test_an_old_name_finds_the_franchise(self, lab: Lab) -> None:
        (sonics,) = lab.entities.find_teams("SuperSonics")
        assert sonics.id == THUNDER and sonics.name == "Oklahoma City Thunder"
        assert "Seattle SuperSonics" in sonics.detail

    def test_a_name_two_franchises_used_depends_on_the_season(self, lab: Lab) -> None:
        assert ids(lab.entities.find_teams("Hornets")) == {HORNETS, PELICANS}
        assert ids(lab.entities.find_teams("Hornets", season="2025-26")) == {HORNETS}
        assert ids(lab.entities.find_teams("Hornets", season="2012-13")) == {PELICANS}

    def test_a_team_name_is_read_as_a_team(self, lab: Lab) -> None:
        assert ids(lab.entities.resolve("Knicks")) == {NYK}
        assert lab.entities.resolve("Knicks", kind="player") == ()


class TestSeasons:
    @pytest.mark.parametrize(
        ("text", "seasons"),
        [
            ("2025-26", ["2025-26"]),
            ("the 2025-2026 season", ["2025-26"]),
            ("1999-00", ["1999-00"]),
            ("the 2013 Knicks", ["2012-13", "2013-14"]),
            ("on 2026-10-01", []),
            ("2025-27", []),
            ("no year here", []),
        ],
    )
    def test_what_a_season_reference_can_mean(self, lab: Lab, text: str, seasons: list) -> None:
        assert [candidate.id for candidate in lab.entities.seasons(text)] == seasons
