"""The Player Value page: what it shows must be what the value service returns.

``value_home`` is the invented league valued by planted weights, with that model on
file. ``plain_home`` and ``contract_template`` are the fixture store valued by the model
the lab ships, without and with the invented contract file.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import text

from front_office.config import load_settings, load_value_model, save_value_model, value_model_path
from front_office.services import Lab
from front_office.storage import Database
from tests.helpers import BOS, TATUM, TOWNS
from tests.ui.conftest import drawn, figures, texts
from tests.ui.test_pages import frame_with
from wb import state

SEASON = "2006-07"


def service(home: Path):  # type: ignore[no-untyped-def]
    return Lab(load_settings(home))


@pytest.fixture
def copy(value_home: Path, tmp_path: Path) -> Path:
    """A private copy of the invented league's project, for tests that change it."""
    target = tmp_path / "home"
    shutil.copytree(value_home, target)
    return target


def pay(
    home: Path, season: str, salaries: dict[int, int], teams: dict[int, int] | None = None
) -> None:
    """Put invented salaries for one season straight into the two contract tables.

    Everyone is under contract to team 101 unless ``teams`` says otherwise.
    """
    teams = teams or {}
    settings = load_settings(home)
    with Database(settings.database_path) as database, database.begin() as connection:
        for number, (player, salary) in enumerate(salaries.items(), start=1):
            connection.execute(
                text(
                    "INSERT INTO contracts (contract_id, player_id, player_name, team_id, "
                    "contract_type, status, first_season, last_season, seasons, total_salary, "
                    "source_label, as_of_date) VALUES (:id, :player, :name, :team, 'standard', "
                    "'active', :season, :season, 1, :salary, 'invented', '2008-10-01')"
                ),
                {"id": number, "player": player, "name": f"Player {player}", "season": season,
                 "salary": salary, "team": teams.get(player, 101)},
            )  # fmt: skip
            connection.execute(
                text(
                    "INSERT INTO contract_years (contract_id, season, player_id, team_id, "
                    "salary, years_remaining) VALUES (:id, :season, :player, :team, :salary, 0)"
                ),
                {
                    "id": number,
                    "season": season,
                    "player": player,
                    "salary": salary,
                    "team": teams.get(player, 101),
                },
            )


class TestThePage:
    def test_it_says_what_it_is_and_what_kind_of_numbers_it_holds(
        self, page, value_home: Path
    ) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        said = texts(opened)
        assert [title.value for title in opened.title] == ["Player Value"]
        assert "tested on seasons it had not seen" in said and "Whole regular seasons" in said
        assert "Modeled" in said and "Derived" in said and "Measured" not in said
        assert [tab.label for tab in opened.tabs][:5] == [
            "Season", "Projections", "Roles", "Value for money", "The model",
        ]  # fmt: skip
        assert "Out of date" not in said

    def test_the_fixture_lab_is_valued_by_the_shipped_model(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "value")
        table = frame_with(opened, "impact", "reliability")
        with service(plain_home) as lab:
            season = lab.value.season("2025-26")
        assert len(table) == len(season) == 41
        assert "**Wins above replacement, 2025-26: the top 15**" in texts(opened)

    def test_before_a_model_is_fitted_it_says_how_to_fit_one(
        self, page, plain_home: Path, tmp_path: Path
    ) -> None:
        from front_office.pipelines.build import build_database

        home = tmp_path / "home"
        shutil.copytree(plain_home, home)
        value_model_path(home / "configs").unlink()
        assert build_database(load_settings(home)).loaded
        opened = page(home, "value")
        said = texts(opened)
        assert "**No value model has been fitted**" in said
        assert "fol value fit --write, then fol build" in said
        assert not opened.tabs and not opened.dataframe

    def test_a_model_on_file_that_was_never_applied_asks_for_a_build(
        self, page, plain_home: Path, tmp_path: Path
    ) -> None:
        from front_office.pipelines.build import build_database

        home = tmp_path / "home"
        shutil.copytree(plain_home, home)
        model = load_value_model(home / "configs")
        value_model_path(home / "configs").unlink()
        assert build_database(load_settings(home)).loaded
        save_value_model(home / "configs", model)
        said = texts(page(home, "value"))
        assert "**The value model has not been applied yet**" in said and "Run: fol build" in said

    def test_a_newer_model_than_the_build_is_flagged(self, page, copy: Path, value_model) -> None:
        save_value_model(copy / "configs", value_model.model_copy(update={"revision": 4}))
        said = texts(page(copy, "value", **{state.SEASON: SEASON}))
        assert "Out of date" in said
        assert (
            "The model on file is revision 4; the values on this page were built with r1." in said
        )

    def test_seasons_finished_since_the_fit_are_flagged(
        self, page, copy: Path, value_model
    ) -> None:
        older = value_model.fitted_on.model_copy(update={"last_season": "2007-08"})
        save_value_model(copy / "configs", value_model.model_copy(update={"fitted_on": older}))
        said = texts(page(copy, "value", **{state.SEASON: SEASON}))
        assert "The model was fitted on seasons to 2007-08. 2008-09 finished since" in said
        assert "fol value fit --write, then fol build" in said

    def test_values_outlive_a_model_file_that_is_gone(self, page, copy: Path) -> None:
        value_model_path(copy / "configs").unlink()
        opened = page(copy, "value", **{state.SEASON: SEASON})
        said = texts(opened)
        assert "no longer on file, so its evidence cannot be shown" in said
        assert "**No fitted model on file**" in said
        assert len(frame_with(opened, "impact", "reliability")) == 110


