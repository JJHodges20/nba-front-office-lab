"""The Team Builder service, on a private copy of the lab with invented contracts."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics.rosters import POOLED_KEYS, ROSTER_METRICS
from front_office.domain.cap_rules import PayrollLine
from front_office.services import Lab, RosterError, RosterNotFound, RosterSummary
from tests.unit.services.conftest import (
    ABDELNABY,
    BROWN,
    BRUNSON,
    PRITCHARD,
    TATUM,
    TOWNS,
    WHITE,
)

CAP_2026 = 164_961_000


@pytest.fixture
def roster(scratch_lab: Lab) -> int:
    """Tatum, Brown and Pritchard start; White comes off the bench on an assumed salary."""
    builder = scratch_lab.builder
    roster_id = builder.create("Test roster")
    builder.add_player(roster_id, TATUM, slot="SF")
    builder.add_player(roster_id, BROWN, slot="SG")
    builder.add_player(roster_id, PRITCHARD, slot="PG")
    builder.add_player(roster_id, WHITE, assumed_salary=28_000_000)
    return roster_id


@pytest.fixture
def summary(scratch_lab: Lab, roster: int) -> RosterSummary:
    return scratch_lab.builder.summary(roster)


class TestRosters:
    def test_a_new_roster_takes_the_labs_default_seasons(self, scratch_lab: Lab) -> None:
        builder = scratch_lab.builder
        roster_id = builder.create("  My   first roster ")
        stored = builder.summary(roster_id).roster
        assert stored["name"] == "My first roster"
        assert (stored["stats_season"], stored["payroll_season"]) == ("2025-26", "2026-27")

    def test_seasons_can_be_chosen(self, scratch_lab: Lab) -> None:
        roster_id = scratch_lab.builder.create(
            "Old", stats_season="2025-26", payroll_season="2025-26"
        )
        assert scratch_lab.builder.summary(roster_id).roster["payroll_season"] == "2025-26"

    def test_listed_most_recently_changed_first_with_player_counts(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        other = scratch_lab.builder.create("Second")
        rosters = scratch_lab.builder.rosters()
        assert rosters["roster_id"].tolist() == [other, roster]
        assert rosters.set_index("roster_id")["players"].to_dict() == {roster: 4, other: 0}

    def test_rename_notes_and_seasons(self, scratch_lab: Lab, roster: int) -> None:
        builder = scratch_lab.builder
        builder.update(roster, name="Renamed", notes="  a note ", payroll_season="2025-26")
        stored = builder.summary(roster).roster
        assert (stored["name"], stored["notes"]) == ("Renamed", "a note")
        assert stored["payroll_season"] == "2025-26"
        assert stored["stats_season"] == "2025-26"

    def test_delete(self, scratch_lab: Lab, roster: int) -> None:
        scratch_lab.builder.delete(roster)
        assert len(scratch_lab.builder.rosters()) == 0
        with pytest.raises(RosterNotFound):
            scratch_lab.builder.summary(roster)

    def test_no_rosters(self, scratch_lab: Lab) -> None:
        rosters = scratch_lab.builder.rosters()
        assert len(rosters) == 0 and "players" in rosters.columns

    @pytest.mark.parametrize("name", ["", "   ", "x" * 81])
    def test_a_bad_name_is_refused(self, scratch_lab: Lab, name: str) -> None:
        with pytest.raises(RosterError):
            scratch_lab.builder.create(name)

    def test_a_bad_season_is_refused(self, scratch_lab: Lab) -> None:
        with pytest.raises(RosterError):
            scratch_lab.builder.create("Bad", stats_season="twenty")

    def test_an_unknown_roster_is_not_found(self, scratch_lab: Lab) -> None:
        with pytest.raises(RosterNotFound, match="no roster with id 999"):
            scratch_lab.builder.summary(999)
        with pytest.raises(RosterNotFound):
            scratch_lab.builder.add_player(999, TATUM)
        with pytest.raises(RosterNotFound):
            scratch_lab.builder.update(999, name="Ghost")


class TestPlayers:
    def test_starters_first_then_the_bench_by_minutes(self, summary: RosterSummary) -> None:
        players = summary.players
        assert players.index.name == "player_id"
        assert players.index.tolist() == [PRITCHARD, BROWN, TATUM, WHITE]
        assert players["slot"].tolist() == ["PG", "SG", "SF", "BENCH"]

    def test_who_each_player_is_and_what_he_did(self, summary: RosterSummary) -> None:
        tatum = summary.players.loc[TATUM]
        assert (tatum["player_name"], tatum["team"]) == ("Jayson Tatum", "BOS")
        assert (tatum["position"], tatum["position_group"], tatum["age"]) == ("F-G", "Forward", 28)
        assert tatum["games_played"] == 16
        assert tatum["pts_per_game"] == pytest.approx(348 / 16)
        assert tatum["ts_pct"] == pytest.approx(348 / (2 * (287 + 0.44 * 79)))

    def test_taking_a_starting_slot_sends_its_holder_to_the_bench(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        scratch_lab.builder.move_player(roster, WHITE, "PG")
        players = scratch_lab.builder.summary(roster).players
        assert players.loc[WHITE, "slot"] == "PG"
        assert players.loc[PRITCHARD, "slot"] == "BENCH"
        # The assumed salary travels with the player.
        assert players.loc[WHITE, "salary"] == 28_000_000

    def test_the_bench_holds_any_number(self, scratch_lab: Lab, roster: int) -> None:
        scratch_lab.builder.add_player(roster, BRUNSON)
        scratch_lab.builder.add_player(roster, TOWNS)
        slots = scratch_lab.builder.summary(roster).players["slot"]
        assert (slots == "BENCH").sum() == 3

    def test_remove_and_clear(self, scratch_lab: Lab, roster: int) -> None:
        builder = scratch_lab.builder
        builder.remove_player(roster, WHITE)
        assert builder.summary(roster).players.index.tolist() == [PRITCHARD, BROWN, TATUM]
        builder.clear(roster)
        assert len(builder.summary(roster).players) == 0

    def test_a_player_can_be_on_a_roster_only_once(self, scratch_lab: Lab, roster: int) -> None:
        with pytest.raises(RosterError, match="already on the roster"):
            scratch_lab.builder.add_player(roster, TATUM)

    def test_an_unknown_player_is_refused(self, scratch_lab: Lab, roster: int) -> None:
        with pytest.raises(RosterError, match="no player with id 1"):
            scratch_lab.builder.add_player(roster, 1)

    def test_an_unknown_slot_is_refused(self, scratch_lab: Lab, roster: int) -> None:
        with pytest.raises(RosterError, match="slot must be one of"):
            scratch_lab.builder.move_player(roster, TATUM, "QB")
        with pytest.raises(RosterError, match="slot must be one of"):
            scratch_lab.builder.add_player(roster, BRUNSON, slot="QB")
        assert BRUNSON not in scratch_lab.builder.summary(roster).players.index

    def test_a_player_not_on_the_roster_cannot_be_moved_or_priced(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        with pytest.raises(RosterError, match="not on the roster"):
            scratch_lab.builder.move_player(roster, BRUNSON, "C")
        with pytest.raises(RosterError, match="not on the roster"):
            scratch_lab.builder.assume_salary(roster, BRUNSON, 1)

    def test_a_player_without_statistics_still_counts(self, scratch_lab: Lab, roster: int) -> None:
        scratch_lab.builder.add_player(roster, ABDELNABY)
        summary = scratch_lab.builder.summary(roster)
        retired = summary.players.loc[ABDELNABY]
        assert (retired["player_name"], retired["position_group"]) == ("Alaa Abdelnaby", "Forward")
        assert pd.isna(retired["minutes"]) and pd.isna(retired["salary"])
        assert summary.indicators["players"] == 5
        assert summary.indicators["players_with_stats"] == 4
        assert summary.indicators["forwards"] == 2
        assert summary.unpriced == 1


class TestPayroll:
    def test_a_salary_is_the_users_figure_or_else_the_contract_datas(
        self, summary: RosterSummary
    ) -> None:
        players = summary.players
        assert players["salary"].tolist() == [7_000_000, 30_000_000, 40_000_000, 28_000_000]
        assert players["salary_source"].tolist() == ["contract", "contract", "contract", "assumed"]
        # What the contract data says stays visible beside the assumption.
        assert players.loc[WHITE, "contract_salary"] == 600_000
        assert players.loc[WHITE, "assumed_salary"] == 28_000_000
        assert pd.isna(players.loc[TATUM, "assumed_salary"])
        assert (summary.priced, summary.assumed, summary.unpriced) == (3, 1, 0)

    def test_the_total_is_measured_against_the_payroll_seasons_lines(
        self, summary: RosterSummary
    ) -> None:
        assert summary.payroll_total == 105_000_000
        assert summary.rules.salary_cap == CAP_2026
        payroll = summary.payroll
        assert payroll.cap_share == pytest.approx(105_000_000 / CAP_2026)
        assert payroll.position(PayrollLine.SALARY_CAP).room == CAP_2026 - 105_000_000
        assert payroll.highest_line_exceeded is None
        assert payroll.is_below_minimum

    def test_each_salary_has_its_share_of_the_cap(self, summary: RosterSummary) -> None:
        shares = summary.players["salary_cap_pct"]
        assert shares.loc[TATUM] == pytest.approx(40_000_000 / CAP_2026)
        assert shares.loc[WHITE] == pytest.approx(28_000_000 / CAP_2026)

    def test_assumptions_can_push_a_roster_over_the_lines(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        builder = scratch_lab.builder
        builder.assume_salary(roster, TATUM, 100_000_000)
        builder.assume_salary(roster, BROWN, 100_000_000)
        summary = builder.summary(roster)
        assert summary.payroll_total == 235_000_000
        assert summary.payroll.highest_line_exceeded is PayrollLine.SECOND_APRON
        assert (summary.priced, summary.assumed) == (1, 3)

    def test_dropping_an_assumption_returns_to_the_contract_data(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        scratch_lab.builder.assume_salary(roster, WHITE, None)
        white = scratch_lab.builder.summary(roster).players.loc[WHITE]
        assert (white["salary"], white["salary_source"]) == (600_000, "contract")
        assert white["slot"] == "BENCH"

    def test_an_assumed_salary_of_zero_is_a_salary(self, scratch_lab: Lab, roster: int) -> None:
        scratch_lab.builder.assume_salary(roster, WHITE, 0)
        white = scratch_lab.builder.summary(roster).players.loc[WHITE]
        assert (white["salary"], white["salary_source"]) == (0, "assumed")

    def test_a_negative_salary_is_refused(self, scratch_lab: Lab, roster: int) -> None:
        with pytest.raises(RosterError, match="cannot be negative"):
            scratch_lab.builder.assume_salary(roster, WHITE, -1)

    def test_a_payroll_season_without_cap_rules_has_a_total_but_no_lines(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        scratch_lab.builder.update(roster, payroll_season="2027-28")
        summary = scratch_lab.builder.summary(roster)
        assert summary.rules is None and summary.payroll is None
        # Tatum 44M and Pritchard 7.5M are under contract; White is assumed; Brown is not.
        assert summary.payroll_total == 44_000_000 + 7_500_000 + 28_000_000
        assert summary.unpriced == 1
        assert summary.players["salary_cap_pct"].isna().all()

    def test_without_contract_data_only_assumed_salaries_count(self, built_lab) -> None:
        with Lab(built_lab) as lab:
            roster_id = lab.builder.create("No contracts")
            lab.builder.add_player(roster_id, TATUM)
            lab.builder.add_player(roster_id, BROWN, assumed_salary=10_000_000)
            summary = lab.builder.summary(roster_id)
            assert summary.payroll_total == 10_000_000
            assert (summary.priced, summary.assumed, summary.unpriced) == (0, 1, 1)


class TestIndicators:
    def test_one_value_per_roster_metric(self, summary: RosterSummary) -> None:
        assert list(summary.indicators.index) == list(ROSTER_METRICS.keys)
        assert list(summary.league.index) == list(ROSTER_METRICS.keys)
        assert summary.metrics is ROSTER_METRICS

    def test_composition(self, summary: RosterSummary) -> None:
        indicators = summary.indicators
        assert (indicators["players"], indicators["players_with_stats"]) == (4, 4)
        assert indicators[["guards", "forwards", "centers"]].tolist() == [3, 1, 0]

    def test_age_and_minutes_come_from_the_statistics_season(
        self, scratch_lab: Lab, summary: RosterSummary
    ) -> None:
        seasons = scratch_lab.read(
            "player_seasons", {"season": "2025-26", "season_type": "regular"}
        )
        members = seasons.set_index("player_id").loc[summary.players.index]
        minutes = members["minutes"]
        assert summary.indicators["minutes_share"] == pytest.approx(minutes.sum() / (240 * 82))
        expected_age = (members["age"] * minutes).sum() / minutes.sum()
        assert summary.indicators["age"] == pytest.approx(expected_age)
        assert summary.indicators["age"] == pytest.approx(29.2667, abs=1e-4)

    def test_shooting_is_pooled_not_averaged(self, scratch_lab: Lab, summary) -> None:
        seasons = scratch_lab.read(
            "player_seasons", {"season": "2025-26", "season_type": "regular"}
        )
        members = seasons.set_index("player_id").loc[summary.players.index]
        pooled = members["pts"].sum() / (2 * (members["fga"].sum() + 0.44 * members["fta"].sum()))
        assert summary.indicators["ts_pct"] == pytest.approx(pooled)
        assert summary.indicators["ts_pct"] != pytest.approx(summary.players["ts_pct"].mean())

    def test_the_league_reference_pools_every_player(self, summary: RosterSummary) -> None:
        """The 41 fixture players scored 20,820 points on 16,225 shots and 3,511 free throws."""
        assert summary.league["ts_pct"] == pytest.approx(20820 / (2 * (16225 + 0.44 * 3511)))
        assert summary.league[list(POOLED_KEYS)].notna().all()
        assert summary.league[["players", "guards", "age", "minutes_share"]].isna().all()

    def test_an_empty_roster_has_counts_of_zero_and_no_rates(self, scratch_lab: Lab) -> None:
        summary = scratch_lab.builder.summary(scratch_lab.builder.create("Empty"))
        assert summary.indicators["players"] == 0
        assert summary.indicators["minutes_share"] == 0
        assert math.isnan(summary.indicators["age"])
        assert summary.indicators[list(POOLED_KEYS)].isna().all()
        assert summary.payroll_total == 0 and summary.payroll.is_below_minimum


class TestChecks:
    def test_facts_about_the_roster_against_the_seasons_rules(self, summary: RosterSummary) -> None:
        checks = {check.key: check for check in summary.checks}
        assert list(checks) == ["size", "starters", "salaries"]
        assert not checks["size"].passed
        assert checks["size"].message == (
            "4 players: 10 short of the 14 a team must generally carry in season."
        )
        assert not checks["starters"].passed
        assert checks["starters"].message == "No starter at PF, C."
        assert checks["salaries"].passed

    def test_a_full_legal_roster_passes(self, scratch_lab: Lab, roster: int) -> None:
        builder = scratch_lab.builder
        players = scratch_lab.players.table("2025-26").players
        others = [
            player for player in players.index if player not in (TATUM, BROWN, PRITCHARD, WHITE)
        ]
        builder.add_player(roster, others[0], slot="PF", assumed_salary=1_000_000)
        builder.add_player(roster, others[1], slot="C", assumed_salary=1_000_000)
        for player in others[2:10]:
            builder.add_player(roster, player, assumed_salary=1_000_000)
        summary = builder.summary(roster)
        assert len(summary.players) == 14
        assert all(check.passed for check in summary.checks)
        assert "within the 14 to 15" in summary.checks[0].message

    def test_too_many_players(self, scratch_lab: Lab, roster: int) -> None:
        players = scratch_lab.players.table("2025-26").players
        others = [
            player for player in players.index if player not in (TATUM, BROWN, PRITCHARD, WHITE)
        ]
        for player in others[:13]:
            scratch_lab.builder.add_player(roster, player)
        size = scratch_lab.builder.summary(roster).checks[0]
        assert not size.passed
        assert size.message.startswith("17 players: 2 more than the 15 standard contracts")

    def test_missing_salaries_are_called_out(self, scratch_lab: Lab, roster: int) -> None:
        scratch_lab.builder.add_player(roster, ABDELNABY)
        salaries = scratch_lab.builder.summary(roster).checks[-1]
        assert not salaries.passed
        assert salaries.message == "1 player has no salary, so the payroll is understated."


def test_a_roster_survives_a_rebuild(scratch_lab: Lab, roster: int) -> None:
    """Rosters are the user's work: rebuilding the league data must not touch them."""
    from front_office.pipelines.build import build_database

    assert build_database(scratch_lab.settings).loaded
    summary = scratch_lab.builder.summary(roster)
    assert summary.players.index.tolist() == [PRITCHARD, BROWN, TATUM, WHITE]
    assert summary.payroll_total == 105_000_000


class TestAssumptionsStayPut:
    """Gaps a planted-bug check found: who keeps what when players are moved or priced."""

    def test_a_starter_sent_to_the_bench_keeps_his_assumed_salary(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        builder = scratch_lab.builder
        builder.move_player(roster, WHITE, "PG")  # Pritchard to the bench
        builder.move_player(roster, PRITCHARD, "PG")  # and White, on 28M assumed, back to it
        white = builder.summary(roster).players.loc[WHITE]
        assert (white["slot"], white["salary"], white["salary_source"]) == (
            "BENCH",
            28_000_000,
            "assumed",
        )

    def test_assuming_a_salary_leaves_a_starter_in_his_slot(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        scratch_lab.builder.assume_salary(roster, TATUM, 45_000_000)
        tatum = scratch_lab.builder.summary(roster).players.loc[TATUM]
        assert (tatum["slot"], tatum["salary"]) == ("SF", 45_000_000)
