"""Fitting the value model: planted weights are found, and the evidence is what it says.

The league is invented and its team ratings are planted by ``tests.value_reference``,
which computes the model with plain loops and shares no code with the modeling layer.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from front_office.domain.seasons import Season
from front_office.domain.value_model import ValueModel, ValueSpec
from front_office.modeling.value import TERM_KEYS, NotEnoughData, fit_value_model
from front_office.modeling.value.estimate import MIN_TRAINING_SEASONS
from front_office.modeling.value.features import COMPONENT_KEYS, RIVAL_KEYS
from tests.league import SyntheticLeague
from tests.unit.modeling.conftest import FITTED_AT
from tests.value_reference import (
    DEFENSE,
    MODEL_TERMS,
    OFFENSE,
    planted_league,
    season_impacts,
)

EXACT = 2e-5
"""Weights are stored to six decimals and team ratings summed in a different order."""


def net(league: SyntheticLeague, year: int, team: int) -> float:
    return sum(league.ratings[year][team])


def years_tested(league: SyntheticLeague, spec: ValueSpec) -> list[int]:
    first = Season.parse(spec.first_test_season).start_year
    return [year for year in league.years if year >= first]


def test_the_reference_declares_the_models_terms_in_the_models_order() -> None:
    assert MODEL_TERMS == TERM_KEYS


class TestPlantedWeights:
    def test_every_weight_is_recovered_on_both_sides_of_the_ball(
        self, exact_model: ValueModel
    ) -> None:
        assert exact_model.keys == TERM_KEYS
        for term in exact_model.terms:
            assert term.offense == pytest.approx(OFFENSE[term.key], abs=EXACT), term.key
            assert term.defense == pytest.approx(DEFENSE[term.key], abs=EXACT), term.key

    def test_a_model_that_is_exactly_right_predicts_exactly(
        self, exact_model: ValueModel, exact_league: SyntheticLeague
    ) -> None:
        tested = exact_model.validation
        for score in (tested.net, tested.offense, tested.defense):
            assert score.rmse < 1e-6 and score.mae < 1e-6
            assert score.r2 == pytest.approx(1.0, abs=1e-9)
        for row in exact_model.backtest:
            year = Season.parse(row.season).start_year
            planted = exact_league.ratings[year][row.team_id]
            assert (row.actual_offense, row.actual_defense) == pytest.approx(planted, abs=1e-3)
            assert row.predicted == pytest.approx(row.actual, abs=2e-3)

    def test_with_nothing_left_to_explain_the_intervals_close_on_the_weights(
        self, exact_model: ValueModel
    ) -> None:
        for term in exact_model.terms:
            for side in ("offense", "defense", "net"):
                low, high = term.interval(side)
                assert high - low < 1e-4, (term.key, side)
                assert low - 1e-4 < term.weight(side) < high + 1e-4

    def test_luck_widens_the_intervals_which_still_hold_the_truth(
        self, noisy_model: ValueModel
    ) -> None:
        held = 0
        for term in noisy_model.terms:
            low, high = term.interval("net")
            assert high - low > 0.01, term.key
            held += low <= OFFENSE[term.key] + DEFENSE[term.key] <= high
        # 95% intervals on 19 weights: nearly all, though not necessarily every one.
        assert held >= len(TERM_KEYS) - 2

    def test_luck_is_what_the_model_cannot_predict(self, noisy_model: ValueModel) -> None:
        # 1.5 points of luck at each end of the floor, independent: 2.1 on net rating.
        tested = noisy_model.validation
        assert tested.offense.rmse == pytest.approx(1.5, rel=0.15)
        assert tested.defense.rmse == pytest.approx(1.5, rel=0.15)
        assert tested.net.rmse == pytest.approx(1.5 * math.sqrt(2), rel=0.15)
        assert 0 < tested.net.r2 < 1

    def test_the_same_tables_and_specification_give_the_same_model(
        self, exact_tables, exact_model: ValueModel, spec: ValueSpec
    ) -> None:
        again = fit_value_model(exact_tables, spec, revision=1, fitted_at=FITTED_AT)
        assert again == exact_model

    def test_the_seed_moves_the_intervals_and_nothing_else(self, noisy_league, spec) -> None:
        tables = noisy_league.tables()
        one = fit_value_model(tables, spec, revision=1, fitted_at=FITTED_AT)
        other = fit_value_model(
            tables, spec.model_copy(update={"seed": 1}), revision=1, fitted_at=FITTED_AT
        )
        assert [term.offense for term in one.terms] == [term.offense for term in other.terms]
        assert one.validation.net == other.validation.net
        assert [term.net_low for term in one.terms] != [term.net_low for term in other.terms]


class TestWhatIsFittedOn:
    def test_the_first_season_has_nothing_before_it_and_is_only_ever_history(
        self, exact_model: ValueModel, exact_league: SyntheticLeague
    ) -> None:
        on = exact_model.fitted_on
        teams, years = len(exact_league.team_ids), exact_league.years
        assert (on.first_season, on.last_season) == ("2000-01", "2008-09")
        assert on.team_seasons == teams * (len(years) - 1)
        # Every player-season with something counted: one a season has not.
        lines = sum(len(exact_league.lines[year]) for year in years)
        assert on.player_seasons == lines - len(years)

    def test_seasons_from_the_first_test_season_are_predicted_once_each(
        self, exact_model: ValueModel, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        tested, years = exact_model.validation, years_tested(exact_league, spec)
        teams = len(exact_league.team_ids)
        assert (tested.first_test_season, tested.last_test_season) == ("2004-05", "2008-09")
        assert tested.team_seasons == len(exact_model.backtest) == teams * len(years)
        assert [score.season for score in tested.by_season] == [
            Season(year).label for year in years
        ]
        assert all(score.teams == teams for score in tested.by_season)
        keys = {(row.season, row.team_id) for row in exact_model.backtest}
        assert len(keys) == len(exact_model.backtest)

    def test_a_season_whose_postseason_is_undecided_is_left_out(self, spec: ValueSpec) -> None:
        league = planted_league(spec)
        league.unfinished = {league.years[-1]}
        model = fit_value_model(league.tables(), spec, revision=1, fitted_at=FITTED_AT)
        assert model.fitted_on.last_season == "2007-08"
        assert model.validation.last_test_season == "2007-08"
        assert model.fitted_on.team_seasons == len(league.team_ids) * (len(league.years) - 2)

    def test_a_team_with_a_player_missing_is_left_out(self, exact_tables, exact_league, spec):
        tables = dict(exact_tables)
        seasons = tables["player_seasons"]
        stint = max(exact_league.stints[2006], key=lambda stint: stint.minutes)
        gone = (seasons["player_id"] == stint.player_id) & (seasons["season"] == "2006-07")
        tables["player_seasons"] = seasons[~gone]
        model = fit_value_model(tables, spec, revision=1, fitted_at=FITTED_AT)
        missing = {(row.season, row.team_id) for row in model.backtest}
        assert ("2006-07", stint.team_id) not in missing
        assert model.validation.team_seasons == len(exact_league.team_ids) * 5 - 1

    def test_too_few_seasons_before_the_test_is_an_error_that_says_so(self, exact_tables) -> None:
        early = ValueSpec(first_test_season="2003-04", resamples=50)
        assert MIN_TRAINING_SEASONS == 3
        # 2001-02 and 2002-03 are the only seasons before it with a season before them.
        with pytest.raises(NotEnoughData, match="tested from 2003-04 .* the tables hold 2 "):
            fit_value_model(exact_tables, early, revision=1, fitted_at=FITTED_AT)

    def test_nothing_to_test_on_is_an_error(self, exact_tables) -> None:
        late = ValueSpec(first_test_season="2012-13", resamples=50)
        with pytest.raises(NotEnoughData, match="0 team-seasons to test on"):
            fit_value_model(exact_tables, late, revision=1, fitted_at=FITTED_AT)

    def test_no_players_at_all_is_an_error(self, exact_tables, spec: ValueSpec) -> None:
        tables = {name: frame.iloc[0:0] for name, frame in exact_tables.items()}
        tables["team_seasons"] = exact_tables["team_seasons"]
        with pytest.raises(NotEnoughData, match="no player statistics"):
            fit_value_model(tables, spec, revision=1, fitted_at=FITTED_AT)

    def test_revision_and_time_are_stamped_as_given(self, exact_tables, spec: ValueSpec) -> None:
        model = fit_value_model(exact_tables, spec, revision=7, fitted_at=FITTED_AT)
        assert (model.revision, model.version, model.fitted_at) == (7, "r7", FITTED_AT)
        assert model.spec == spec


class TestBaselines:
    """What the model is set against, worked out by hand from the planted ratings."""

    def errors(self, league: SyntheticLeague, spec: ValueSpec, predict) -> np.ndarray:  # type: ignore[no-untyped-def]
        return np.array(
            [
                predict(year, team) - net(league, year, team)
                for year in years_tested(league, spec)
                for team in league.team_ids
            ]
        )

    def test_every_baseline_is_there_and_named(self, noisy_model: ValueModel) -> None:
        keys = [item.key for item in noisy_model.validation.baselines]
        assert keys == ["league_average", "last_season", "last_season_regressed", *RIVAL_KEYS]
        assert all(
            item.label and item.label[0].isupper() for item in noisy_model.validation.baselines
        )

    def test_calling_every_team_average_misses_by_the_teams_own_ratings(
        self, noisy_model: ValueModel, noisy_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        errors = self.errors(noisy_league, spec, lambda year, team: 0.0)
        found = noisy_model.validation.baseline("league_average")
        assert found.rmse == pytest.approx(np.sqrt((errors**2).mean()), abs=1e-6)
        assert found.mae == pytest.approx(np.abs(errors).mean(), abs=1e-6)

    def test_last_season_is_the_teams_own_net_rating_the_season_before(
        self, noisy_model: ValueModel, noisy_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        league = noisy_league
        errors = self.errors(league, spec, lambda year, team: net(league, year - 1, team))
        found = noisy_model.validation.baseline("last_season")
        assert found.rmse == pytest.approx(np.sqrt((errors**2).mean()), abs=1e-6)

    def test_the_regressed_baseline_fits_its_slope_on_earlier_seasons_only(
        self, noisy_model: ValueModel, noisy_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        league = noisy_league
        usable = league.years[1:]  # the first season has no season before it

        def predict(year: int, team: int) -> float:
            pairs = [
                (net(league, earlier - 1, other), net(league, earlier, other))
                for earlier in usable
                if earlier < year
                for other in league.team_ids
            ]
            slope = sum(a * b for a, b in pairs) / sum(a * a for a, _ in pairs)
            return slope * net(league, year - 1, team)

        errors = self.errors(league, spec, predict)
        found = noisy_model.validation.baseline("last_season_regressed")
        assert found.rmse == pytest.approx(np.sqrt((errors**2).mean()), abs=1e-6)

    def test_a_difference_is_the_models_error_less_the_baselines(
        self, noisy_model: ValueModel
    ) -> None:
        tested = noisy_model.validation
        for item in tested.baselines:
            assert item.difference == pytest.approx(tested.net.rmse - item.rmse, abs=2e-6)
            assert item.low <= item.difference <= item.high

    def test_the_planted_model_beats_every_baseline_beyond_doubt(
        self, noisy_model: ValueModel
    ) -> None:
        for item in noisy_model.validation.baselines:
            assert item.difference < 0 and item.high < 0, item.key
            assert item.is_distinguishable


class TestAblations:
    def test_one_for_every_component_then_age_and_the_minutes_prior(
        self, exact_model: ValueModel
    ) -> None:
        keys = [item.key for item in exact_model.validation.ablations]
        assert keys == [*COMPONENT_KEYS, "age", "prior_minutes"]

    def test_leaving_out_anything_that_matters_costs_accuracy(
        self, exact_model: ValueModel
    ) -> None:
        # Every planted weight is far from zero, so in a world without luck each part
        # is missed when it goes.
        full = exact_model.validation.net.rmse
        for item in exact_model.validation.ablations:
            assert item.rmse > 1e-3 and item.difference == pytest.approx(item.rmse - full, abs=2e-6)
            assert item.low > 0, item.key

    def test_a_part_with_nothing_planted_is_not_missed(self, spec: ValueSpec) -> None:
        offense = {**OFFENSE, "oreb": 0.0, "dreb": 0.0}
        defense = {**DEFENSE, "oreb": 0.0, "dreb": 0.0}
        league = planted_league(spec, noise=1.0, seed=5, teams=20, offense=offense, defense=defense)
        model = fit_value_model(league.tables(), spec, revision=1, fitted_at=FITTED_AT)
        rebounding = model.validation.ablation("rebounding")
        assert not rebounding.is_distinguishable
        assert abs(rebounding.difference) < 0.1
        assert model.validation.ablation("efficiency").low > 0


class TestWhatTheRatingsImply:
    def test_replacement_level_is_the_impact_of_players_beyond_each_teams_top_ten(
        self, exact_model: ValueModel, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        league = exact_league
        assert spec.replacement_rank == 10
        weighted = minutes = 0.0
        for year in league.years:
            impacts = season_impacts(league, year, spec)
            best: dict[int, int] = {}
            for team in league.team_ids:
                played = sorted(
                    (stint for stint in league.stints[year] if stint.team_id == team),
                    key=lambda stint: -stint.minutes,
                )
                for place, stint in enumerate(played, start=1):
                    best[stint.player_id] = min(place, best.get(stint.player_id, place))
            for line in league.lines[year]:
                if best[line.player_id] > 10:
                    weighted += line.minutes * impacts[line.player_id]["impact"]
                    minutes += line.minutes
        assert minutes > 0
        assert exact_model.replacement_level == pytest.approx(weighted / minutes, abs=1e-4)
        assert exact_model.replacement_level < 0

    def test_how_a_teams_impacts_add_up_against_its_own_season(
        self, exact_model: ValueModel, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        league = exact_league
        sums, actual = [], []
        for year in league.years[1:]:
            impacts = season_impacts(league, year, spec)
            for team in league.team_ids:
                sums.append(
                    sum(
                        stint.minutes / (82 * 48) * impacts[stint.player_id]["impact"]
                        for stint in league.stints[year]
                        if stint.team_id == team
                    )
                )
                actual.append(net(league, year, team))
        sums, actual = np.array(sums), np.array(actual)
        same = exact_model.validation.same_season
        assert same.slope == pytest.approx((sums * actual).sum() / (sums**2).sum(), abs=1e-4)
        assert same.correlation == pytest.approx(np.corrcoef(sums, actual)[0, 1], abs=1e-4)

    def test_minutes_are_projected_and_tested_too(self, noisy_model: ValueModel) -> None:
        minutes = noisy_model.availability
        assert set(minutes.coefficients) == {
            "intercept", "share_1", "share_2", "share_3", "years_over_30", "years_under_25",
        }  # fmt: skip
        assert minutes.players > 0 and 0 < minutes.rmse < 1
        assert minutes.difference == pytest.approx(minutes.rmse - minutes.baseline_rmse)
        assert minutes.low <= minutes.difference <= minutes.high


def test_a_fitted_model_survives_being_written_down(exact_model: ValueModel) -> None:
    again = ValueModel.model_validate_json(exact_model.model_dump_json())
    assert again == exact_model
    frame = pd.DataFrame([row.model_dump() for row in again.backtest])
    assert frame.notna().all().all()
