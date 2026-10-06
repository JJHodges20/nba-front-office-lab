"""The contract service, against a database with an invented contract file built in.

The file is in this directory's conftest: New York owes 205M to four players and 7M of
dead money; Boston owes 77M on three standard contracts and has one two-way player;
one salary has no team. None of the figures is real.
"""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.config import Settings
from front_office.services import Lab
from tests.unit.services.conftest import (
    BOS,
    BRIDGES,
    BROWN,
    BRUNSON,
    HART,
    NYK,
    PRITCHARD,
    TATUM,
    VUCEVIC,
    WHITE,
)

CAP_2026 = 164_961_000


@pytest.fixture(scope="module")
def table(contract_lab: Lab) -> pd.DataFrame:
    """Every salary owed in 2026-27."""
    return contract_lab.contracts.table("2026-27")


@pytest.fixture(scope="module")
def payrolls(contract_lab: Lab) -> pd.DataFrame:
    return contract_lab.contracts.team_payrolls("2026-27")


class TestAvailability:
    def test_a_lab_without_a_contract_file_says_so(self, lab: Lab) -> None:
        assert not lab.contracts.available
        assert lab.contracts.seasons() == ()

    def test_every_view_is_empty_but_well_formed_without_contracts(self, lab: Lab) -> None:
        contracts = lab.contracts
        assert len(contracts.table("2026-27")) == 0
        assert "salary_cap_pct" in contracts.table("2026-27").columns
        assert len(contracts.team_payrolls("2026-27")) == 0
        assert "team_salary" in contracts.team_payrolls("2026-27").columns
        assert len(contracts.commitments(BOS)) == 0
        assert len(contracts.outlook(BOS)) == 0
        assert len(contracts.salaries("2026-27")) == 0
        assert len(contracts.sources()) == 0
        assert contracts.unassigned("2026-27") == 0

    def test_an_unbuilt_lab_has_no_contracts(self, settings: Settings) -> None:
        with Lab(settings) as empty:
            assert not empty.contracts.available

    def test_seasons_and_source(self, contract_lab: Lab) -> None:
        assert contract_lab.contracts.available
        assert contract_lab.contracts.seasons() == ("2026-27", "2027-28", "2028-29")
        sources = contract_lab.contracts.sources()
        assert len(sources) == 1
        source = sources.iloc[0]
        assert source["source_label"] == "invented for tests"
        assert source["as_of_date"] == pd.Timestamp("2026-10-01")
        assert (source["contracts"], source["players"]) == (11, 10)


class TestCapRules:
    def test_configured_seasons_newest_first(self, lab: Lab) -> None:
        rules = lab.contracts.cap_rules()
        assert rules["season"].tolist() == ["2026-27", "2025-26", "2024-25"]
        assert rules.iloc[0]["salary_cap"] == CAP_2026
        assert rules.iloc[0]["source_urls"].startswith("http")


class TestTable:
    def test_every_salary_owed_in_the_season_largest_first(self, table: pd.DataFrame) -> None:
        assert len(table) == 11
        assert table["salary"].is_monotonic_decreasing
        top = table.iloc[0]
        assert (top["player_id"], top["salary"], top["team"]) == (BRUNSON, 60_000_000, "NYK")
        assert top["salary_cap_pct"] == pytest.approx(60_000_000 / CAP_2026)
        assert top["team_name"] == "New York Knicks"

    def test_players_carry_the_leagues_name_and_position(self, table: pd.DataFrame) -> None:
        rows = table.set_index("contract_id")
        tatum = rows[rows["player_id"] == TATUM].iloc[0]
        assert (tatum["player_name"], tatum["position"]) == ("Jayson Tatum", "F-G")
        assert not table["player_name"].str.startswith("player ").any()

    def test_contract_details(self, table: pd.DataFrame) -> None:
        tatum = table[table["player_id"] == TATUM].iloc[0]
        assert (tatum["first_season"], tatum["last_season"], tatum["seasons"]) == (
            "2026-27",
            "2027-28",
            2,
        )
        assert (tatum["total_salary"], tatum["years_remaining"]) == (84_000_000, 1)
        assert (tatum["contract_type"], tatum["status"]) == ("standard", "active")
        white = table[table["player_id"] == WHITE].iloc[0]
        assert white["contract_type"] == "two_way"

    def test_dead_money_is_listed_as_such(self, table: pd.DataFrame) -> None:
        dead = table[table["status"] == "dead_money"]
        assert sorted(dead["player_id"]) == sorted([BROWN, VUCEVIC])
        assert set(dead["team"]) == {"NYK"}
        # Brown appears twice: his Boston contract and what New York still owes him.
        assert len(table[table["player_id"] == BROWN]) == 2

    def test_a_salary_without_a_team_has_no_team(self, table: pd.DataFrame, contract_lab) -> None:
        hart = table[table["player_id"] == HART].iloc[0]
        assert pd.isna(hart["team"]) and pd.isna(hart["team_id"])
        assert contract_lab.contracts.unassigned("2026-27") == 1
        assert contract_lab.contracts.unassigned("2027-28") == 0

    def test_a_later_season_shows_options(self, contract_lab: Lab) -> None:
        later = contract_lab.contracts.table("2027-28").set_index("player_id")
        assert later.loc[TATUM, "option"] == "player"
        assert later.loc[PRITCHARD, "option"] == "team"
        assert later.loc[TATUM, "years_remaining"] == 0
        assert later["salary_cap_pct"].isna().all()  # no cap is configured for 2027-28


