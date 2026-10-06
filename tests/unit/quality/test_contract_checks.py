"""Quality checks on contract data.

The baseline pairs the real fixture teams and players with an invented contract file:
fifteen players on each of the two fixture teams, each paid an invented round salary.
"""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.pipelines.normalize import BUILT_TABLES
from front_office.processing.cap_rules import cap_rules_frame
from front_office.processing.contracts import build_contracts
from front_office.quality import Severity, all_checks, run_checks
from tests.helpers import snapshot

BOS, NYK = 1610612738, 1610612752


@pytest.fixture
def tables(normalized, season_rules) -> dict[str, pd.DataFrame]:
    frames = {name: frame.copy() for name, frame in normalized.frames.items()}
    rostered = frames["team_rosters"]
    rostered = rostered[rostered["season"] == "2026-27"]
    lines = ["player_id,team,2026-27,2027-28,2028-29"]
    for team_id, abbreviation in ((BOS, "BOS"), (NYK, "NYK")):
        roster = rostered[rostered["team_id"] == team_id].head(15)
        for rank, player_id in enumerate(roster["player_id"], start=1):
            lines.append(f"{player_id},{abbreviation},{rank}000000,{rank}100000,")
    payload = {
        "filename": "invented.csv",
        "source_label": "invented for tests",
        "as_of": "2026-10-01",
        "text": "\n".join(lines) + "\n",
    }
    built = build_contracts(
        snapshot("contracts", payload, source="contract_file"),
        players=frames["players"],
        teams=frames["teams"],
        caps={rules.season: rules.salary_cap for rules in season_rules},
    )
    assert built.unmatched == []
    frames["contracts"] = built.contracts
    frames["contract_years"] = built.contract_years
    frames["salary_cap_rules"] = cap_rules_frame(season_rules)
    return frames


