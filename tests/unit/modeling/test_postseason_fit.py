"""Fitting the postseason model on the invented league: the planted series model is found
again, and the out-of-sample test covers what it should."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from front_office.config import load_eras
from front_office.domain.postseason import PostseasonModel, PostseasonSpec
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.modeling.postseason import (
    SEASON_ALTERNATIVES,
    SERIES_ALTERNATIVES,
    UNIFORM,
    NotEnoughHistory,
    fit_postseason_model,
)
from tests.conftest import REPO_ROOT
from tests.postseason_reference import PLANTED

SPEC = PostseasonSpec(
    formats=(), first_test_season="2006-07", min_training_seasons=3, resamples=100, kept_draws=40
)
AT = datetime(2026, 10, 5, 12, 0)


@pytest.fixture(scope="module")
def eras() -> list:
    return list(load_eras(REPO_ROOT / "configs"))


@pytest.fixture(scope="module")
def fitted(postseason_league, eras) -> PostseasonModel:  # type: ignore[no-untyped-def]
    return fit_postseason_model(
        postseason_league[2], SPEC, eras, revision=1, fitted_at=AT, value_model_version="r1"
    )


class TestWhatIsRecovered:
    def test_the_planted_game_model_is_found_within_its_intervals(
        self, fitted: PostseasonModel
    ) -> None:
        game = fitted.game
        assert game.home_low <= PLANTED["home_advantage"] <= game.home_high
        assert game.net_low <= PLANTED["net_slope"] <= game.net_high
        assert game.top_low <= PLANTED["top_slope"] <= game.top_high
        assert game.home_advantage == pytest.approx(PLANTED["home_advantage"], abs=0.12)
        assert game.net_rating == pytest.approx(PLANTED["net_slope"], abs=0.04)
        assert game.top_players == pytest.approx(PLANTED["top_slope"], abs=0.12)
        assert game.games == 1192 and len(game.draws) == SPEC.kept_draws

    def test_what_it_was_fitted_on(self, fitted: PostseasonModel, postseason_league) -> None:  # type: ignore[no-untyped-def]
        league = postseason_league[0]
        on = fitted.fitted_on
        assert (on.first_season, on.last_season, on.seasons) == ("2000-01", "2013-14", 14)
        assert on.series == 15 * 14 and on.team_seasons == 30 * 14
        assert on.playoff_games == sum(
            len(series.games) for played in league.postseasons.values() for series in played.series
        )
        assert (fitted.revision, fitted.fitted_at, fitted.spec) == (1, AT, SPEC)
        assert fitted.value_model_version == "r1" and fitted.version == "p1"

    def test_the_season_model_sees_that_the_playoffs_follow_the_rating(
        self, fitted: PostseasonModel
    ) -> None:
        steps = {step.key: step for step in fitted.steps}
        assert tuple(steps) == BRACKET_STAGE_KEYS
        first = steps["made_playoffs"]
        assert first.net_rating > 0 and first.net_low > 0
        assert (first.teams, first.reached) == (420, 16 * 14)
        assert (steps["won_a_round"].teams, steps["won_a_round"].reached) == (16 * 14, 8 * 14)
        assert (steps["won_championship"].teams, steps["won_championship"].reached) == (28, 14)
        for step in fitted.steps:
            assert len(step.draws) == SPEC.kept_draws
            assert step.net_low <= step.net_high and step.top_low <= step.top_high

    def test_eras_that_cover_the_league_are_fitted_alone(self, fitted: PostseasonModel) -> None:
        by_key = {era.key: era for era in fitted.by_era}
        # The modern and play-in eras begin after the league ends, so they are left out.
        assert list(by_key) == ["all", "last_10", "last_5"]
        assert by_key["all"].games == 1192
        assert (by_key["last_5"].first_season, by_key["last_5"].last_season) == (
            "2009-10",
            "2013-14",
        )


class TestTheTest:
    def test_series_are_scored_out_of_sample_from_the_first_test_season(
        self, fitted: PostseasonModel
    ) -> None:
        tested = fitted.evaluation.series
        assert (tested.first_test_season, tested.last_test_season) == ("2006-07", "2013-14")
        assert tested.series == 8 * 15
        assert (
            0 <= tested.favourite_won <= tested.series
            and 0 <= tested.home_side_won <= tested.series
        )
        baselines = {item.key: item for item in tested.baselines}
        assert set(baselines) == {"home_court_rate", "coin_flip"}
        assert baselines["coin_flip"].log_loss == pytest.approx(np.log(2), abs=1e-4)
        assert baselines["coin_flip"].brier == 0.25
        assert tested.log_loss < baselines["coin_flip"].log_loss
        assert {item.key for item in tested.comparisons} == {key for key, *_ in SERIES_ALTERNATIVES}
        assert [item.round for item in tested.by_round] == [1, 2, 3, 4]
        assert [item.series for item in tested.by_round] == [64, 32, 16, 8]
        assert sum(item.cases for item in tested.reliability) == tested.series
        assert [item.key for item in tested.by_era] == ["all", "last_10", "last_5"]
        assert tested.by_era[0].series == tested.series

    def test_experience_without_playoff_logs_changes_nothing(self, fitted: PostseasonModel) -> None:
        for evaluation in (fitted.evaluation.series, fitted.evaluation.season):
            item = next(c for c in evaluation.comparisons if c.key == "with_experience")
            assert (item.difference, item.low, item.high) == (0.0, 0.0, 0.0)

    def test_the_bracket_is_carried_for_every_test_season(self, fitted: PostseasonModel) -> None:
        tested = fitted.evaluation.bracket
        assert tested.team_postseasons == 8 * 16 and len(tested.favourites) == 8
        for item, share in zip(tested.stages, (0.5, 0.25, 0.125, 0.0625), strict=True):
            assert item.cases == 128 and item.reached == 128 * share
            # Chances of a round add up over a bracket, so their mean is exact.
            assert item.mean_probability == pytest.approx(share, abs=1e-4)
            baselines = {baseline.key: baseline for baseline in item.baselines}
            assert set(baselines) == {"seed_rate", "uniform"}
            coin = UNIFORM[item.key]
            assert baselines["uniform"].log_loss == pytest.approx(
                -(share * np.log(coin) + (1 - share) * np.log(1 - coin)), abs=1e-4
            )
        assert 0 <= tested.favourite_won <= 8
        assert sum(item.cases for item in tested.reliability) == 4 * 128
        for favourite in tested.favourites:
            assert favourite.favourite_probability >= favourite.champion_probability
            assert favourite.season >= "2006-07"

    def test_the_season_model_is_scored_on_every_team_season(self, fitted: PostseasonModel) -> None:
        tested = fitted.evaluation.season
        assert tested.team_seasons == 8 * 30
        for item, reached in zip(tested.stages, (16, 8, 4, 2, 1), strict=True):
            assert item.cases == 240 and item.reached == 8 * reached
            assert [baseline.key for baseline in item.baselines] == ["base_rate"]
        first = tested.stages[0]
        assert first.log_loss < first.baselines[0].log_loss
        assert {item.key for item in tested.comparisons} == {key for key, *_ in SEASON_ALTERNATIVES}
        assert sum(item.cases for item in tested.reliability) == 5 * 240

    def test_the_same_inputs_give_the_same_model(
        self, fitted: PostseasonModel, postseason_league, eras
    ) -> None:  # type: ignore[no-untyped-def]
        again = fit_postseason_model(
            postseason_league[2], SPEC, eras, revision=1, fitted_at=AT, value_model_version="r1"
        )
        assert again == fitted

    def test_without_enough_history_the_test_cannot_run(self, postseason_league, eras) -> None:  # type: ignore[no-untyped-def]
        frames = postseason_league[2]
        late = PostseasonSpec(first_test_season="2030-31", resamples=50, kept_draws=10)
        with pytest.raises(NotEnoughHistory, match="tested from 2030-31 and needs 5 seasons"):
            fit_postseason_model(
                frames, late, eras, revision=1, fitted_at=AT, value_model_version="r1"
            )
        one = {
            name: frame[frame["season"] == "2005-06"] if "season" in frame.columns else frame
            for name, frame in frames.items()
        }
        with pytest.raises(NotEnoughHistory, match="needs 3 seasons of playoffs before that"):
            fit_postseason_model(
                one, SPEC, eras, revision=1, fitted_at=AT, value_model_version="r1"
            )
        none = {name: frame.iloc[0:0] for name, frame in frames.items()}
        with pytest.raises(NotEnoughHistory, match="no decided playoff games"):
            fit_postseason_model(
                none, SPEC, eras, revision=1, fitted_at=AT, value_model_version="r1"
            )