class TestSalaries:
    def test_a_players_salary_is_his_active_contract(self, contract_lab: Lab) -> None:
        salaries = contract_lab.contracts.salaries("2026-27")
        assert salaries.index.name == "player_id" and salaries.index.is_unique
        assert len(salaries) == 9
        assert salaries.loc[BROWN, "salary"] == 30_000_000  # not the 2M New York owes him
        assert VUCEVIC not in salaries.index  # owed dead money only
        assert salaries.loc[WHITE, "salary"] == 600_000
        assert salaries.loc[TATUM, "salary_cap_pct"] == pytest.approx(40_000_000 / CAP_2026)


class TestTeamPayrolls:
    def test_largest_payroll_first_and_only_teams_the_file_covers(self, payrolls) -> None:
        assert payrolls.index.tolist() == [NYK, BOS]
        assert payrolls["team"].tolist() == ["NYK", "BOS"]
        assert payrolls.loc[NYK, "team_name"] == "New York Knicks"

    def test_dead_money_counts_and_two_way_contracts_do_not(self, payrolls) -> None:
        knicks, celtics = payrolls.loc[NYK], payrolls.loc[BOS]
        assert (knicks["active_salary"], knicks["dead_money"]) == (205_000_000, 7_000_000)
        assert knicks["team_salary"] == 212_000_000
        assert (knicks["standard_contracts"], knicks["two_way_contracts"]) == (4, 0)
        assert celtics["team_salary"] == 77_000_000
        assert celtics["two_way_salary"] == 600_000
        assert (celtics["standard_contracts"], celtics["two_way_contracts"]) == (3, 1)

    def test_each_payroll_is_measured_against_the_seasons_lines(self, payrolls) -> None:
        knicks, celtics = payrolls.loc[NYK], payrolls.loc[BOS]
        assert knicks["cap_share"] == pytest.approx(212_000_000 / CAP_2026)
        assert knicks["room_salary_cap"] == CAP_2026 - 212_000_000
        assert knicks["room_first_apron"] == 209_015_000 - 212_000_000
        assert knicks["room_second_apron"] == 221_686_000 - 212_000_000
        assert knicks["highest_line_exceeded"] == "first_apron"
        assert not knicks["is_below_minimum"]
        assert pd.isna(celtics["highest_line_exceeded"])
        assert celtics["is_below_minimum"]
        assert celtics["room_minimum_team_salary"] == 148_465_000 - 77_000_000

    def test_a_season_without_cap_rules_has_payrolls_but_no_lines(self, contract_lab) -> None:
        payrolls = contract_lab.contracts.team_payrolls("2027-28")
        assert payrolls.loc[BOS, "team_salary"] == 51_500_000
        assert payrolls.loc[NYK, "dead_money"] == 3_000_000
        assert payrolls["cap_share"].isna().all()
        assert payrolls["room_salary_cap"].isna().all()
        assert payrolls["highest_line_exceeded"].isna().all()

    def test_the_salary_without_a_team_is_in_no_payroll(self, payrolls) -> None:
        assert payrolls["team_salary"].sum() == 289_000_000  # Hart's 12M is in neither