def results(tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    return {result.check: result for result in run_checks(tables, all_checks(BUILT_TABLES))}


CONTRACT_CHECKS = (
    "contracts.totals_match_years",
    "contracts.player_id_exists",
    "contracts.team_id_exists",
    "contract_years.contract_id_exists",
    "contract_years.player_id_exists",
    "contract_years.team_id_exists",
    "contract_years.one_active_contract_per_player_team_season",
    "contract_years.cap_shares_are_consistent",
    "contract_years.salaries_are_plausible",
)


def test_a_consistent_contract_file_passes(tables) -> None:
    found = results(tables)
    for name in CONTRACT_CHECKS:
        assert found[name].passed, (name, found[name].examples)
        assert found[name].examined > 0, name


def test_empty_contract_tables_pass_with_nothing_examined(normalized) -> None:
    found = results(dict(normalized.frames))
    for name in CONTRACT_CHECKS + ("contract_years.teams_have_plausible_rosters",):
        assert found[name].passed and found[name].examined == 0, name


class TestTotals:
    def test_a_total_that_disagrees_with_its_seasons(self, tables) -> None:
        contracts = tables["contracts"]
        contracts.loc[contracts.index[0], "total_salary"] += 1
        result = results(tables)["contracts.totals_match_years"]
        assert result.failures == 1
        assert result.severity is Severity.ERROR
        assert "total_in_years=" in result.examples[0]

    def test_a_missing_season_row(self, tables) -> None:
        years = tables["contract_years"]
        tables["contract_years"] = years.drop(index=years.index[0])
        assert results(tables)["contracts.totals_match_years"].failures == 1

    def test_a_wrong_last_season(self, tables) -> None:
        contracts = tables["contracts"]
        contracts.loc[contracts.index[0], "last_season"] = "2030-31"
        assert results(tables)["contracts.totals_match_years"].failures == 1


class TestCapShare:
    def test_a_share_that_does_not_match_the_salary(self, tables) -> None:
        years = tables["contract_years"]
        row = years.index[years["season"] == "2026-27"][0]
        years.loc[row, "salary_cap_pct"] *= 2
        result = results(tables)["contract_years.cap_shares_are_consistent"]
        assert result.failures == 1
        assert "expected=" in result.examples[0]

    def test_a_missing_share_where_a_cap_is_configured(self, tables) -> None:
        years = tables["contract_years"]
        row = years.index[years["season"] == "2026-27"][0]
        years.loc[row, "salary_cap_pct"] = float("nan")
        assert results(tables)["contract_years.cap_shares_are_consistent"].failures == 1

    def test_a_share_where_no_cap_is_configured(self, tables) -> None:
        years = tables["contract_years"]
        future = years.index[years["season"] == "2027-28"]
        assert years.loc[future, "salary_cap_pct"].isna().all()
        years.loc[future[0], "salary_cap_pct"] = 0.1
        assert results(tables)["contract_years.cap_shares_are_consistent"].failures == 1

    def test_a_changed_cap_invalidates_every_share_for_that_season(self, tables) -> None:
        rules = tables["salary_cap_rules"]
        rules.loc[rules["season"] == "2026-27", "salary_cap"] += 1_000_000
        result = results(tables)["contract_years.cap_shares_are_consistent"]
        assert result.failures == 30


CHECK_ONE_ACTIVE = "contract_years.one_active_contract_per_player_team_season"


def with_second_contract(tables, *, other_team: bool = False, **changes) -> None:
    """Add a copy of the first contract, and of its first season, with ``changes``.

    ``other_team`` moves the copy to the fixture team the first contract is not with.
    """
    contracts, years = tables["contracts"], tables["contract_years"]
    first = contracts.iloc[0]
    if other_team:
        changes["team_id"] = NYK if first["team_id"] == BOS else BOS
    second = contracts.iloc[[0]].assign(contract_id="second", **changes)
    second_year = years[years["contract_id"] == first["contract_id"]].iloc[[0]]
    second_year = second_year.assign(contract_id="second")
    if "team_id" in changes:
        second_year = second_year.assign(team_id=changes["team_id"])
    tables["contracts"] = pd.concat([contracts, second], ignore_index=True)
    tables["contract_years"] = pd.concat([years, second_year], ignore_index=True)


class TestOneActiveContract:
    def test_two_active_contracts_with_one_team_in_one_season(self, tables) -> None:
        with_second_contract(tables)
        result = results(tables)[CHECK_ONE_ACTIVE]
        assert result.failures == 1
        assert "active_contracts=2" in result.examples[0]

    def test_a_move_between_teams_within_a_season_is_allowed(self, tables) -> None:
        """Each team owed its share; the player had one contract, carried by two teams."""
        with_second_contract(tables, other_team=True)
        assert results(tables)[CHECK_ONE_ACTIVE].passed

    def test_a_two_way_contract_converted_to_a_standard_one_is_allowed(self, tables) -> None:
        with_second_contract(tables, contract_type="two_way")
        assert results(tables)[CHECK_ONE_ACTIVE].passed

    def test_dead_money_alongside_an_active_contract_is_allowed(self, tables) -> None:
        with_second_contract(tables, other_team=True, status="dead_money")
        assert results(tables)[CHECK_ONE_ACTIVE].passed


class TestPlausibility:
    @pytest.mark.parametrize("share", [0.9, 0.00001])
    def test_an_implausible_salary_is_a_warning(self, tables, share: float) -> None:
        years = tables["contract_years"]
        row = years.index[years["season"] == "2026-27"][0]
        years.loc[row, "salary_cap_pct"] = share
        result = results(tables)["contract_years.salaries_are_plausible"]
        assert result.failures == 1
        assert result.severity is Severity.WARNING

    def test_seasons_without_a_cap_are_not_judged(self, tables) -> None:
        result = results(tables)["contract_years.salaries_are_plausible"]
        assert result.examined == 30  # only the 2026-27 seasons have a cap share


class TestRosterCoverage:
    def test_teams_missing_from_the_file_are_reported(self, tables) -> None:
        result = results(tables)["contract_years.teams_have_plausible_rosters"]
        assert result.examined == 30
        assert result.failures == 28  # every team but the two the file covers
        assert result.severity is Severity.WARNING
        assert "standard_contracts=0" in result.examples[0]

    def test_a_thin_roster_is_reported(self, tables) -> None:
        years = tables["contract_years"]
        boston = years.index[(years["team_id"] == BOS) & (years["season"] == "2026-27")]
        tables["contract_years"] = years.drop(index=boston[:8])
        result = results(tables)["contract_years.teams_have_plausible_rosters"]
        assert result.failures == 29

    def test_two_way_and_dead_money_do_not_count_as_roster_spots(self, tables) -> None:
        contracts = tables["contracts"]
        boston = contracts.index[contracts["team_id"] == BOS]
        contracts.loc[boston[:4], "contract_type"] = "two_way"
        contracts.loc[boston[4:7], "status"] = "dead_money"
        result = results(tables)["contract_years.teams_have_plausible_rosters"]
        assert result.failures == 29  # Boston now shows 8 standard contracts

    def test_only_the_first_season_of_the_file_is_judged(self, tables) -> None:
        years = tables["contract_years"]
        tables["contract_years"] = years[years["season"] != "2027-28"]
        assert results(tables)["contract_years.teams_have_plausible_rosters"].failures == 28