class TestASeason:
    def test_the_table_is_the_services_season(self, page, value_home: Path) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        table = frame_with(opened, "impact", "reliability")
        with service(value_home) as lab:
            season = lab.value.season(SEASON)
        assert table["player_name"].tolist() == season["player_name"].tolist()
        for column in ("minutes_share", "impact", "impact_offense", "impact_defense", "wins_added"):
            assert table[column].tolist() == pytest.approx(season[column].tolist())
        assert f"{len(season)} players. Select a row" in texts(opened)

    def test_the_chart_draws_the_top_fifteen_in_order(self, page, value_home: Path) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        (bars,) = drawn(opened)["value_top"].data
        with service(value_home) as lab:
            top = lab.value.season(SEASON).head(15)
        assert list(bars.x) == pytest.approx(top["wins_added"].tolist())
        assert list(bars.y) == (top["player_name"] + " · " + top["team"]).tolist()
        assert list(bars.text) == [f"{wins:.1f}" for wins in top["wins_added"]]
        first = bars.customdata[0]
        assert first[2] == (
            f"Offense {top['impact_offense'].iloc[0]:+.1f}, "
            f"defense {top['impact_defense'].iloc[0]:+.1f}"
        )
        assert first[3].endswith(f"{top['wins_added'].iloc[0]:.1f} wins above replacement")

    @pytest.mark.parametrize("order", ["impact", "impact_offense", "impact_defense"])
    def test_it_can_be_ordered_by_another_measure(self, page, value_home: Path, order: str) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON, "value_order": order})
        (bars,) = drawn(opened)["value_top"].data
        with service(value_home) as lab:
            season = lab.value.season(SEASON).sort_values(order, ascending=False)
        assert list(bars.x) == pytest.approx(season[order].head(15).tolist())
        table = frame_with(opened, "impact", "reliability")
        assert table[order].is_monotonic_decreasing
        assert f"**{lab.value.metrics[order].name}, {SEASON}: the top 15**" in texts(opened)

    def test_position_and_team_narrow_the_table_and_the_chart(self, page, value_home: Path) -> None:
        session = {state.SEASON: SEASON, state.TEAM: 103, "value_position": "Guard"}
        opened = page(value_home, "value", **session)
        table = frame_with(opened, "impact", "reliability")
        with service(value_home) as lab:
            season = lab.value.season(SEASON)
        mine = season[(season["team_id"] == 103) & (season["position_group"] == "Guard")]
        assert 0 < len(mine) < 12 and set(table["team"]) == {"T103"}
        assert sorted(table["player_name"]) == sorted(mine["player_name"])
        (bars,) = drawn(opened)["value_top"].data
        assert len(bars.x) == len(mine)
        assert f"the top {len(mine)}**" in texts(opened)

    def test_filters_that_leave_nobody_say_so(self, page, plain_home: Path) -> None:
        # The fixture store has the players of two teams; every other team has nobody.
        with service(plain_home) as lab:
            season = lab.value.season("2025-26")
            empty = next(
                team for team in lab.team_labels().index if team not in set(season["team_id"])
            )
        opened = page(plain_home, "value", **{state.TEAM: int(empty)})
        assert "**No players match**" in texts(opened)
        assert "value_top" not in drawn(opened)

    def test_a_season_that_was_not_valued_says_which_were(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "value", **{state.SEASON: "1996-97"})
        said = texts(opened)
        assert "**No values for 1996-97**" in said
        assert "seasons with player statistics: 2025-26 to 2025-26" in said

    def test_the_phase_and_the_window_do_not_narrow_the_page(self, page, value_home: Path) -> None:
        plain = page(value_home, "value", **{state.SEASON: SEASON})
        expected = frame_with(plain, "impact", "reliability")
        narrowed = page(
            value_home,
            "value",
            **{state.SEASON: SEASON, state.PHASE: "playoffs", state.SPAN: "Last 10 games"},
        )
        assert frame_with(narrowed, "impact", "reliability").equals(expected)


