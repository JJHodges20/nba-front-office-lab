"""The value service: what the model says of players, and the model laid out for reading.

``value_lab`` holds the invented league valued by planted weights, so every number can
be checked against ``tests.value_reference``. ``lab`` is the fixture store valued by
the model the lab ships.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from front_office.config import archetypes_path, load_archetypes, load_settings, value_model_path
from front_office.domain.schema import Provenance
from front_office.domain.value_model import Comparison, ValueModel
from front_office.modeling.archetypes import persistence
from front_office.modeling.value import TERM_KEYS
from front_office.modeling.value.catalog import (
    PART_KEYS,
    PROJECTION_KEYS,
    SEASON_KEYS,
    VALUE_METRICS,
)
from front_office.services import Lab, ModelCard, ValueStatus
from front_office.services.value import (
    HISTORY_COLUMNS,
    MONEY_COLUMNS,
    PROJECTION_COLUMNS,
    ROLE_COLUMNS,
    ROLE_PLAYER_COLUMNS,
    ROLE_SUMMARY_COLUMNS,
    SEASON_COLUMNS,
    baseline_table,
    comparison_table,
    term_table,
)
from tests.conftest import VALUE_SPEC
from tests.unit.services.conftest import (
    ANUNOBY,
    BRIDGES,
    BROWN,
    BRUNSON,
    HART,
    PRITCHARD,
    TATUM,
    TOWNS,
    WHITE,
)
from tests.value_reference import DEFENSE, OFFENSE, entering, season_impacts


class TestCatalog:
    def test_every_value_column_a_screen_shows_is_a_metric(self) -> None:
        assert SEASON_KEYS == (
            "impact", "impact_offense", "impact_defense", "wins_added", "minutes_share",
            "reliability",
        )  # fmt: skip
        assert len(PART_KEYS) == 9 and PART_KEYS[-1] == "impact_from_baseline"
        assert PROJECTION_KEYS[0] == "projected_impact" and len(PROJECTION_KEYS) == 6
        assert VALUE_METRICS.keys == (*SEASON_KEYS, *PART_KEYS, *PROJECTION_KEYS)

    def test_what_a_model_produced_is_marked_modeled(self) -> None:
        derived = {"minutes_share", "reliability", "projection_reliability"}
        for spec in VALUE_METRICS:
            expected = Provenance.DERIVED if spec.key in derived else Provenance.MODELED
            assert spec.provenance is expected, spec.key
            assert spec.description.endswith(".") and len(spec.label) <= 8, spec.key

    def test_the_service_hands_out_the_catalog(self, lab: Lab) -> None:
        assert lab.value.metrics is VALUE_METRICS


class TestStatus:
    def test_a_valued_lab(self, value_lab: Lab) -> None:
        status = value_lab.value.status()
        assert isinstance(status, ValueStatus)
        assert status.is_fitted and status.is_available and not status.needs_build
        assert (status.revision, status.applied_revision) == (1, "r1")
        assert status.fitted_through == "2008-09" and status.finished_since == ()
        assert status.seasons[0] == "2008-09" and status.seasons[-1] == "2000-01"
        assert len(status.seasons) == 9
        assert status.upcoming == "2009-10"

    def test_the_fixture_lab_is_valued_by_the_shipped_model(self, lab: Lab) -> None:
        status = lab.value.status()
        assert status.is_available and not status.needs_build
        assert (status.seasons, status.upcoming) == (("2025-26",), "2026-27")
        assert status.applied_revision == f"r{status.revision}"

    @pytest.fixture
    def copy(self, value_home: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
        target = tmp_path / "copy"
        shutil.copytree(value_home, target)
        return target

    def test_a_model_fitted_since_the_build_needs_a_build(
        self, copy: Path, value_model: ValueModel
    ) -> None:
        from front_office.config import save_value_model

        save_value_model(copy / "configs", value_model.model_copy(update={"revision": 2}))
        with Lab(load_settings(copy)) as opened:
            status = opened.value.status()
        assert status.needs_build and (status.revision, status.applied_revision) == (2, "r1")

    def test_without_a_model_file_what_was_built_is_still_shown(self, copy: Path) -> None:
        value_model_path(copy / "configs").unlink()
        with Lab(load_settings(copy)) as opened:
            status = opened.value.status()
            assert opened.value.model() is None and opened.value.card() is None
        assert not status.is_fitted and status.is_available and not status.needs_build
        assert (status.revision, status.fitted_at, status.fitted_through) == (None, None, None)

    def test_seasons_finished_since_the_fit_are_named(
        self, copy: Path, value_model: ValueModel
    ) -> None:
        from front_office.config import save_value_model

        older = value_model.fitted_on.model_copy(update={"last_season": "2006-07"})
        save_value_model(copy / "configs", value_model.model_copy(update={"fitted_on": older}))
        with Lab(load_settings(copy)) as opened:
            assert opened.value.status().finished_since == ("2007-08", "2008-09")


class TestSeason:
    def test_everyone_who_played_most_valuable_first(self, value_lab: Lab, value_league) -> None:
        season = value_lab.value.season("2005-06")
        assert tuple(season.columns) == SEASON_COLUMNS and season.index.name == "player_id"
        assert set(season.index) == {line.player_id for line in value_league.lines[2005]}
        assert season["wins_added"].is_monotonic_decreasing
        assert season[list(SEASON_KEYS)].notna().all().all()

    def test_the_numbers_are_the_models(self, value_lab: Lab, value_league) -> None:
        season = value_lab.value.season("2005-06")
        expected = season_impacts(value_league, 2005, VALUE_SPEC)
        for player in list(season.index)[::9]:
            row = season.loc[player]
            assert row["impact"] == pytest.approx(expected[player]["impact"])
            assert row["impact_offense"] == pytest.approx(expected[player]["offense"])
            assert row["impact_from_creation"] == pytest.approx(expected[player]["creation"])

    def test_identity_comes_from_the_season_and_the_player_tables(
        self, value_lab: Lab, value_league
    ) -> None:
        season = value_lab.value.season("2005-06")
        line = value_league.lines[2005][5]
        row = season.loc[line.player_id]
        assert row["player_name"] == f"Player {line.player_id}"
        assert (row["team_id"], row["team"]) == (line.team_id, f"T{line.team_id:02d}")
        assert row["team_name"] == f"City {line.team_id} Team {line.team_id}"
        assert (row["age"], row["games_played"]) == (line.age, line.games)
        assert row["minutes"] == pytest.approx(line.minutes)
        assert row["position_group"] in {"Guard", "Forward", "Center"}

    def test_a_player_the_model_could_not_rate_is_left_out_not_shown_blank(
        self, value_home: Path, tmp_path: Path, value_lab: Lab
    ) -> None:
        from sqlalchemy import text

        from front_office.storage import Database

        target = tmp_path / "copy"
        shutil.copytree(value_home, target)
        whole = value_lab.value.season("2006-07")
        unrated = int(whole.index[4])
        settings = load_settings(target)
        with Database(settings.database_path) as database, database.begin() as connection:
            connection.execute(
                text(
                    "UPDATE player_value_scores SET impact = NULL "
                    "WHERE player_id = :player AND season = '2006-07'"
                ),
                {"player": unrated},
            )
        with Lab(settings) as opened:
            season = opened.value.season("2006-07")
        assert unrated not in season.index and len(season) == len(whole) - 1
        assert season["impact"].notna().all()

    def test_a_season_that_has_not_been_valued_is_empty(self, value_lab: Lab) -> None:
        for season in ("2009-10", "1990-91"):
            found = value_lab.value.season(season)
            assert found.empty and tuple(found.columns) == SEASON_COLUMNS

    def test_on_the_fixture_lab(self, lab: Lab) -> None:
        season = lab.value.season("2025-26")
        assert len(season) == 41 and season.loc[TATUM, "player_name"] == "Jayson Tatum"
        assert season.loc[TATUM, "team"] == "BOS"
        assert -10 < season["impact"].min() and season["impact"].max() < 12


class TestProjections:
    def test_everyone_with_a_past_most_projected_wins_first(
        self, value_lab: Lab, value_league
    ) -> None:
        projected = value_lab.value.projections()
        assert tuple(projected.columns) == PROJECTION_COLUMNS
        known = entering(value_league, 2009, VALUE_SPEC)
        assert set(projected.index) == set(known)
        assert projected["projected_wins"].is_monotonic_decreasing
        assert projected["projected_impact"].notna().all()

    def test_the_last_season_on_record_is_recalled(self, value_lab: Lab, value_league) -> None:
        projected = value_lab.value.projections()
        last = {line.player_id for line in value_league.lines[2008]}
        played_last = projected[projected.index.isin(last)]
        assert (played_last["last_season"] == "2008-09").all()
        earlier = projected[~projected.index.isin(last)]
        assert len(earlier) > 0 and (earlier["last_season"] < "2008-09").all()
        player = played_last.index[0]
        impact = season_impacts(value_league, 2008, VALUE_SPEC)[player]["impact"]
        assert projected.loc[player, "last_impact"] == pytest.approx(impact)
        assert 0 < projected.loc[player, "last_minutes_share"] < 1

    def test_the_team_is_the_one_the_player_is_with_now(self, value_lab: Lab, value_league) -> None:
        projected = value_lab.value.projections()
        now = {line.player_id: line.team_id for line in value_league.lines[2008]}
        player = next(iter(now))
        assert projected.loc[player, "team_id"] == now[player]
        assert projected.loc[player, "team"] == f"T{now[player]:02d}"
        gone = projected[~projected.index.isin(now)]
        assert gone["team"].isna().all() and gone["player_name"].notna().all()

    def test_nothing_ahead_nothing_projected(self, value_home: Path, tmp_path: Path) -> None:
        from sqlalchemy import text

        from front_office.storage import Database

        target = tmp_path / "copy"
        shutil.copytree(value_home, target)
        settings = load_settings(target)
        with Database(settings.database_path) as database, database.begin() as connection:
            connection.execute(text("DELETE FROM player_value_scores WHERE impact IS NULL"))
        with Lab(settings) as opened:
            assert opened.value.status().upcoming is None
            found = opened.value.projections()
        assert found.empty and tuple(found.columns) == PROJECTION_COLUMNS


class TestPlayer:
    def test_every_season_oldest_first_then_the_projection(
        self, value_lab: Lab, value_league
    ) -> None:
        seasons = [
            year for year in value_league.years
            if any(line.player_id == 30 for line in value_league.lines[year])
        ]  # fmt: skip
        history = value_lab.value.player(30)
        assert tuple(history.columns) == HISTORY_COLUMNS
        labels = history["season"].tolist()
        assert labels == sorted(labels)
        played = history[history["impact"].notna()]
        assert len(played) == len(seasons)
        if labels[-1] == "2009-10":
            assert pd.isna(history["impact"].iloc[-1]) and pd.isna(history["team"].iloc[-1])
            assert pd.notna(history["projected_impact"].iloc[-1])

    def test_the_team_is_the_one_each_season_ended_with(self, value_lab: Lab, value_league) -> None:
        line = value_league.lines[2004][10]
        history = value_lab.value.player(line.player_id).set_index("season")
        assert history.loc["2004-05", "team"] == f"T{line.team_id:02d}"

    def test_an_unknown_player_has_no_history(self, value_lab: Lab) -> None:
        found = value_lab.value.player(999_999)
        assert found.empty and tuple(found.columns) == HISTORY_COLUMNS

    def test_the_parts_of_a_season_add_up_to_its_impact(self, value_lab: Lab, value_league) -> None:
        line = value_league.lines[2006][20]
        parts = value_lab.value.parts(line.player_id, "2006-07")
        assert list(parts.columns) == ["key", "label", "description", "value"]
        assert parts["key"].tolist() == list(PART_KEYS)
        assert parts["label"].tolist() == [
            "Scoring efficiency", "Creation", "Spacing", "Rebounding", "Ball security",
            "Defensive activity", "On-court results", "Team results", "Assumed",
        ]  # fmt: skip
        expected = season_impacts(value_league, 2006, VALUE_SPEC)[line.player_id]
        assert parts["value"].sum() == pytest.approx(expected["impact"])
        assert parts.set_index("label").at["Rebounding", "value"] == pytest.approx(
            expected["rebounding"]
        )

    @pytest.mark.parametrize("season", ["2009-10", "1990-91"])
    def test_no_impact_no_parts(self, value_lab: Lab, value_league, season: str) -> None:
        player = value_league.lines[2008][3].player_id
        found = value_lab.value.parts(player, season)
        assert found.empty and list(found.columns) == ["key", "label", "description", "value"]


@pytest.fixture(scope="module")
def card(lab: Lab) -> ModelCard:
    """The model the lab ships, read through the fixture lab."""
    return lab.value.card()


class TestTheModelCard:
    def test_every_term_is_named_grouped_and_given_its_intervals(self, card: ModelCard) -> None:
        terms = card.terms
        assert terms["key"].tolist() == list(TERM_KEYS)
        assert terms["label"].notna().all() and terms["description"].str.endswith(".").all()
        assert terms["group"].tolist()[:4] == [
            "Scoring efficiency",
            "Creation",
            "Creation",
            "Creation",
        ]
        assert set(terms["group"].tail(4)) == {"Levels"}
        for side in ("offense", "defense", "net"):
            assert (terms[f"{side}_low"] <= terms[side]).all()
            assert (terms[side] <= terms[f"{side}_high"]).all()
        assert (terms["net"] - terms["offense"] - terms["defense"]).abs().max() < 1e-9

    def test_known_means_the_data_can_tell_the_term_from_nothing(self, card: ModelCard) -> None:
        terms = card.terms.set_index("key")
        excludes_zero = (terms["net_low"] > 0) | (terms["net_high"] < 0)
        assert (terms["known"] == excludes_zero).all()
        assert terms.at["team_def", "known"] and not terms.at["fta", "known"]

    def test_baselines_put_the_model_among_them_smallest_error_first(self, card: ModelCard) -> None:
        table = card.baselines
        assert len(table) == 7 and table["rmse"].is_monotonic_increasing
        own = table.iloc[0]
        assert (own["key"], own["label"]) == ("value_model", "Value model")
        assert own["rmse"] == card.model.validation.net.rmse and pd.isna(own["difference"])
        others = table.iloc[1:]
        assert (others["difference"] < 0).all() and others["distinguishable"].all()
        assert others["difference"].tolist() == pytest.approx(
            (own["rmse"] - others["rmse"]).tolist(), abs=2e-6
        )

    def test_ablations_put_the_costliest_omission_first(self, card: ModelCard) -> None:
        table = card.ablations
        assert len(table) == 10 and table["difference"].is_monotonic_decreasing
        assert table["key"].iloc[0] == "team_context"
        assert set(table["distinguishable"]) == {True, False}

    def test_the_backtest_names_its_teams_and_measures_its_misses(self, card: ModelCard) -> None:
        backtest = card.backtest
        assert len(backtest) == card.model.validation.team_seasons
        assert backtest["team"].notna().all() and backtest["team_name"].notna().all()
        assert (backtest["error"] - (backtest["predicted"] - backtest["actual"])).abs().max() < 1e-9
        rmse = (backtest["error"] ** 2).mean() ** 0.5
        assert rmse == pytest.approx(card.model.validation.net.rmse, abs=1e-3)
        seasons = card.by_season
        assert seasons["season"].tolist() == sorted(seasons["season"])
        assert seasons["teams"].sum() == len(backtest)

    def test_a_model_with_no_backtest_has_an_empty_one(self, value_lab: Lab) -> None:
        card = value_lab.value.card()
        assert card.backtest.empty and "error" in card.backtest.columns
        assert card.by_season.empty and card.ablations.empty
        assert card.baselines["key"].tolist() == ["value_model"]


class TestTables:
    def test_a_term_table_carries_the_planted_weights(self, value_model: ValueModel) -> None:
        terms = term_table(value_model).set_index("key")
        assert terms.at["blk", "defense"] == DEFENSE["blk"]
        assert terms.at["blk", "net"] == pytest.approx(OFFENSE["blk"] + DEFENSE["blk"])
        assert (
            terms.at["blk", "label"] == "Blocks"
            and terms.at["blk", "group"] == "Defensive activity"
        )
        assert terms.at["age", "label"] == "Age, per year"

    def test_a_comparison_table_says_which_can_be_told_apart(self) -> None:
        items = (
            Comparison(key="a", label="A", rmse=3.2, mae=2.5, difference=0.2, low=0.1, high=0.3),
            Comparison(key="b", label="B", rmse=3.1, mae=2.4, difference=0.1, low=-0.1, high=0.3),
        )
        table = comparison_table(items)
        assert table["distinguishable"].tolist() == [True, False]
        assert table["key"].tolist() == ["a", "b"]
        assert comparison_table(()).empty

    def test_the_baseline_table_is_sorted_whatever_order_the_model_lists_them(
        self, value_model: ValueModel
    ) -> None:
        worse = Comparison(key="w", label="W", rmse=5.0, mae=4.0, difference=-5.0, low=-6, high=-4)
        better = Comparison(key="b", label="B", rmse=-1.0, mae=0.0, difference=1.0, low=0.5, high=2)
        tested = value_model.validation.model_copy(update={"baselines": (worse, better)})
        table = baseline_table(value_model.model_copy(update={"validation": tested}))
        assert table["key"].tolist() == ["b", "value_model", "w"]


UNSEEN = 99_999
"""A player under contract who has never played: nothing to value."""


class TestValueForMoney:
    """``contract_lab`` holds invented salaries for 2026-27 to 2028-29: nine players of
    Boston and New York under contract, valued by the model the lab ships."""

    def test_the_season_still_to_be_played_is_judged_on_its_projection(
        self, contract_lab: Lab
    ) -> None:
        money = contract_lab.value.for_money("2026-27")
        assert (money.season, money.basis) == ("2026-27", "projected")
        players = money.players
        assert tuple(players.columns) == MONEY_COLUMNS and players.index.name == "player_id"
        assert set(players.index) == {
            TATUM, BROWN, PRITCHARD, WHITE, BRUNSON, TOWNS, BRIDGES, ANUNOBY, HART,
        }  # fmt: skip
        assert money.unvalued == 0
        projected = contract_lab.value.projections()
        for player in (TATUM, BRUNSON, HART):
            row = players.loc[player]
            assert row["rating"] == projected.loc[player, "projected_impact"]
            assert row["wins"] == projected.loc[player, "projected_wins"]

    def test_salaries_are_the_players_own(self, contract_lab: Lab) -> None:
        players = contract_lab.value.for_money("2026-27").players
        # Brown is under contract in Boston; the money New York still owes him is not his salary.
        assert players.loc[BROWN, "salary"] == 30_000_000
        assert players.loc[BROWN, "team"] == "BOS"
        assert players.loc[TATUM, "salary"] == 40_000_000
        assert players.loc[TATUM, "player_name"] == "Jayson Tatum"
        assert pd.isna(players.loc[HART, "team"])  # under contract to nobody in the file

    def test_contracts_that_do_not_pay_for_wins_give_no_price(self, contract_lab: Lab) -> None:
        from front_office.modeling.value.market import fit_market

        # The invented file pays its players without regard to what they are worth.
        money = contract_lab.value.for_money("2026-27")
        players = money.players
        assert fit_market(players["salary"], players["wins"]) is None
        assert money.market is None
        assert players["market_value"].isna().all() and players["surplus"].isna().all()
        assert players["cost_per_win"].notna().any()
        # With no surplus to order by, the players worth the most come first.
        assert players["wins"].is_monotonic_decreasing

    def test_a_later_season_of_a_contract_is_not_valued(self, contract_lab: Lab) -> None:
        money = contract_lab.value.for_money("2027-28")
        assert money.basis is None and money.market is None
        assert money.players.empty and tuple(money.players.columns) == MONEY_COLUMNS
        assert money.unvalued == 2  # Tatum and Pritchard are the two still under contract

    def test_a_season_without_salaries_has_nobody_to_value(self, lab: Lab) -> None:
        money = lab.value.for_money("2026-27")
        assert money.basis == "projected" and money.players.empty and money.unvalued == 0

    def test_a_played_season_is_judged_on_what_it_showed(self, value_home, tmp_path) -> None:
        from sqlalchemy import text

        from front_office.modeling.value.market import fit_market, surplus
        from front_office.storage import Database

        # The invented league has no contract file, and a build would wipe its tables, so
        # the salaries are written straight into the two contract tables of a copy.
        target = tmp_path / "copy"
        shutil.copytree(value_home, target)
        settings = load_settings(target)
        with Lab(settings) as opened:
            season = opened.value.season("2008-09")
        # The six most valuable players, the best of them paid the most.
        chosen = season.index[:6].tolist()[::-1]
        with Database(settings.database_path) as database, database.begin() as connection:
            # And one more under contract whom the model has never seen.
            for number, player in enumerate([*chosen, UNSEEN], start=1):
                connection.execute(
                    text(
                        "INSERT INTO contracts (contract_id, player_id, player_name, team_id, "
                        "contract_type, status, first_season, last_season, seasons, "
                        "total_salary, source_label, as_of_date) VALUES (:id, :player, :name, "
                        "101, 'standard', 'active', '2008-09', '2008-09', 1, :salary, "
                        "'invented', '2008-10-01')"
                    ),
                    {
                        "id": number,
                        "player": player,
                        "name": f"Player {player}",
                        "salary": number * 1_000_000,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO contract_years (contract_id, season, player_id, team_id, "
                        "salary, years_remaining) VALUES (:id, '2008-09', :player, 101, "
                        ":salary, 0)"
                    ),
                    {"id": number, "player": player, "salary": number * 1_000_000},
                )
        with Lab(settings) as opened:
            money = opened.value.for_money("2008-09")
        players = money.players
        assert money.basis == "played" and len(players) == 6
        # A salary with no value beside it is counted and kept out of the market.
        assert money.unvalued == 1 and UNSEEN not in players.index
        assert players["wins"].notna().all()
        for player in chosen:
            assert players.loc[player, "wins"] == season.loc[player, "wins_added"]
            assert players.loc[player, "rating"] == season.loc[player, "impact"]
        assert players.loc[chosen[-1], "salary"] == 6_000_000

        # Paid more for more wins, so a price can be read off them.
        again = fit_market(players["salary"], players["wins"])
        assert money.market.price_per_win == pytest.approx(again.price_per_win)
        assert money.market.replacement_cost == pytest.approx(again.replacement_cost)
        assert money.market.contracts == 6 and money.market.price_per_win > 0
        expected = surplus(players["salary"], players["wins"], money.market)
        for column in expected.columns:
            assert players[column].tolist() == pytest.approx(expected[column].tolist())
        assert players["surplus"].is_monotonic_decreasing
        # Against a line fitted to these same contracts, the surpluses balance out.
        assert players["surplus"].sum() == pytest.approx(0, abs=1.0)
        assert (players["team"] == "T101").all()


class TestRoles:
    """``lab`` is the fixture store given roles by the shipped rules; ``value_lab`` the
    invented league, whose table is read back to check what the service makes of it."""

    SEASON = "2006-07"

    def test_the_definitions_are_the_ones_on_file(self, value_lab: Lab) -> None:
        assert value_lab.value.archetypes() == load_archetypes(value_lab.settings.config_dir)

    def test_a_players_roles_are_named_the_main_one_first_apart(self, lab: Lab) -> None:
        roles = lab.value.roles("2025-26")
        assert tuple(roles.columns) == ROLE_COLUMNS and roles.index.name == "player_id"
        assert roles.loc[TATUM].tolist() == [
            "Primary Creator", "Primary Creator, Perimeter Defender",
        ]  # fmt: skip
        # Every role filled is listed in the order the roles are defined, whichever is
        # the main one.
        assert roles.loc[BRIDGES].tolist() == [
            "Switchable Wing", "Perimeter Defender, Switchable Wing",
        ]  # fmt: skip
        assert roles.loc[ANUNOBY].tolist() == [
            "Perimeter Defender", "Perimeter Defender, Switchable Wing",
        ]  # fmt: skip
        assert roles.loc[BRUNSON].tolist() == ["Primary Creator", "Primary Creator"]

    def test_only_players_who_fill_a_role_appear(self, lab: Lab) -> None:
        roles = lab.value.roles("2025-26")
        table = lab.read("player_archetypes", {"season": "2025-26"})
        assert set(roles.index) == set(table.loc[table["fills"], "player_id"])
        assert TOWNS not in roles.index and HART not in roles.index
        assert TOWNS in set(table["player_id"])  # scored, and short of every cut-off
        assert roles["role"].notna().all()

    def test_a_season_without_roles_is_empty(self, lab: Lab) -> None:
        roles = lab.value.roles("1996-97")
        assert roles.empty and tuple(roles.columns) == ROLE_COLUMNS
        assert roles.index.name == "player_id"

    def test_a_role_no_longer_defined_is_not_shown(self, value_home: Path, tmp_path: Path) -> None:
        # The table was built with eight roles; the file now defines seven.
        target = tmp_path / "copy"
        shutil.copytree(value_home, target)
        path = archetypes_path(target / "configs")
        text = path.read_text(encoding="utf-8")
        start = text.index("  - key: connector")
        path.write_text(text[:start], encoding="utf-8")
        with Lab(load_settings(target)) as opened, Lab(load_settings(value_home)) as whole:
            before, after = whole.value.roles(self.SEASON), opened.value.roles(self.SEASON)
            summary = opened.value.role_summary(self.SEASON)
        assert before["roles"].str.contains("Connector").any()
        assert not after["roles"].str.contains("Connector").any()
        only = before.index[before["roles"] == "Connector"]
        assert len(only) > 0 and not set(only) & set(after.index)
        assert "connector" not in summary["archetype"].tolist() and len(summary) == 7

    def test_who_fills_a_role_highest_score_first(self, value_lab: Lab) -> None:
        players = value_lab.value.role_players(self.SEASON, "floor_spacer")
        table = value_lab.read("player_archetypes", {"season": self.SEASON})
        mine = table[(table["archetype"] == "floor_spacer") & table["fills"]]
        assert tuple(players.columns) == ROLE_PLAYER_COLUMNS
        assert players.index.name == "player_id" and len(players) == len(mine) > 5
        assert set(players.index) == set(mine["player_id"])
        assert players["score"].is_monotonic_decreasing and players["score"].min() >= 67
        expected = mine.set_index("player_id")
        assert players["score"].to_dict() == expected["score"].to_dict()
        assert players["is_primary"].to_dict() == expected["is_primary"].to_dict()

    def test_each_is_shown_with_what_the_model_makes_of_them(self, value_lab: Lab) -> None:
        players = value_lab.value.role_players(self.SEASON, "rim_protector")
        season = value_lab.value.season(self.SEASON)
        roles = value_lab.value.roles(self.SEASON)
        for column in ("player_name", "team", "team_id", "position", "age", "impact", "wins_added"):
            assert players[column].tolist() == season[column].reindex(players.index).tolist()
        assert players["roles"].tolist() == roles["roles"].reindex(players.index).tolist()
        assert players["roles"].str.contains("Rim Protector").all()

    def test_a_role_nobody_fills_or_that_does_not_exist_has_no_players(
        self, value_lab: Lab
    ) -> None:
        for season, role in ((self.SEASON, "sixth_man"), ("1990-91", "floor_spacer")):
            players = value_lab.value.role_players(season, role)
            assert players.empty and tuple(players.columns) == ROLE_PLAYER_COLUMNS

    def test_the_summary_lays_out_each_rule_in_the_order_defined(self, value_lab: Lab) -> None:
        summary = value_lab.value.role_summary(self.SEASON)
        spec = value_lab.value.archetypes()
        assert tuple(summary.columns) == ROLE_SUMMARY_COLUMNS
        assert tuple(summary["archetype"]) == spec.keys
        first = summary.iloc[0]
        assert (first["name"], first["open_to"], first["measures"]) == (
            "Primary Creator", "Everyone", "usage, assist percentage",
        )  # fmt: skip
        assert first["description"] == spec["primary_creator"].description
        assert first["note"] == spec["primary_creator"].note
        by_key = summary.set_index("archetype")
        assert by_key["open_to"].to_dict() == {
            "primary_creator": "Everyone", "secondary_creator": "Everyone",
            "floor_spacer": "Everyone", "perimeter_defender": "Guards",
            "switchable_wing": "Wings", "rim_protector": "Big men", "stretch_big": "Big men",
            "connector": "Low-usage players",
        }  # fmt: skip
        assert by_key.at["rim_protector", "measures"] == "blocks, defensive impact"
        assert by_key["fills_at"].tolist() == [85, 67, 67, 67, 67, 67, 67, 67]
        assert by_key.at["secondary_creator", "fills_below"] == 85
        assert by_key["fills_below"].drop("secondary_creator").isna().all()

    def test_the_summary_counts_one_season_and_carries_over_on_every_season(
        self, value_lab: Lab
    ) -> None:
        summary = value_lab.value.role_summary(self.SEASON).set_index("archetype")
        table = value_lab.read("player_archetypes")
        mine = table[table["season"] == self.SEASON]
        for key, row in summary.iterrows():
            role = mine[mine["archetype"] == key]
            assert (row["scored"], row["filled"], row["primary"]) == (
                len(role), role["fills"].sum(), role["is_primary"].sum(),
            ), key  # fmt: skip
        assert summary["scored"].min() > 0 and summary["filled"].sum() > summary["primary"].sum()
        carried = persistence(table, value_lab.value.archetypes()).set_index("archetype")
        assert summary["again"].to_dict() == carried["again"].to_dict()
        assert summary["anyone"].to_dict() == carried["anyone"].to_dict()
        # A different season has different counts and the same record.
        other = value_lab.value.role_summary("2003-04").set_index("archetype")
        assert other["again"].to_dict() == summary["again"].to_dict()
        assert other["scored"].tolist() != summary["scored"].tolist()

    def test_a_season_without_roles_counts_nobody(self, value_lab: Lab) -> None:
        summary = value_lab.value.role_summary("1990-91")
        assert summary[["scored", "filled", "primary"]].to_numpy().sum() == 0
        assert summary["again"].notna().all() and len(summary) == 8

    def test_one_season_on_record_has_nothing_to_carry_over(self, lab: Lab) -> None:
        summary = lab.value.role_summary("2025-26")
        assert summary["again"].isna().all() and summary["anyone"].isna().all()
        assert summary.set_index("archetype").at["primary_creator", "filled"] == 3


def test_players_already_in_an_unfinished_season_keep_their_projection(
    value_lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    # While a season is being played, a player who has appeared in it has an impact for
    # it as well as a projection. The pool is everyone projected, not only the absent.
    upcoming = value_lab.value.status().upcoming
    assert upcoming is not None
    before = value_lab.value.projections()
    appeared = int(before.index[0])
    original = value_lab.read

    def reading(table, where=None, **kwargs):  # type: ignore[no-untyped-def]
        frame = original(table, where, **kwargs)
        if table == "player_value_scores" and where == {"season": upcoming}:
            frame = frame.copy()
            frame.loc[frame["player_id"] == appeared, "impact"] = 1.5
        return frame

    monkeypatch.setattr(value_lab, "read", reading)
    projected = value_lab.value.projections()
    assert appeared in projected.index
    assert len(projected) == len(before)
