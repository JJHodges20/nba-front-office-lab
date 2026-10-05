"""The arithmetic the postseason model shares: a logistic fit, scores for probabilities,
reliability, calibration, and intervals from resampling seasons."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from front_office.analytics.benchmarks import wilson_interval
from front_office.domain.postseason import Calibration, ReliabilityBin

EPS = 1e-9
DECIMALS = 4
RIDGE = 1e-6
"""A trace of shrinkage, so that a fit with a perfectly separated input still finishes."""


def logistic(z: np.ndarray | float) -> np.ndarray | float:
    """The logistic function, written so that a huge log-odds never overflows: the exponent
    is always of a non-positive number."""
    values = np.asarray(z, dtype="float64")
    shrunk = np.exp(-np.abs(values))
    out = np.where(values >= 0, 1.0 / (1.0 + shrunk), shrunk / (1.0 + shrunk))
    return out if out.shape else float(out)


def logit(p: np.ndarray | float) -> np.ndarray:
    clipped = np.clip(np.asarray(p, dtype="float64"), EPS, 1 - EPS)
    return np.log(clipped / (1 - clipped))


def fit_logistic(
    design: np.ndarray, outcome: np.ndarray, *, ridge: float = RIDGE, iterations: int = 60
) -> np.ndarray:
    """Maximum-likelihood weights of a logistic regression by Newton's method.

    No intercept is added: put a column of ones in ``design`` to get one. ``ridge``
    shrinks the weights a trace toward zero, enough to finish when an input separates
    the outcomes perfectly and too little to move any weight the data decides.
    """
    X = np.asarray(design, dtype="float64")
    y = np.asarray(outcome, dtype="float64")
    if X.ndim != 2 or len(X) != len(y):
        raise ValueError("design must be a matrix with one row per outcome")
    beta = np.zeros(X.shape[1])
    penalty = ridge * np.eye(X.shape[1])
    for _ in range(iterations):
        p = logistic(X @ beta)
        weights = p * (1 - p) + 1e-12
        gradient = X.T @ (y - p) - ridge * beta
        hessian = (X * weights[:, None]).T @ X + penalty
        step = np.linalg.solve(hessian, gradient)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def row_losses(probability: np.ndarray, outcome: np.ndarray) -> np.ndarray:
    """Each case's log loss: how surprised the model was by what happened."""
    p = np.clip(np.asarray(probability, dtype="float64"), EPS, 1 - EPS)
    y = np.asarray(outcome, dtype="float64")
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def log_loss(probability: np.ndarray, outcome: np.ndarray) -> float:
    return float(np.mean(row_losses(probability, outcome)))


def brier(probability: np.ndarray, outcome: np.ndarray) -> float:
    p = np.asarray(probability, dtype="float64")
    y = np.asarray(outcome, dtype="float64")
    return float(np.mean((p - y) ** 2))


def calibration(probability: np.ndarray, outcome: np.ndarray) -> Calibration:
    """Outcomes regressed on the model's log-odds. With fewer than two distinct
    probabilities there is nothing to fit, and the slope is reported as 1."""
    z = logit(probability)
    y = np.asarray(outcome, dtype="float64")
    if len(z) < 2 or np.ptp(z) < 1e-9:
        return Calibration(slope=1.0, intercept=rounded(float(np.mean(y)) if len(y) else 0.0))
    fitted = fit_logistic(np.column_stack([np.ones(len(z)), z]), y, ridge=1e-4)
    return Calibration(slope=rounded(fitted[1]), intercept=rounded(fitted[0]))


def reliability(
    probability: np.ndarray,
    outcome: np.ndarray,
    edges: Sequence[float],
    *,
    confidence: float,
) -> tuple[ReliabilityBin, ...]:
    """Predicted against observed in bands of predicted probability. A band holds its lower
    edge and stops short of its upper one; the last band includes 1. Empty bands are left
    out."""
    p = np.asarray(probability, dtype="float64")
    y = np.asarray(outcome, dtype="float64")
    bins = []
    for lower, upper in zip(edges, edges[1:], strict=False):
        inside = (p >= lower) & ((p < upper) if upper < 1 else (p <= upper))
        if not inside.any():
            continue
        cases = int(inside.sum())
        reached = int(y[inside].sum())
        low, high = wilson_interval(pd.Series([reached]), pd.Series([cases]), confidence=confidence)
        bins.append(
            ReliabilityBin(
                lower=float(lower),
                upper=float(upper),
                cases=cases,
                predicted=rounded(p[inside].mean()),
                observed=rounded(reached / cases),
                low=rounded(low.iloc[0]),
                high=rounded(high.iloc[0]),
            )
        )
    return tuple(bins)


def season_members(seasons: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    """The distinct seasons of a column and, for each, the rows that belong to it."""
    distinct, position = np.unique(np.asarray(seasons), return_inverse=True)
    return distinct, [np.flatnonzero(position == index) for index in range(len(distinct))]


def season_draws(count: int, resamples: int, seed: int) -> np.ndarray:
    """Which seasons each resample takes: ``resamples`` rows of ``count`` indices drawn
    with replacement."""
    generator = np.random.default_rng(seed)
    return generator.integers(0, count, size=(resamples, count))


def percentile_interval(values: np.ndarray, confidence: float) -> tuple[float, float]:
    tail = 100 * (1 - confidence) / 2
    low, high = np.nanpercentile(np.asarray(values, dtype="float64"), [tail, 100 - tail], axis=0)
    return float(low), float(high)


def difference_interval(
    losses: np.ndarray,
    against: np.ndarray,
    seasons: np.ndarray,
    *,
    resamples: int,
    seed: int,
    confidence: float,
) -> tuple[float, float, float]:
    """The mean of ``losses`` less the mean of ``against``, with the interval it takes when
    whole seasons are drawn with replacement: the difference, its low and its high."""
    gap = np.asarray(losses, dtype="float64") - np.asarray(against, dtype="float64")
    _, members = season_members(seasons)
    draws = season_draws(len(members), resamples, seed)
    sampled = np.empty(len(draws))
    for number, draw in enumerate(draws):
        rows = np.concatenate([members[index] for index in draw])
        sampled[number] = gap[rows].mean()
    low, high = percentile_interval(sampled, confidence)
    return rounded(gap.mean()), rounded(low), rounded(high)


def rounded(value: float) -> float:
    return round(float(value), DECIMALS) + 0.0