class TestAPlayer:
    @pytest.fixture
    def chosen(self, value_home: Path) -> int:
        with service(value_home) as lab:
            return int(lab.value.season(SEASON).index[2])

    def test_the_headline_is_the_players_row_with_its_ranks(
        self, page, value_home: Path, chosen: int
    ) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON, state.PLAYER: chosen})
        shown = figures(opened)
        with service(value_home) as lab:
            season = lab.value.season(SEASON)
        row = season.loc[chosen]
        assert [heading.value for heading in opened.subheader] == [row["player_name"]]
        assert shown["Wins above replacement"] == (f"{row['wins_added']:.1f}", "3rd of 110")
        rank = int(row["impact_rank"])
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank, "th")
        assert shown["Impact"] == (f"{row['impact']:+.1f}", f"{rank}{suffix} of 110")
        assert shown["Offense"] == (f"{row['impact_offense']:+.1f}", "points added")
        assert shown["Defense"] == (f"{row['impact_defense']:+.1f}", "points saved")
        assert shown["Reliability"] == (
            f"{row['reliability'] * 100:.0f}%",
            f"{row['minutes_share'] * 100:.0f}% of team minutes",
        )

    def test_the_parts_drawn_add_up_to_the_impact(
        self, page, value_home: Path, chosen: int
    ) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON, state.PLAYER: chosen})
        (bars,) = drawn(opened)["value_parts"].data
        with service(value_home) as lab:
            parts = lab.value.parts(chosen, SEASON)
            impact = lab.value.season(SEASON).loc[chosen, "impact"]
        assert list(bars.x) == pytest.approx(parts["value"].tolist())
        assert list(bars.y) == parts["label"].tolist() and bars.y[-1] == "Assumed"
        assert sum(bars.x) == pytest.approx(impact)
        assert list(bars.text) == [f"{value:+.2f}" for value in parts["value"]]

    def test_the_history_sets_each_season_beside_what_was_expected(
        self, page, value_home: Path, chosen: int
    ) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON, state.PLAYER: chosen})
        showed, expected = drawn(opened)["value_history"].data
        with service(value_home) as lab:
            history = lab.value.player(chosen)
        assert (showed.name, expected.name) == ("What the season showed", "Expected going in")
        assert list(showed.x) == list(expected.x) == history["season"].tolist()
        both = zip(showed.y, history["impact"], strict=True)
        assert all(drew == pytest.approx(value, nan_ok=True) for drew, value in both)
        assert list(expected.y) == pytest.approx(history["projected_impact"].tolist())

    def test_a_player_from_another_season_has_no_breakdown_here(
        self, page, plain_home: Path
    ) -> None:
        # The sidebar offers the players of the chosen season, so this happens only when
        # the choice is carried over from a page that set it another way.
        opened = page(plain_home, "value", **{state.PLAYER: TATUM})
        assert figures(opened)["Impact"][1].endswith("of 41")
        assert not [box for box in opened.error]


