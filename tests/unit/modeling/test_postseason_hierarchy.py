"""The season model: conditional steps multiplied up, and the chances they give a team."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.postseason import PostseasonSpec, Step, StepDraw
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.modeling.postseason import STEP_COLUMNS, stage_probabilities, step_weights
from front_office.modeling.postseason.fitting import logistic
from front_office.modeling.postseason.hierarchy import apply_steps, fit_step_weights, fit_steps
from tests import postseason_reference as reference

WEIGHTS = [
    (-0.5, 0.9, 0.5),
    (-3.0, 0.4, 0.7),
    (-1.7, 0.25, 0.15),
    (-2.2, 0.0, 0.8),
    (-2.7, 0.3, 0.2),
]
"""Intercept, net rating and top-player weights of each planted step."""


def steps_from(weights: list[tuple[float, float, float]], draws: int = 3) -> tuple[Step, ...]:
    return tuple(
        Step(
            key=key,
            from_key=None if position == 0 else BRACKET_STAGE_KEYS[position - 1],
            intercept=a,
            net_rating=b,
            net_low=b - 0.1,
            net_high=b + 0.1,
            top_players=c,
            top_low=c - 0.1,
            top_high=c + 0.1,
            teams=100,
            reached=50,
            draws=tuple(
                StepDraw(intercept=a + 0.01 * number, net_rating=b, top_players=c)
                for number in range(draws)
            ),
        )
        for position, (key, (a, b, c)) in enumerate(zip(BRACKET_STAGE_KEYS, weights, strict=True))
    )


def planted_teams(seed: int = 0, count: int = 3000) -> pd.DataFrame:
    """Team-seasons whose stages follow the planted steps, each stage drawn only for the
    teams that reached the one before."""
    generator = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "start_year": generator.integers(2000, 2010, count),
            "net_rating": generator.normal(0, 4, count),
            "top_players": generator.normal(2, 1.5, count),
            "decided": True,
        }
    )
    alive = np.ones(count, dtype=bool)
    for key, (a, b, c) in zip(BRACKET_STAGE_KEYS, WEIGHTS, strict=True):
        chance = logistic(
            a + b * frame["net_rating"].to_numpy() + c * frame["top_players"].to_numpy()
        )
        reached = alive & (generator.random(count) < chance)
        frame[key] = reached
        alive = reached
    return frame


class TestSteps:
    def test_conditional_steps_recover_planted_weights(self) -> None:
        fitted = fit_step_weights(planted_teams(count=20000), STEP_COLUMNS)
        assert len(fitted) == 5
        # The first steps have thousands of cases behind them.
        for weights, planted in zip(fitted[:2], WEIGHTS[:2], strict=True):
            assert weights == pytest.approx(planted, abs=0.15)

    def test_direct_fits_use_every_team_for_every_stage(self) -> None:
        frame = planted_teams()
        direct = fit_step_weights(frame, STEP_COLUMNS, direct=True)
        conditional = fit_step_weights(frame, STEP_COLUMNS)
        assert direct[0] == pytest.approx(conditional[0])
        assert not np.allclose(direct[1], conditional[1])

    def test_applied_steps_nest_and_match_the_chain_by_hand(self) -> None:
        frame = planted_teams(count=500)
        weights = fit_step_weights(frame, STEP_COLUMNS)
        chances = apply_steps(weights, frame, STEP_COLUMNS)
        assert chances.shape == (500, 5)
        assert np.all(np.diff(chances, axis=1) <= 1e-12)
        inputs = frame[list(STEP_COLUMNS)].to_numpy()
        by_hand = np.cumprod([logistic(inputs @ w[1:] + w[0]) for w in weights], axis=0).T
        assert chances == pytest.approx(by_hand)
        direct = apply_steps(weights, frame, STEP_COLUMNS, direct=True)
        assert direct[:, 1] == pytest.approx(logistic(inputs @ weights[1][1:] + weights[1][0]))

    def test_fit_steps_describes_each_step_with_intervals_and_draws(self) -> None:
        frame = planted_teams(count=1500)
        spec = PostseasonSpec(resamples=30, kept_draws=10)
        steps = fit_steps(frame, spec)
        assert tuple(step.key for step in steps) == BRACKET_STAGE_KEYS
        assert steps[0].from_key is None and steps[1].from_key == "made_playoffs"
        assert steps[0].teams == 1500 and steps[0].reached == int(frame["made_playoffs"].sum())
        assert steps[1].teams == steps[0].reached
        assert steps[1].reached == int(frame["won_a_round"].sum())
        for step in steps:
            assert step.net_low <= step.net_high and step.top_low <= step.top_high
            assert len(step.draws) == 10
        with pytest.raises(ValueError, match="no decided team-seasons"):
            fit_steps(frame.assign(decided=False), spec)


class TestStageProbabilities:
    def test_the_chain_by_hand(self) -> None:
        chances = stage_probabilities(steps_from(WEIGHTS), 4.0, 2.5)
        assert list(chances) == list(BRACKET_STAGE_KEYS)
        assert [chances[key] for key in BRACKET_STAGE_KEYS] == pytest.approx(
            reference.chain_probabilities(WEIGHTS, 4.0, 2.5)
        )

    def test_draws_give_one_chance_per_kept_parameter_set(self) -> None:
        steps = steps_from(WEIGHTS, draws=4)
        sampled = stage_probabilities(steps, 4.0, 2.5, draws=True)
        assert all(np.asarray(sampled[key]).shape == (4,) for key in BRACKET_STAGE_KEYS)
        weights = step_weights(steps, draws=True)
        assert weights.shape == (4, 5, 3) and step_weights(steps).shape == (5, 3)
        first = [tuple(row) for row in weights[0]]
        assert np.asarray(sampled["won_championship"])[0] == pytest.approx(
            reference.chain_probabilities(first, 4.0, 2.5)[-1]
        )

    def test_an_uncertain_rating_is_integrated_over(self) -> None:
        steps = steps_from(WEIGHTS)
        chances = stage_probabilities(steps, 4.0, 2.5, error=3.0)
        expected = reference.integrated_chain(WEIGHTS, 4.0, 2.5, 3.0)
        assert [chances[key] for key in BRACKET_STAGE_KEYS] == pytest.approx(expected, abs=1e-4)
        plain = stage_probabilities(steps, 4.0, 2.5)
        for none in (None, 0.0, -1.0):
            assert stage_probabilities(steps, 4.0, 2.5, error=none) == pytest.approx(plain)

    def test_uncertainty_pulls_a_strong_team_down_and_a_weak_one_up(self) -> None:
        steps = steps_from(WEIGHTS)
        strong = stage_probabilities(steps, 8.0, 3.0)
        strong_unsure = stage_probabilities(steps, 8.0, 3.0, error=4.0)
        weak = stage_probabilities(steps, -6.0, 0.0)
        weak_unsure = stage_probabilities(steps, -6.0, 0.0, error=4.0)
        assert strong_unsure["made_playoffs"] < strong["made_playoffs"]
        assert weak_unsure["made_playoffs"] > weak["made_playoffs"]
