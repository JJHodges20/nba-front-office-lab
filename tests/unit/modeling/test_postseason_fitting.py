"""The arithmetic the postseason model shares: a logistic fit, scores for probabilities,
calibration, reliability, and intervals from resampling seasons."""

from __future__ import annotations

import numpy as np
import pytest

from front_office.domain.postseason import Calibration
from front_office.modeling.postseason.fitting import (
    brier,
    calibration,
    difference_interval,
    fit_logistic,
    log_loss,
    logistic,
    logit,
    percentile_interval,
    reliability,
    rounded,
    row_losses,
    season_draws,
    season_members,
)


def simulated(weights: list[float], n: int = 20000, seed: int = 0) -> tuple:
    """Outcomes drawn from a logistic model with the given weights on an intercept and two
    normal inputs: the design, the true chances and what happened."""
    generator = np.random.default_rng(seed)
    design = np.column_stack([np.ones(n), generator.normal(size=n), generator.normal(size=n)])
    chances = logistic(design @ np.asarray(weights))
    outcome = (generator.random(n) < chances).astype(float)
    return design, chances, outcome


class TestLogistic:
    def test_recovers_planted_weights(self) -> None:
        design, _, outcome = simulated([0.3, 1.2, -0.8])
        assert fit_logistic(design, outcome) == pytest.approx([0.3, 1.2, -0.8], abs=0.06)

    def test_a_perfectly_separated_input_still_finishes(self) -> None:
        design = np.column_stack([np.ones(40), np.linspace(-2, 2, 40)])
        outcome = (design[:, 1] > 0).astype(float)
        fitted = fit_logistic(design, outcome)
        assert np.all(np.isfinite(fitted)) and fitted[1] > 5

    def test_logit_and_logistic_invert_and_the_ends_are_clipped(self) -> None:
        chances = np.array([0.1, 0.5, 0.9])
        assert logistic(logit(chances)) == pytest.approx(chances)
        ends = logit(np.array([0.0, 1.0]))
        assert np.all(np.isfinite(ends)) and ends[0] < -20 and ends[1] > 20

    def test_design_and_outcome_must_agree(self) -> None:
        with pytest.raises(ValueError, match="one row per outcome"):
            fit_logistic(np.ones((3, 1)), np.ones(2))


class TestScores:
    def test_log_loss_and_brier_by_hand(self) -> None:
        chances, outcome = np.array([0.8, 0.3]), np.array([1.0, 0.0])
        assert row_losses(chances, outcome) == pytest.approx([-np.log(0.8), -np.log(0.7)])
        assert log_loss(chances, outcome) == pytest.approx((-np.log(0.8) - np.log(0.7)) / 2)
        assert brier(chances, outcome) == pytest.approx((0.04 + 0.09) / 2)
        assert log_loss(np.array([0.5, 0.5]), outcome) == pytest.approx(np.log(2))

    def test_a_certain_wrong_call_costs_dearly_but_not_infinitely(self) -> None:
        loss = log_loss(np.array([1.0]), np.array([0.0]))
        assert np.isfinite(loss) and loss > 20


class TestCalibration:
    def test_chances_that_mean_what_they_say_have_slope_one(self) -> None:
        _, chances, outcome = simulated([0.0, 1.0, 0.5], n=40000)
        fitted = calibration(chances, outcome)
        assert fitted.slope == pytest.approx(1.0, abs=0.06)
        assert fitted.intercept == pytest.approx(0.0, abs=0.06)

    def test_chances_too_sure_of_themselves_have_a_slope_below_one(self) -> None:
        _, chances, outcome = simulated([0.0, 1.0, 0.5], n=40000)
        sharpened = logistic(2 * logit(chances))
        assert calibration(sharpened, outcome).slope == pytest.approx(0.5, abs=0.05)

    def test_a_constant_chance_has_nothing_to_fit(self) -> None:
        fitted = calibration(np.full(5, 0.3), np.array([1.0, 0.0, 0.0, 1.0, 0.0]))
        assert fitted == Calibration(slope=1.0, intercept=0.4)


class TestReliability:
    def test_bands_hold_their_lower_edge_and_the_last_includes_one(self) -> None:
        chances = np.array([0.0, 0.05, 0.1, 0.5, 0.99, 1.0])
        outcome = np.array([0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        bins = reliability(chances, outcome, (0.0, 0.1, 0.5, 1.0), confidence=0.95)
        assert [(item.lower, item.upper, item.cases) for item in bins] == [
            (0.0, 0.1, 2),
            (0.1, 0.5, 1),
            (0.5, 1.0, 3),
        ]
        assert bins[0].observed == 0.0 and bins[1].observed == 1.0
        assert bins[2].predicted == pytest.approx(round((0.5 + 0.99 + 1.0) / 3, 4))
        assert bins[0].low == 0.0 and 0 < bins[0].high < 1
        assert bins[2].high == 1.0 and 0 < bins[2].low < 1

    def test_empty_bands_are_left_out(self) -> None:
        bins = reliability(
            np.array([0.9, 0.95]), np.array([1.0, 0.0]), (0.0, 0.5, 1.0), confidence=0.95
        )
        assert [(item.lower, item.upper, item.cases) for item in bins] == [(0.5, 1.0, 2)]


class TestResampling:
    def test_seasons_are_the_unit_and_draws_repeat_for_a_seed(self) -> None:
        seasons = np.array([2000, 2001, 2001, 2002])
        distinct, members = season_members(seasons)
        assert list(distinct) == [2000, 2001, 2002]
        assert [group.tolist() for group in members] == [[0], [1, 2], [3]]
        draws = season_draws(3, 5, seed=1)
        assert np.array_equal(draws, season_draws(3, 5, seed=1))
        assert draws.shape == (5, 3) and draws.min() >= 0 and draws.max() < 3

    def test_a_percentile_interval_ignores_missing_values(self) -> None:
        low, high = percentile_interval(np.array([1.0, 2.0, np.nan, 3.0, 4.0]), 0.5)
        assert (low, high) == (1.75, 3.25)

    def test_identical_losses_differ_by_nothing(self) -> None:
        losses = np.array([0.5, 0.6, 0.7, 0.8])
        seasons = np.array([1, 1, 2, 2])
        assert difference_interval(
            losses, losses, seasons, resamples=50, seed=0, confidence=0.95
        ) == (0.0, 0.0, 0.0)

    def test_the_interval_stays_within_the_seasons_own_gaps(self) -> None:
        other = np.array([0.6, 0.6, 0.9, 0.9])
        model = np.array([0.5, 0.5, 0.7, 0.7])
        seasons = np.array([1, 1, 2, 2])
        difference, low, high = difference_interval(
            other, model, seasons, resamples=400, seed=0, confidence=0.95
        )
        # One season's gap is 0.1, the other's 0.2: any resample of seasons lies between.
        assert difference == pytest.approx(0.15)
        assert 0.1 <= low <= 0.15 <= high <= 0.2


def test_rounded_gives_a_plain_float_to_four_places() -> None:
    assert rounded(0.123456) == 0.1235
    assert rounded(-0.0) == 0.0 and str(rounded(-0.0)) == "0.0"
    assert isinstance(rounded(np.float64(1)), float)