class TestProjections:
    def test_the_table_is_the_services_projection(self, page, value_home: Path) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        table = frame_with(opened, "projected_wins", "last_season")
        with service(value_home) as lab:
            projected = lab.value.projections()
        assert table["player_name"].tolist() == projected["player_name"].tolist()
        for column in ("projected_impact", "projected_share", "projected_wins", "last_impact"):
            assert table[column].tolist() == pytest.approx(projected[column].tolist(), nan_ok=True)
        said = texts(opened)
        assert "What the model expects of each player in **2009-10**" in said
        assert f"{len(projected)} players with a season on record in the last three." in said

    def test_the_chart_draws_the_most_projected_wins(self, page, value_home: Path) -> None:
        (bars,) = drawn(page(value_home, "value"))["value_projected_top"].data
        with service(value_home) as lab:
            top = lab.value.projections().head(15)
        assert list(bars.x) == pytest.approx(top["projected_wins"].tolist())
        assert bars.customdata[0][2] == f"Projected impact {top['projected_impact'].iloc[0]:+.1f}"

    def test_the_team_filter_follows_the_players_current_team(self, page, value_home: Path) -> None:
        opened = page(value_home, "value", **{state.TEAM: 105})
        table = frame_with(opened, "projected_wins", "last_season")
        with service(value_home) as lab:
            projected = lab.value.projections()
        assert sorted(table["player_name"]) == sorted(
            projected.loc[projected["team_id"] == 105, "player_name"]
        )
        assert set(table["team"]) == {"T105"}

    def test_with_nothing_ahead_it_says_so(self, page, copy: Path) -> None:
        with Database(load_settings(copy).database_path) as database:
            with database.begin() as connection:
                connection.execute(text("DELETE FROM player_value_scores WHERE impact IS NULL"))
        said = texts(page(copy, "value", **{state.SEASON: SEASON}))
        assert "**Nothing to look ahead to**" in said


class TestValueForMoney:
    def test_without_contracts_it_says_where_salaries_come_from(
        self, page, plain_home: Path
    ) -> None:
        said = texts(page(plain_home, "value"))
        assert "**No contract data**" in said and "a contract file you import" in said

    def test_contracts_that_do_not_pay_for_wins_are_shown_without_a_price(
        self, page, contract_template: Path
    ) -> None:
        opened = page(contract_template, "value")
        said = texts(opened)
        assert "Salaries in **2026-27**, from your contract file, against what was expected" in said
        assert "No price of a win can be read off these contracts" in said
        assert "Price of a win" not in figures(opened)
        table = frame_with(opened, "salary", "cost_per_win")
        with service(contract_template) as lab:
            money = lab.value.for_money("2026-27")
        assert money.market is None
        assert table["player_name"].tolist() == money.players["player_name"].tolist()
        assert table["salary"].tolist() == money.players["salary"].tolist()
        assert table["market_value"].isna().all()
        trace = drawn(opened)["value_money"].data
        assert len(trace) == 1 and len(trace[0].x) == len(money.players)

    def test_a_later_season_of_a_contract_is_not_valued(
        self, page, contract_template: Path
    ) -> None:
        said = texts(page(contract_template, "value", value_money_season="2027-28"))
        assert "**2027-28 has not been valued**" in said
        assert "looks one season ahead, to 2026-27" in said

    @pytest.fixture
    def paid(self, copy: Path) -> Path:
        """The six most valuable players of 2008-09, the best of them paid the most."""
        with service(copy) as lab:
            best = lab.value.season("2008-09").index[:6].tolist()
        pay(copy, "2008-09", {player: (6 - place) * 5_000_000 for place, player in enumerate(best)})
        return copy

    def test_the_price_of_a_win_is_the_services_market(self, page, paid: Path) -> None:
        opened = page(paid, "value", **{state.SEASON: "2008-09"})
        with service(paid) as lab:
            money = lab.value.for_money("2008-09")
        shown = figures(opened)
        market = money.market
        assert shown["Price of a win"] == (
            f"${market.price_per_win / 1e6:,.1f}M",
            "from 6 contracts",
        )
        assert shown["Salary explained"] == (f"{market.r2 * 100:.0f}%", "by wins alone")
        assert shown["Cost of no wins"][1] == "a replacement player"
        said = texts(opened)
        assert "against what the season showed: 6 players." in said
        assert "have no value" not in said

    def test_the_table_and_the_chart_are_the_services_players(self, page, paid: Path) -> None:
        opened = page(paid, "value", **{state.SEASON: "2008-09"})
        with service(paid) as lab:
            money = lab.value.for_money("2008-09")
        table = frame_with(opened, "salary", "rating")
        for column in ("salary", "wins", "market_value", "surplus", "cost_per_win", "rating"):
            assert table[column].tolist() == pytest.approx(money.players[column].tolist())
        line, marks = drawn(opened)["value_money"].data
        assert line.mode == "lines" and marks.mode == "markers"
        assert list(marks.x) == pytest.approx(money.players["wins"].tolist())
        assert list(marks.y) == pytest.approx(money.players["salary"].tolist())
        # The line is the market: it runs across the wins on the page at the market's price.
        market = money.market
        assert list(line.y) == pytest.approx(
            [market.replacement_cost + market.price_per_win * wins for wins in line.x]
        )
        assert sorted(line.x) == pytest.approx(
            [money.players["wins"].min(), money.players["wins"].max()]
        )

    def test_a_team_narrows_the_table_and_is_picked_out_among_everyone_drawn(
        self, page, copy: Path
    ) -> None:
        with service(copy) as lab:
            best = lab.value.season("2008-09").index[:6].tolist()
        salaries = {player: (6 - place) * 5_000_000 for place, player in enumerate(best)}
        elsewhere = [best[1], best[4]]
        pay(copy, "2008-09", salaries, teams=dict.fromkeys(elsewhere, 102))
        opened = page(copy, "value", **{state.SEASON: "2008-09", state.TEAM: 102})
        table = frame_with(opened, "salary", "rating")
        assert sorted(table["player_name"]) == sorted(f"Player {player}" for player in elsewhere)
        assert set(table["team"]) == {"T102"}
        # The market is everyone's, so the chart still draws all six.
        traces = drawn(opened)["value_money"].data
        assert sum(len(trace.x) for trace in traces if trace.mode != "lines") == 6
        assert figures(opened)["Price of a win"][1] == "from 6 contracts"

    def test_players_without_a_value_are_counted_not_dropped_silently(
        self, page, paid: Path
    ) -> None:
        with Database(load_settings(paid).database_path) as database:
            with database.begin() as connection:
                connection.execute(
                    text("UPDATE contract_years SET player_id = 99999 WHERE contract_id = 6")
                )
                connection.execute(
                    text("UPDATE contracts SET player_id = 99999 WHERE contract_id = 6")
                )
        said = texts(page(paid, "value", **{state.SEASON: "2008-09"}))
        assert "5 players. 1 with a salary have no value and are left out." in said