class TestCommitments:
    def test_one_row_per_contract_one_column_per_season(self, contract_lab: Lab) -> None:
        owed = contract_lab.contracts.commitments(BOS)
        assert list(owed.columns) == [
            "player_id",
            "player_name",
            "contract_type",
            "status",
            "2026-27",
            "2027-28",
            "2028-29",
            "total_salary",
        ]
        assert owed["player_id"].tolist() == [TATUM, BROWN, PRITCHARD, WHITE]
        assert owed["player_name"].iloc[0] == "Jayson Tatum"
        assert owed["total_salary"].tolist() == [84_000_000, 30_000_000, 22_500_000, 600_000]

    def test_a_season_the_contract_does_not_run_is_missing_not_zero(self, contract_lab) -> None:
        owed = contract_lab.contracts.commitments(BOS).set_index("player_id")
        assert owed.loc[PRITCHARD, ["2026-27", "2027-28", "2028-29"]].tolist() == [
            7_000_000,
            7_500_000,
            8_000_000,
        ]
        assert pd.isna(owed.loc[BROWN, "2027-28"])
        assert pd.isna(owed.loc[TATUM, "2028-29"])

    def test_dead_money_is_part_of_what_a_team_owes(self, contract_lab: Lab) -> None:
        owed = contract_lab.contracts.commitments(NYK)
        assert len(owed) == 6
        assert (owed["status"] == "dead_money").sum() == 2

    def test_a_team_with_no_contracts(self, contract_lab: Lab) -> None:
        owed = contract_lab.contracts.commitments(1610612737)
        assert len(owed) == 0 and "player_name" in owed.columns


class TestOutlook:
    def test_payroll_by_season_with_the_cap_lines(self, contract_lab: Lab) -> None:
        outlook = contract_lab.contracts.outlook(BOS)
        assert outlook.index.tolist() == ["2026-27", "2027-28", "2028-29"]
        assert outlook["team_salary"].tolist() == [77_000_000, 51_500_000, 8_000_000]
        assert outlook["standard_contracts"].tolist() == [3, 2, 1]
        assert outlook.loc["2026-27", "salary_cap"] == CAP_2026
        assert outlook.loc["2026-27", "luxury_tax"] == 200_428_000
        assert outlook.loc["2026-27", "cap_share"] == pytest.approx(77_000_000 / CAP_2026)

    def test_seasons_without_cap_rules_have_no_lines(self, contract_lab: Lab) -> None:
        outlook = contract_lab.contracts.outlook(BOS)
        assert outlook.loc[["2027-28", "2028-29"], "salary_cap"].isna().all()
        assert outlook.loc[["2027-28", "2028-29"], "cap_share"].isna().all()

    def test_dead_money_runs_on(self, contract_lab: Lab) -> None:
        outlook = contract_lab.contracts.outlook(NYK)
        assert outlook.index.tolist() == ["2026-27", "2027-28"]
        assert outlook["dead_money"].tolist() == [7_000_000, 3_000_000]
        assert outlook.loc["2027-28", "team_salary"] == 3_000_000


class TestSummary:
    def test_what_a_season_adds_up_to(self, contract_lab: Lab) -> None:
        summary = contract_lab.contracts.summary("2026-27")
        assert (summary.contracts, summary.players, summary.teams) == (11, 10, 2)
        assert summary.total_salary == 301_600_000
        assert summary.dead_money == 7_000_000
        assert summary.two_way_salary == 600_000
        assert summary.unassigned == 1

    def test_a_season_without_contracts(self, lab: Lab) -> None:
        summary = lab.contracts.summary("2026-27")
        assert (summary.contracts, summary.total_salary, summary.unassigned) == (0, 0, 0)


def test_outlook_cap_share_counts_dead_money(contract_lab: Lab) -> None:
    """New York's 212M is 205M under contract plus 7M of dead money."""
    outlook = contract_lab.contracts.outlook(NYK)
    assert outlook.loc["2026-27", "cap_share"] == pytest.approx(212_000_000 / CAP_2026)


class TestMidSeasonMoves:
    """A player paid by two teams in one season, from the ``priced_lab`` fixture."""

    def test_each_team_owes_its_share(self, priced_lab: Lab) -> None:
        owed = priced_lab.contracts.table("2026-27").set_index("contract_id")
        assert owed.loc[f"{BRIDGES}-{BOS}-2026-27", "salary"] == 10_000_000
        assert owed.loc[f"{BRIDGES}-{NYK}-2026-27", "salary"] == 15_000_000
        payrolls = priced_lab.contracts.team_payrolls("2026-27")
        assert payrolls.loc[BOS, "active_salary"] == 80_000_000
        assert payrolls.loc[NYK, "active_salary"] == 15_000_000

    def test_the_players_salary_is_the_sum_and_the_contract_that_runs_on(
        self, priced_lab: Lab
    ) -> None:
        salaries = priced_lab.contracts.salaries("2026-27")
        assert salaries.index.is_unique
        bridges = salaries.loc[BRIDGES]
        assert bridges["salary"] == 25_000_000
        assert bridges["salary_cap_pct"] == pytest.approx(25_000_000 / CAP_2026)
        assert bridges["years_remaining"] == 1  # New York's contract runs into 2027-28
        later = priced_lab.contracts.salaries("2027-28").loc[BRIDGES]
        assert (later["salary"], later["option"], later["years_remaining"]) == (
            16_000_000,
            "team",
            0,
        )
