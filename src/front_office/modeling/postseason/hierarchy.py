"""The season model: a team's chance of each stage before the bracket is known.

The roadmap's hierarchy. Each step is the chance of reaching the next stage for a team
that reached this one - every team for making the playoffs, playoff teams for winning a
round, and so on to the title - as a logistic in regular-season net rating and
top-player quality. The chance of a stage is the steps up to it multiplied together, so
the stages nest as they must, and the thirty champions on record never have to carry a
model of their own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from front_office.domain.postseason import PostseasonSpec, Step, StepDraw
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.modeling.postseason.fitting import (
    fit_logistic,
    logistic,
    percentile_interval,
    rounded,
    season_draws,
    season_members,
)

STEP_COLUMNS: tuple[str, ...] = ("net_rating", "top_players")
STEP_RIDGE = 1e-4
"""Making the playoffs is nearly decided by net rating, so the first step sits close to
perfect separation; this much shrinkage keeps its weights finite without moving them."""
QUADRATURE_NODES = 24


def step_design(frame: pd.DataFrame, columns: Sequence[str] = STEP_COLUMNS) -> np.ndarray:
    return np.column_stack(
        [np.ones(len(frame)), *[frame[c].to_numpy(dtype="float64") for c in columns]]
    )


def fit_step_weights(
    frame: pd.DataFrame, columns: Sequence[str], *, direct: bool = False
) -> list[np.ndarray]:
    """One weight vector per stage. Conditional steps by default: each fitted on the
    teams that reached the stage before. ``direct`` fits every stage on every team
    instead - the single-classifier alternative the hierarchy is compared with."""
    weights = []
    for position, key in enumerate(BRACKET_STAGE_KEYS):
        rows = frame if direct or position == 0 else frame[frame[BRACKET_STAGE_KEYS[position - 1]]]
        design = step_design(rows, columns)
        weights.append(fit_logistic(design, rows[key].to_numpy(dtype="float64"), ridge=STEP_RIDGE))
    return weights


def apply_steps(
    weights: Sequence[np.ndarray],
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    direct: bool = False,
) -> np.ndarray:
    """Each row's chance of every stage: shape (rows, stages). Conditional steps are
    multiplied up; direct fits are taken as they are."""
    design = step_design(frame, columns)
    out = np.empty((len(frame), len(weights)))
    running = np.ones(len(frame))
    for position, beta in enumerate(weights):
        conditional = logistic(design @ beta)
        running = conditional if direct else running * conditional
        out[:, position] = running
    return out


def fit_steps(features: pd.DataFrame, spec: PostseasonSpec) -> tuple[Step, ...]:
    """The season model on every decided team-season with its inputs known, with
    intervals and kept draws from resampling seasons."""
    rows = features[features["decided"]].dropna(subset=list(STEP_COLUMNS)).reset_index(drop=True)
    if rows.empty:
        raise ValueError("no decided team-seasons with net rating and top-player quality")
    fitted = fit_step_weights(rows, STEP_COLUMNS)
    _, members = season_members(rows["start_year"].to_numpy())
    draws = season_draws(len(members), spec.resamples, spec.seed + 1)
    sampled = np.empty((len(draws), len(BRACKET_STAGE_KEYS), 1 + len(STEP_COLUMNS)))
    for number, draw in enumerate(draws):
        picked = rows.iloc[np.concatenate([members[index] for index in draw])]
        sampled[number] = np.vstack(fit_step_weights(picked, STEP_COLUMNS))
    kept = np.linspace(0, len(draws) - 1, spec.kept_draws).round().astype(int)
    steps = []
    for position, key in enumerate(BRACKET_STAGE_KEYS):
        reached_from = rows if position == 0 else rows[rows[BRACKET_STAGE_KEYS[position - 1]]]
        net_low, net_high = percentile_interval(sampled[:, position, 1], spec.confidence)
        top_low, top_high = percentile_interval(sampled[:, position, 2], spec.confidence)
        steps.append(
            Step(
                key=key,
                from_key=None if position == 0 else BRACKET_STAGE_KEYS[position - 1],
                intercept=rounded(fitted[position][0]),
                net_rating=rounded(fitted[position][1]),
                net_low=rounded(net_low),
                net_high=rounded(net_high),
                top_players=rounded(fitted[position][2]),
                top_low=rounded(top_low),
                top_high=rounded(top_high),
                teams=int(len(reached_from)),
                reached=int(reached_from[key].sum()),
                draws=tuple(
                    StepDraw(
                        intercept=rounded(sampled[index, position, 0]),
                        net_rating=rounded(sampled[index, position, 1]),
                        top_players=rounded(sampled[index, position, 2]),
                    )
                    for index in kept
                ),
            )
        )
    return tuple(steps)


def step_weights(steps: Sequence[Step], *, draws: bool = False) -> np.ndarray:
    """The steps' weights as an array of shape (stages, 3) - or, with ``draws``, of
    shape (kept draws, stages, 3)."""
    if not draws:
        return np.array([[s.intercept, s.net_rating, s.top_players] for s in steps])
    count = len(steps[0].draws)
    return np.array(
        [
            [
                [s.draws[number].intercept, s.draws[number].net_rating, s.draws[number].top_players]
                for s in steps
            ]
            for number in range(count)
        ]
    )


def stage_probabilities(
    steps: Sequence[Step],
    net_rating: float,
    top_players: float,
    *,
    draws: bool = False,
    error: float | None = None,
) -> Mapping[str, np.ndarray | float]:
    """A team's chance of each stage. With ``draws`` every value is an array over the
    kept parameter draws. With ``error``, the net rating is a projection with that
    standard error, and the chance is averaged over where the true rating may lie
    (Gauss-Hermite quadrature); top-player quality is taken as given."""
    weights = step_weights(steps, draws=draws)  # (stages, 3) or (draws, stages, 3)
    if error is None or error <= 0:
        ratings, quadrature = np.array([net_rating]), np.array([1.0])
    else:
        nodes, node_weights = np.polynomial.hermite.hermgauss(QUADRATURE_NODES)
        ratings = net_rating + np.sqrt(2.0) * error * nodes
        quadrature = node_weights / np.sqrt(np.pi)
    design = np.column_stack([np.ones(len(ratings)), ratings, np.full(len(ratings), top_players)])
    logits = np.einsum(
        "...sk,rk->...sr", weights, design
    )  # (stages, ratings) or (draws, stages, ratings)
    conditional = logistic(logits)
    cumulative = np.cumprod(conditional, axis=-2)
    averaged = np.tensordot(
        cumulative, quadrature, axes=([-1], [0])
    )  # (stages,) or (draws, stages)
    return {
        key: (averaged[..., position] if draws else float(averaged[position]))
        for position, key in enumerate(BRACKET_STAGE_KEYS)
    }