class TestTheModel:
    def test_the_headlines_are_the_models_own_figures(self, page, plain_home: Path) -> None:
        shown = figures(page(plain_home, "value"))
        model = load_value_model(plain_home / "configs")
        tested = model.validation
        assert shown["Typical miss, in points"] == (
            f"{tested.net.rmse:.2f}", f"{tested.team_seasons} team-seasons",
        )  # fmt: skip
        best = min(tested.baselines, key=lambda item: item.rmse)
        assert shown["Best simpler method"] == (f"{best.rmse:.2f}", "closest of 6")
        assert shown["Replacement level"] == (
            f"{model.replacement_level:+.2f}", "per 100 possessions",
        )  # fmt: skip
        assert shown["Fitted on"][0] == f"{model.fitted_on.team_seasons:,}"
        assert shown["Revision"][0] == str(model.revision)

    def test_each_simpler_method_is_drawn_with_its_interval(self, page, plain_home: Path) -> None:
        intervals, dots = drawn(page(plain_home, "value"))["value_baselines"].data
        with service(plain_home) as lab:
            card = lab.value.card()
        others = card.baselines[card.baselines["key"] != "value_model"]
        assert list(dots.x) == pytest.approx(others["difference"].tolist())
        assert list(dots.y) == others["label"].tolist()
        ends = [value for value in intervals.x if value is not None]
        expected = [end for pair in zip(others["low"], others["high"], strict=True) for end in pair]
        assert ends == pytest.approx(expected)
        assert "95% interval" in dots.customdata[0][0]
        table = frame_with(page(plain_home, "value"), "method", "rmse")
        assert table["method"].iloc[0] == "Value model" and len(table) == 7

    def test_each_part_left_out_is_drawn_costliest_first(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "value")
        _, dots = drawn(opened)["value_ablations"].data
        with service(plain_home) as lab:
            ablations = lab.value.card().ablations
        assert list(dots.x) == pytest.approx(ablations["difference"].tolist())
        assert list(dots.x) == sorted(dots.x, reverse=True)
        unsure = ablations.loc[~ablations["distinguishable"], "label"].str.lower().tolist()
        assert unsure and all(name in texts(opened) for name in unsure)
        assert "cannot be told from adding nothing" in texts(opened)

    @pytest.mark.parametrize("side", ["net", "offense", "defense"])
    def test_the_weights_are_drawn_for_either_end_or_both(
        self, page, plain_home: Path, side: str
    ) -> None:
        opened = page(plain_home, "value", value_side=side)
        intervals, dots = drawn(opened)["value_weights"].data
        with service(plain_home) as lab:
            terms = lab.value.card().terms
        features = terms[terms["group"] != "Levels"]
        assert len(dots.x) == 15 and list(dots.y) == features["label"].tolist()
        assert list(dots.x) == pytest.approx(features[side].tolist())
        ends = [value for value in intervals.x if value is not None]
        assert ends[:2] == pytest.approx(
            [features[f"{side}_low"].iloc[0], features[f"{side}_high"].iloc[0]]
        )
        levels = terms.set_index("key")
        assert f"starts at {levels.at['new_player', 'net']:+.2f}" in texts(opened)

    def test_the_backtest_is_drawn_against_the_line_of_exact_prediction(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "value")
        line, marks = drawn(opened)["value_backtest"].data
        with service(plain_home) as lab:
            backtest = lab.value.card().backtest
        assert list(marks.x) == pytest.approx(backtest["predicted"].tolist())
        assert list(marks.y) == pytest.approx(backtest["actual"].tolist())
        assert list(line.x) == pytest.approx(list(line.y))
        assert f"One mark for each of {len(backtest)} team-seasons" in texts(opened)
        assert "Choose a team in the sidebar" in texts(opened)

    def test_a_chosen_teams_seasons_are_picked_out(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "value", **{state.TEAM: BOS})
        _, rest, chosen = drawn(opened)["value_backtest"].data
        with service(plain_home) as lab:
            backtest = lab.value.card().backtest
        mine = backtest[backtest["team_id"] == BOS]
        assert len(chosen.x) == len(mine) and len(rest.x) == len(backtest) - len(mine)
        assert "Choose a team in the sidebar" not in texts(opened)

    def test_what_the_model_cannot_tell_you_is_said(self, page, plain_home: Path) -> None:
        said = texts(page(plain_home, "value"))
        for claim in (
            "Impact is an estimate of ability, not a split of results.",
            "Defense is the weak side.",
            "The test takes next season's minutes as given.",
            "Playoff performance is not in it.",
        ):
            assert claim in said

    def test_a_model_without_a_test_on_file_says_so(self, page, value_home: Path) -> None:
        # The planted model has weights and no evidence: the page shows the one and says
        # plainly that the other is missing.
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        said = texts(opened)
        assert said.count("**No test on file**") == 3
        assert figures(opened)["Best simpler method"] == ("—", "closest of 0")
        charts = drawn(opened)
        assert "value_weights" in charts
        assert not {"value_baselines", "value_ablations", "value_backtest"} & set(charts)


