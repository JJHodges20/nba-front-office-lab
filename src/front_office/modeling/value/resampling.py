"""Uncertainty from resampling whole seasons.

Teams of one season are not independent observations: they play each other, share a
rule book and a style of play. Resampling team-seasons one by one would treat them as
if they were and make every interval too narrow, so the unit that is drawn is the
season, with everything in it.
"""

from __future__ import annotations

import numpy as np

from front_office.domain.value_model import ValueSpec


def season_draws(seasons: np.ndarray, spec: ValueSpec) -> np.ndarray:
    """``spec.resamples`` draws of as many seasons as there are, with replacement.

    ``seasons`` are the distinct seasons. Each row of the result indexes into it. The
    draws depend only on the seed and on how many seasons there are, so two comparisons
    made over the same seasons are made on the same draws.
    """
    generator = np.random.default_rng(spec.seed)
    return generator.integers(0, len(seasons), size=(spec.resamples, len(seasons)))


def interval(values: np.ndarray, spec: ValueSpec) -> tuple[float, float]:
    """The central ``spec.confidence`` share of ``values``."""
    tail = 100 * (1 - spec.confidence) / 2
    low, high = np.percentile(values, [tail, 100 - tail])
    return float(low), float(high)


def rmse_differences(
    first: np.ndarray, second: np.ndarray, season_of: np.ndarray, spec: ValueSpec
) -> np.ndarray:
    """Root mean squared error of ``first`` minus that of ``second``, in every draw.

    ``first`` and ``second`` are the errors of two methods on the same observations and
    ``season_of`` the season each observation belongs to.
    """
    seasons, position = np.unique(season_of, return_inverse=True)
    counts = np.bincount(position, minlength=len(seasons)).astype("float64")
    squared_first = np.bincount(position, weights=first**2, minlength=len(seasons))
    squared_second = np.bincount(position, weights=second**2, minlength=len(seasons))
    draws = season_draws(seasons, spec)
    drawn = counts[draws].sum(axis=1)
    return np.sqrt(squared_first[draws].sum(axis=1) / drawn) - np.sqrt(
        squared_second[draws].sum(axis=1) / drawn
    )
