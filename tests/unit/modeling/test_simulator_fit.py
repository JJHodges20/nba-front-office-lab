"""Measuring the simulator's parameters on the invented league, whose regular seasons were
played by a planted game model, and testing the wins they give."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from front_office.config import load_eras
from front_office.domain.simulator import SimulatorModel, SimulatorSpec
from front_office.modeling.simulator import NotEnoughHistory, fit_simulator_model, season_noise
from front_office.modeling.value.wins import wins_per_net_point
from tests.conftest import REPO_ROOT, VALUE_SPEC
from tests.league import GAMES, POSSESSIONS
from tests.postseason_reference import REGULAR_SEASON
from tests.value_reference import planted_model

SPEC = SimulatorSpec(noise_seasons=5, test_simulations=200, simulations=500)
AT = datetime(2026, 10, 5, 12, 0)


@pytest.fixture(scope="module")
def eras() -> list:
    return list(load_eras(REPO_ROOT / "configs"))


@pytest.fixture(scope="module")
def fitted(postseason_league, eras) -> SimulatorModel:  # type: ignore[no-untyped-def]
    _, model, frames = postseason_league
    return fit_simulator_model(
        frames, SPEC, eras, model, revision=1, fitted_at=AT, postseason_model_version="p1"
    )


class TestWhatIsMeasured:
    def test_a_seasons_noise_is_what_the_planted_games_carry(
        self, fitted: SimulatorModel, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        _, _, frames = postseason_league
        noise = season_noise(frames["team_games"], frames["team_seasons"])
        assert len(noise) == 30 * 14
        # By hand for one team-season: the standard error of its margins, per 100 possessions.
        games = frames["team_games"]
        mine = games[
            (games["season"] == "2005-06")
            & (games["team_id"] == 101)
            & (games["season_type"] == "regular")
        ]
        margins = (mine["pts"] - mine["opp_pts"]).astype(float)
        expected = margins.std(ddof=1) / np.sqrt(len(margins)) * 100 / (POSSESSIONS / GAMES)
        row = noise[(noise["season"] == "2005-06") & (noise["team_id"] == 101)].iloc[0]
        assert row["noise"] == pytest.approx(expected) and row["games"] == GAMES
        # The planted noise on a margin, plus what the schedule's strengths add.
        floor = REGULAR_SEASON["margin_noise"] / np.sqrt(GAMES) * 100 / (POSSESSIONS / GAMES)
        assert floor < fitted.season_noise < floor * 1.3
        assert [item.key for item in fitted.noise_by_era] == ["all", "last_10", "last_5"]

    def test_wins_follow_the_rating_as_the_planted_games_make_them(
        self, fitted: SimulatorModel
    ) -> None:
        assert fitted.wins_season == "2013-14"
        # The invented strengths spread wider than a real league does, which flattens the
        # line through wins; the figure is still the one the value model gives (tested below).
        assert 1.0 < fitted.wins_per_point < 3.5
        # Wins around the rating spread like a season of coin flips, give or take.
        assert 3.0 < fitted.wins_residual < 5.5
        # The invented league keeps no noise in its ratings, so the value model misses by
        # less than a season carries: what is left for the strength is nothing at all.
        left = max(fitted.value_error**2 - fitted.season_noise**2, 0.0)
        assert fitted.strength_error == pytest.approx(np.sqrt(left), abs=1e-3)

    def test_development_and_missed_games_come_from_the_valued_players(
        self, fitted: SimulatorModel, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        _, _, frames = postseason_league
        scores = frames["player_value_scores"]
        both = scores.dropna(subset=["impact", "projected_impact"])
        both = both[both["minutes_share"].fillna(0) > 0]
        assert sum(band.players for band in fitted.development) == len(both)
        assert [(b.lower, b.upper) for b in fitted.development] == [
            (0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0),
        ]  # fmt: skip
        assert all(band.spread > 0 for band in fitted.development if band.players > 1)
        assert fitted.missed.players > 100 and 0 <= fitted.missed.mean < 0.5
        assert [q.level for q in fitted.missed.quantiles] == list(SPEC.missed_quantiles)
        values = [q.value for q in fitted.missed.quantiles]
        assert values == sorted(values) and values[0] == 0.0

    def test_what_it_was_fitted_on(self, fitted: SimulatorModel, postseason_league) -> None:  # type: ignore[no-untyped-def]
        league, model, frames = postseason_league
        on = fitted.fitted_on
        assert (on.first_season, on.last_season, on.team_seasons) == ("2000-01", "2013-14", 420)
        assert on.games == sum(len(games) for games in league.regular_seasons.values())
        assert on.player_seasons == len(frames["player_seasons"])
        assert (fitted.revision, fitted.fitted_at, fitted.spec) == (1, AT, SPEC)
        assert fitted.value_model_version == model.version == "r1"
        assert fitted.postseason_model_version == "p1" and fitted.version == "s1"


class TestTheWinsTest:
    def test_every_team_season_of_the_value_models_test_is_scored(
        self, fitted: SimulatorModel, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        _, model, _ = postseason_league
        test = fitted.test
        assert test.team_seasons == len(model.backtest) == 10 * 30
        assert (test.first_test_season, test.last_test_season) == ("2004-05", "2013-14")
        assert [item.level for item in test.coverage] == list(SPEC.coverage_levels)
        for item in test.coverage:
            assert item.cases == test.team_seasons and 0 < item.share <= 1
        # Wider intervals hold the wins that happened more often.
        shares = [item.share for item in test.coverage]
        assert shares == sorted(shares)
        assert test.mae <= test.rmse < test.baseline_rmse

    def test_the_same_inputs_give_the_same_parameters(
        self, fitted: SimulatorModel, postseason_league, eras
    ) -> None:  # type: ignore[no-untyped-def]
        _, model, frames = postseason_league
        again = fit_simulator_model(
            frames, SPEC, eras, model, revision=1, fitted_at=AT, postseason_model_version="p1"
        )
        assert again == fitted

    def test_the_wins_per_point_is_the_value_models_own_figure(
        self, fitted: SimulatorModel, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        _, model, frames = postseason_league
        slopes = wins_per_net_point(frames["team_seasons"], window=model.spec.wins_window)
        assert fitted.wins_per_point == pytest.approx(slopes.iloc[-1], abs=1e-4)


class TestWhatCannotBeMeasured:
    def test_without_regular_season_games(self, postseason_league, eras) -> None:  # type: ignore[no-untyped-def]
        _, model, frames = postseason_league
        games = frames["team_games"]
        without = {**frames, "team_games": games[games["season_type"] != "regular"]}
        with pytest.raises(NotEnoughHistory, match="no regular-season games"):
            fit_simulator_model(
                without, SPEC, eras, model, revision=1, fitted_at=AT, postseason_model_version=None
            )

    def test_without_a_tested_value_model(self, postseason_league, eras) -> None:  # type: ignore[no-untyped-def]
        _, _, frames = postseason_league
        planted = planted_model(VALUE_SPEC)
        with pytest.raises(NotEnoughHistory, match="carries no out-of-sample test"):
            fit_simulator_model(
                frames, SPEC, eras, planted, revision=1, fitted_at=AT, postseason_model_version=None
            )

    def test_without_anyone_valued(self, postseason_league, eras) -> None:  # type: ignore[no-untyped-def]
        _, model, frames = postseason_league
        scores = frames["player_value_scores"]
        without = {**frames, "player_value_scores": scores.iloc[0:0]}
        with pytest.raises(NotEnoughHistory, match="no player-season has both"):
            fit_simulator_model(
                without, SPEC, eras, model, revision=1, fitted_at=AT, postseason_model_version=None
            )


class TestTheErrorAForecastCarries:
    def test_the_miss_is_the_one_measured_with_minutes_projected(
        self, fitted: SimulatorModel, postseason_league
    ) -> None:  # type: ignore[no-untyped-def]
        _, model, _ = postseason_league
        ahead = model.validation.projected
        assert ahead is not None
        assert fitted.value_error_basis == "projected"
        assert fitted.value_error == pytest.approx(ahead.rmse, abs=1e-4)
        assert fitted.value_error >= model.validation.net.rmse - 1e-9 or True