class TestRoles:
    def test_the_rules_are_laid_out_as_the_service_gives_them(self, page, value_home: Path) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        table = frame_with(opened, "open_to", "measures")
        with service(value_home) as lab:
            summary = lab.value.role_summary(SEASON)
        assert list(table.columns) == [
            "name", "open_to", "measures", "fills_at", "scored", "filled", "again", "anyone",
        ]  # fmt: skip
        for column in ("name", "open_to", "measures", "fills_at", "scored", "filled"):
            assert table[column].tolist() == summary[column].tolist(), column
        for column in ("again", "anyone"):
            assert table[column].tolist() == pytest.approx(summary[column].tolist())
        said = texts(opened)
        assert "A role is a rule, not a measurement" in said
        assert "configs/archetypes.yaml" in said
        assert "filled again far more often than by anyone at all" in said

    def test_it_opens_on_the_first_role_with_who_fills_it(self, page, value_home: Path) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON})
        with service(value_home) as lab:
            players = lab.value.role_players(SEASON, "primary_creator")
            role = lab.value.archetypes()["primary_creator"]
        said = texts(opened)
        assert f"**Primary Creator.** {role.description}" in said
        assert f"{role.note} Fills the role: a score of 85 or more, among everyone." in said
        table = frame_with(opened, "score", "is_primary")
        assert list(table.columns) == [
            "player_name", "team", "position", "age", "score", "is_primary", "roles", "impact",
            "wins_added",
        ]  # fmt: skip
        assert table.index.tolist() == players.index.tolist()
        assert table["score"].tolist() == players["score"].tolist()
        assert table["roles"].str.contains("Primary Creator").all()

    @pytest.mark.parametrize(
        ("role", "rule"),
        [
            ("secondary_creator", "a score of 67 or more and below 85, among everyone."),
            ("rim_protector", "a score of 67 or more, among big men."),
            ("connector", "a score of 67 or more, among low-usage players."),
        ],
    )
    def test_another_role_is_chosen_on_the_page(
        self, page, value_home: Path, role: str, rule: str
    ) -> None:
        opened = page(value_home, "value", **{state.SEASON: SEASON, "value_role": role})
        with service(value_home) as lab:
            players = lab.value.role_players(SEASON, role)
            name = lab.value.archetypes()[role].name
        assert f"**{name}.**" in texts(opened) and f"Fills the role: {rule}" in texts(opened)
        table = frame_with(opened, "score", "is_primary")
        assert table["player_name"].tolist() == players["player_name"].tolist()
        assert table["is_primary"].tolist() == players["is_primary"].tolist()
        assert table["impact"].tolist() == pytest.approx(players["impact"].tolist())
        assert f"{len(players)} players fill this role in {SEASON}." in texts(opened)
        assert opened.dataframe and table["score"].is_monotonic_decreasing

    def by_team(self, home: Path, role: str):  # type: ignore[no-untyped-def]
        with service(home) as lab:
            players = lab.value.role_players(SEASON, role)
            teams = lab.team_labels().index.tolist()
        return players, {team: int((players["team_id"] == team).sum()) for team in teams}

    def test_the_team_filter_narrows_who_is_listed(self, page, value_home: Path) -> None:
        players, counts = self.by_team(value_home, "floor_spacer")
        team = next(team for team, count in counts.items() if count > 1)
        session = {state.SEASON: SEASON, state.TEAM: team, "value_role": "floor_spacer"}
        opened = page(value_home, "value", **session)
        table = frame_with(opened, "score", "is_primary")
        mine = players[players["team_id"] == team]
        assert table["player_name"].tolist() == mine["player_name"].tolist()
        assert f"{len(mine)} players fill this role in {SEASON}." in texts(opened)
        # The rules above the list are the league's, whatever team is chosen.
        assert frame_with(opened, "open_to", "measures")["filled"].sum() > len(mine)

    def test_one_player_is_not_several(self, page, value_home: Path) -> None:
        _, counts = self.by_team(value_home, "floor_spacer")
        team = next(team for team, count in counts.items() if count == 1)
        session = {state.SEASON: SEASON, state.TEAM: team, "value_role": "floor_spacer"}
        said = texts(page(value_home, "value", **session))
        assert f"1 player fills this role in {SEASON}." in said

    def test_a_team_with_nobody_in_the_role_says_so(self, page, value_home: Path) -> None:
        _, counts = self.by_team(value_home, "primary_creator")
        team = next(team for team, count in counts.items() if count == 0)
        opened = page(value_home, "value", **{state.SEASON: SEASON, state.TEAM: team})
        said = texts(opened)
        assert "**Nobody fills this role**" in said and "Clear the team filter" in said
        assert not [frame for frame in opened.dataframe if "is_primary" in frame.value.columns]
        assert "value_role_csv" not in [button.key for button in opened.get("download_button")]

    def test_a_season_without_roles_says_so(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "value", **{state.SEASON: "1996-97"})
        assert "**No roles for 1996-97**" in texts(opened)
        assert not [frame for frame in opened.dataframe if "open_to" in frame.value.columns]

    def test_the_fixture_lab_has_one_season_and_nothing_carried_over(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "value")
        table = frame_with(opened, "open_to", "measures")
        assert table["again"].isna().all() and table["filled"].tolist()[0] == 3
        players = frame_with(opened, "score", "is_primary")
        assert players["player_name"].tolist() == ["Jalen Brunson", "Jaylen Brown", "Jayson Tatum"]

    def test_a_chosen_players_roles_are_named_on_the_season_tab(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "value", **{state.PLAYER: TATUM})
        assert "Roles filled in 2025-26: Primary Creator, Perimeter Defender." in texts(opened)
        without = page(plain_home, "value", **{state.PLAYER: TOWNS})
        assert "Karl-Anthony Towns" in texts(without) and "Roles filled" not in texts(without)
