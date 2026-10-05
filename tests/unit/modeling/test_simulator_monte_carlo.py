"""Seasons drawn for a roster: without noise they are the sum of the parts, and with it
they spread as the parameters say."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from front_office.domain.postseason import Step, StepDraw
from front_office.domain.scenario import Availability, Development
from front_office.domain.simulator import (
    Coverage,
    DevelopmentBand,
    FittedOn,
    MissedGames,
    Quantile,
    SimulatorModel,
    SimulatorSpec,
    WinsTest,
)
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.modeling.simulator import (
    ROSTER_COLUMNS,
    draw_missed,
    expected_rating,
    simulate,
)
from front_office.modeling.simulator.monte_carlo import stage_frame, summarise_wins
from tests import postseason_reference as reference

REPLACEMENT = -2.0
WEIGHTS = [
    (-0.5, 0.9, 0.5),
    (-3.0, 0.4, 0.7),
    (-1.7, 0.25, 0.15),
    (-2.2, 0.0, 0.8),
    (-2.7, 0.3, 0.2),
]


def steps(draws: int = 3, jitter: float = 0.0) -> tuple[Step, ...]:
    return tuple(
        Step(
            key=key,
            from_key=None if position == 0 else BRACKET_STAGE_KEYS[position - 1],
            intercept=a,
            net_rating=b,
            net_low=b,
            net_high=b,
            top_players=c,
            top_low=c,
            top_high=c,
            teams=100,
            reached=50,
            draws=tuple(
                StepDraw(intercept=a + jitter * number, net_rating=b, top_players=c)
                for number in range(draws)
            ),
        )
        for position, (key, (a, b, c)) in enumerate(zip(BRACKET_STAGE_KEYS, WEIGHTS, strict=True))
    )


def model_with(
    *,
    spread: float = 0.0,
    mean_miss: float = 0.0,
    strength_error: float = 0.0,
    noise: float = 0.0,
    residual: float = 0.0,
    missed: tuple[float, ...] = (0.0, 0.0, 0.0),
    missed_mean: float = 0.0,
    wins_per_point: float = 2.5,
) -> SimulatorModel:
    """Parameters chosen by hand. ``missed`` are the values at the 0th, 75th and 100th
    percentiles of the missed-games distribution."""
    return SimulatorModel(
        revision=1,
        fitted_at=datetime(2026, 10, 5, 12),
        spec=SimulatorSpec(missed_quantiles=(0.0, 0.75, 1.0)),
        value_model_version="r1",
        postseason_model_version="p1",
        fitted_on=FittedOn(
            first_season="2000-01", last_season="2013-14", team_seasons=1, games=1, player_seasons=1
        ),
        value_error=float(np.sqrt(strength_error**2 + noise**2)),
        season_noise=noise,
        strength_error=strength_error,
        noise_by_era=(),
        wins_season="2013-14",
        wins_per_point=wins_per_point,
        wins_residual=residual,
        development=(
            DevelopmentBand(lower=0.0, upper=1.0, players=10, mean_miss=mean_miss, spread=spread),
        ),
        missed=MissedGames(
            players=10,
            mean=missed_mean,
            quantiles=tuple(
                Quantile(level=level, value=value)
                for level, value in zip((0.0, 0.75, 1.0), missed, strict=True)
            ),
        ),
        test=WinsTest(
            team_seasons=1,
            first_test_season="2006-07",
            last_test_season="2006-07",
            mae=0.0,
            rmse=0.0,
            baseline_rmse=0.0,
            coverage=(Coverage(level=0.8, cases=1, covered=1),),
        ),
    )


def roster(
    impacts: list[float], shares: list[float], reliability: float = 0.8, **columns: list
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "projected_impact": impacts,
            "projected_share": shares,
            "projection_reliability": [reliability] * len(impacts),
            "games_missed": [np.nan] * len(impacts),
            "development": [np.nan] * len(impacts),
            "share": [np.nan] * len(impacts),
        },
        index=pd.Index(range(1, len(impacts) + 1), name="player_id"),
    )
    for column, values in columns.items():
        frame[column] = values
    return frame[list(ROSTER_COLUMNS)]


FIVE = roster([4.0, 2.0, 0.0, -1.0, -3.0], [1.0, 1.0, 1.0, 1.0, 1.0])


class TestWithoutNoise:
    def test_a_season_is_the_sum_of_the_parts(self) -> None:
        model = model_with()
        drawn = simulate(FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=50)
        rating = 5 * REPLACEMENT + sum((i - REPLACEMENT) * 1.0 for i in [4.0, 2.0, 0.0, -1.0, -3.0])
        assert drawn.strength == pytest.approx(rating) and rating == pytest.approx(2.0)
        assert expected_rating(FIVE, REPLACEMENT) == pytest.approx(rating)
        assert drawn.rating == pytest.approx(rating)
        assert drawn.wins == pytest.approx(41 + 2.5 * rating)
        assert drawn.top_players == pytest.approx((4.0 + 2.0 + 0.0) / 3)
        assert drawn.shares == pytest.approx(5.0)
        assert (drawn.players, drawn.projected, drawn.seasons) == (5, 5, 50)
        chances = reference.chain_probabilities(WEIGHTS, rating, 2.0)
        for key, expected in zip(BRACKET_STAGE_KEYS, chances, strict=True):
            assert drawn.chances[key] == pytest.approx(expected)
            assert drawn.stage_probability(key) == pytest.approx(expected)
            assert drawn.intervals[key] == pytest.approx((expected, expected))

    def test_the_parts_scale_down_when_shares_run_over_a_season(self) -> None:
        over = roster([4.0, 4.0], [3.0, 3.0])
        drawn = simulate(
            over, model=model_with(), steps=steps(), replacement=REPLACEMENT, simulations=5
        )
        assert drawn.shares == pytest.approx(6.0)
        assert drawn.strength == pytest.approx(5 * REPLACEMENT + (5 / 6) * 2 * 6.0 * 3.0)
        assert expected_rating(over, REPLACEMENT) == pytest.approx(drawn.strength[0])

    def test_removing_a_player_lowers_the_rating_and_a_share_set_by_hand_stands(self) -> None:
        model = model_with()
        fewer = FIVE.drop(index=1)
        assert expected_rating(fewer, REPLACEMENT) < expected_rating(FIVE, REPLACEMENT)
        halved = FIVE.copy()
        halved.loc[1, "share"] = 0.5
        drawn = simulate(halved, model=model, steps=steps(), replacement=REPLACEMENT, simulations=5)
        assert drawn.strength == pytest.approx(2.0 - (4.0 - REPLACEMENT) * 0.5)
        assert drawn.shares == pytest.approx(4.5)

    def test_a_player_without_a_projection_counts_as_a_replacement_player(self) -> None:
        with_rookie = roster([4.0, np.nan], [1.0, np.nan])
        drawn = simulate(
            with_rookie, model=model_with(), steps=steps(), replacement=REPLACEMENT, simulations=5
        )
        assert drawn.projected == 1 and drawn.players == 2
        assert drawn.strength == pytest.approx(5 * REPLACEMENT + (4.0 - REPLACEMENT))
        assert drawn.top_players == pytest.approx(4.0)

    def test_an_emptied_roster_is_five_replacement_players(self) -> None:
        nobody = roster([], [])
        drawn = simulate(
            nobody, model=model_with(), steps=steps(), replacement=REPLACEMENT, simulations=20
        )
        assert drawn.rating == pytest.approx(5 * REPLACEMENT)
        assert drawn.top_players == pytest.approx(REPLACEMENT)
        assert drawn.shares == pytest.approx(0.0)
        assert (drawn.players, drawn.projected) == (0, 0)

    def test_development_presets_step_every_player_by_the_bands_typical_size(self) -> None:
        model = model_with(mean_miss=-0.5, spread=1.0)
        plain = simulate(
            FIVE, model=model_with(), steps=steps(), replacement=REPLACEMENT, simulations=5
        )
        expected = simulate(
            FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=2000, seed=1
        )
        up = simulate(
            FIVE,
            model=model,
            steps=steps(),
            replacement=REPLACEMENT,
            development=Development.OPTIMISTIC,
            simulations=2000,
            seed=1,
        )
        down = simulate(
            FIVE,
            model=model,
            steps=steps(),
            replacement=REPLACEMENT,
            development=Development.REGRESSION,
            simulations=2000,
            seed=1,
        )
        # Five players each shifted by the typical miss, then one spread up or down.
        assert expected.strength.mean() == pytest.approx(plain.strength[0] - 5 * 0.5, abs=0.15)
        assert up.strength.mean() == pytest.approx(expected.strength.mean() + 5 * 1.0, abs=0.15)
        assert down.strength.mean() == pytest.approx(expected.strength.mean() - 5 * 1.0, abs=0.15)
        assert expected.strength.std() > 0.5

    def test_a_development_figure_of_the_users_own_replaces_the_preset(self) -> None:
        model = model_with(mean_miss=-0.5)
        own = FIVE.copy()
        own.loc[1, "development"] = 2.0
        drawn = simulate(
            own,
            model=model,
            steps=steps(),
            replacement=REPLACEMENT,
            development=Development.REGRESSION,
            simulations=5,
        )
        # Player 1 moves by exactly +2; the other four by the preset, -0.5 each.
        assert drawn.strength == pytest.approx(2.0 + 2.0 - 4 * 0.5)


class TestAvailability:
    def test_missed_games_are_read_off_the_measured_distribution(self) -> None:
        model = model_with(missed=(0.0, 0.2, 0.6))
        assert draw_missed(model, np.array([0.0, 0.375, 0.75, 1.0])) == pytest.approx(
            [0.0, 0.1, 0.2, 0.6]
        )

    def test_healthy_raises_the_shares_and_a_high_injury_season_lowers_them(self) -> None:
        # Rotation players typically miss a tenth of a season: a projected share already
        # allows for it, so a healthy season gives a tenth more.
        model = model_with(missed=(0.1, 0.1, 0.1), missed_mean=0.1)
        healthy = simulate(
            FIVE,
            model=model,
            steps=steps(),
            replacement=REPLACEMENT,
            availability=Availability.HEALTHY,
            simulations=5,
        )
        projected = simulate(
            FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=5
        )
        hurt = simulate(
            FIVE,
            model=model,
            steps=steps(),
            replacement=REPLACEMENT,
            availability=Availability.HIGH_INJURY,
            simulations=5,
        )
        assert projected.shares == pytest.approx(5.0)
        assert healthy.shares == pytest.approx(5.0 / 0.9)
        assert hurt.shares == pytest.approx(5.0)  # the 75th percentile is the mean here
        # Five full shares already fill the floor, so scaling undoes the gain; with a
        # floor left uncovered, a healthy season puts the players on it for longer.
        assert healthy.strength[0] == pytest.approx(projected.strength[0])
        four = FIVE.drop(index=5)
        fuller = simulate(
            four,
            model=model,
            steps=steps(),
            replacement=REPLACEMENT,
            availability=Availability.HEALTHY,
            simulations=5,
        )
        usual = simulate(four, model=model, steps=steps(), replacement=REPLACEMENT, simulations=5)
        assert fuller.shares == pytest.approx(4.0 / 0.9) and fuller.strength[0] > usual.strength[0]

    def test_games_missed_set_by_hand_shift_a_players_share(self) -> None:
        model = model_with(missed=(0.1, 0.1, 0.1), missed_mean=0.1)
        own = FIVE.copy()
        own.loc[1, "games_missed"] = 41.0
        drawn = simulate(own, model=model, steps=steps(), replacement=REPLACEMENT, simulations=5)
        # Player 1 plays half the season instead of nine tenths of it.
        assert drawn.shares == pytest.approx(4.0 + (1.0 / 0.9) * 0.5)
        gone = FIVE.copy()
        gone.loc[1, "games_missed"] = 82.0
        out = simulate(gone, model=model, steps=steps(), replacement=REPLACEMENT, simulations=5)
        assert out.shares == pytest.approx(4.0)
        assert out.top_players == pytest.approx((2.0 + 0.0 - 1.0) / 3)

    def test_the_draws_spread_each_player_around_the_target(self) -> None:
        model = model_with(missed=(0.0, 0.2, 0.4), missed_mean=0.15)
        drawn = simulate(
            FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=4000, seed=2
        )
        # Each player's share is the projection times (1 - missed) / (1 - mean): on average one.
        assert drawn.shares.mean() == pytest.approx(5.0, abs=0.05)
        assert drawn.shares.std() > 0.1


class TestNoise:
    def test_the_seasons_are_reproducible_and_spread_as_the_parameters_say(self) -> None:
        model = model_with(strength_error=2.0, noise=1.5, residual=3.0, wins_per_point=2.0)
        one = simulate(
            FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=20000, seed=7
        )
        two = simulate(
            FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=20000, seed=7
        )
        assert np.array_equal(one.wins, two.wins) and np.array_equal(one.strength, two.strength)
        assert one.strength.mean() == pytest.approx(2.0, abs=0.05)
        assert one.strength.std() == pytest.approx(2.0, abs=0.05)
        assert one.rating.std() == pytest.approx(np.sqrt(2.0**2 + 1.5**2), abs=0.06)
        wins_sd = np.sqrt((2.0 * np.sqrt(2.0**2 + 1.5**2)) ** 2 + 3.0**2)
        assert one.wins.std() == pytest.approx(wins_sd, abs=0.1)
        assert one.wins.min() >= 0 and one.wins.max() <= 82

    def test_the_players_own_spread_comes_out_of_the_team_level_miss(self) -> None:
        # With a spread of 1 on five players at a full share, the parts alone spread the
        # team by sqrt(5); the team-level miss fills the rest up to the strength error.
        model = model_with(spread=1.0, strength_error=3.0)
        drawn = simulate(
            FIVE, model=model, steps=steps(), replacement=REPLACEMENT, simulations=20000, seed=3
        )
        assert drawn.strength.std() == pytest.approx(3.0, abs=0.08)
        wider = model_with(spread=2.0, strength_error=3.0)
        more = simulate(
            FIVE, model=wider, steps=steps(), replacement=REPLACEMENT, simulations=20000, seed=3
        )
        # The players' spread alone (sqrt(20)) exceeds the strength error: nothing is taken off.
        assert more.strength.std() == pytest.approx(np.sqrt(20.0), abs=0.1)

    def test_intervals_come_from_the_postseason_models_resampled_steps(self) -> None:
        model = model_with()
        drawn = simulate(
            FIVE,
            model=model,
            steps=steps(draws=5, jitter=0.2),
            replacement=REPLACEMENT,
            simulations=10,
        )
        for key in BRACKET_STAGE_KEYS:
            low, high = drawn.intervals[key]
            assert low <= drawn.stage_probability(key) <= high or low < high


class TestSummaries:
    def test_wins_are_counted_by_total_and_stages_tabled(self) -> None:
        counts = summarise_wins(np.array([40.2, 40.4, 41.0, 82.0]))
        assert list(counts.columns) == ["wins", "share"] and len(counts) == 83
        assert counts.set_index("wins")["share"].loc[[40, 41, 82]].tolist() == [0.5, 0.25, 0.25]
        drawn = simulate(
            FIVE, model=model_with(), steps=steps(), replacement=REPLACEMENT, simulations=5
        )
        table = stage_frame(drawn, {key: key.upper() for key in BRACKET_STAGE_KEYS})
        assert list(table.columns) == ["key", "label", "probability", "low", "high"]
        assert (
            table["label"].iloc[0] == "MADE_PLAYOFFS"
            and table["probability"].is_monotonic_decreasing
        )
