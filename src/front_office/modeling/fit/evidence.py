"""Does fit say anything the sum of the parts does not? The test.

The value model's test predicted every team-season from 2006-07 on from its players'
pooled earlier seasons and the season's actual minutes, and recorded what each
prediction missed. Fit would show in those misses, if it shows anywhere. This module
takes each fit measure - computed from the players' *previous-season* profiles, weighted
by the minutes they then played, so that nothing of the season predicted leaks in - and
asks whether it explains the misses on seasons it had not seen; then asks all of the
measures together, and what each area contributes to that.

Every correction is fitted by least squares with an intercept on standardised measures,
one season at a time with only earlier seasons to learn from, as the value model is.
Intervals come from resampling whole seasons.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.domain.archetypes import ArchetypeSet
from front_office.domain.fit import MEASURE_KEYS, Area, measure
from front_office.domain.fit_model import (
    AreaEvidence,
    CombinedEvidence,
    FitEvidence,
    FitSpec,
    Interval,
    MeasureEvidence,
    Term,
)
from front_office.domain.seasons import Season
from front_office.domain.value_model import ValueModel
from front_office.modeling.fit.profile import team_profiles
from front_office.modeling.value.features import start_years
from front_office.modeling.value.resampling import interval, rmse_differences, season_draws

Tables = Mapping[str, pd.DataFrame]

LAG = 1
"""Profiles come from the season before the one predicted: what was known going in."""
NOT_TESTED: tuple[str, ...] = (
    "offense_sum",
    "defense_sum",
    "impact_sum",
    "projected_sum",
    "minutes_covered",
)
"""The sums of parts are what the fit is measured beyond, not candidates for it."""
TESTED: tuple[str, ...] = tuple(key for key in MEASURE_KEYS if key not in NOT_TESTED)
DECIMALS = 4


class NotEnoughEvidence(ValueError):
    """The tables or the model cannot support the test; the message says why."""


@dataclass(frozen=True, slots=True)
class Problem:
    """Every team-season the value model's test predicted, with its miss and the fit
    measures as they stood going into the season."""

    rows: pd.DataFrame
    """``season``, ``team_id``, ``start``, ``predicted``, ``actual`` and :data:`TESTED`."""
    start: np.ndarray
    residual: np.ndarray
    """Actual less predicted: what the sum of the parts missed by."""
    features: np.ndarray
    """The tested measures, raw, one column each, missing where unknown."""


def prepare(tables: Tables, model: ValueModel, archetypes: ArchetypeSet) -> Problem:
    backtest = pd.DataFrame([row.model_dump() for row in model.backtest])
    if backtest.empty:
        raise NotEnoughEvidence(
            "the value model on file has no test on record, so there is nothing to measure "
            "fit beyond; fit the value model again"
        )
    backtest["predicted"] = backtest["predicted_offense"] + backtest["predicted_defense"]
    backtest["actual"] = backtest["actual_offense"] + backtest["actual_defense"]
    lagged = team_profiles(tables, archetypes, lag=LAG)
    rows = backtest[["season", "team_id", "predicted", "actual"]].merge(
        lagged[["season", "team_id", *TESTED]], on=["season", "team_id"], how="inner"
    )
    if rows.empty:
        raise NotEnoughEvidence(
            "no team-season of the value model's test has player profiles from the season before it"
        )
    rows["start"] = start_years(rows["season"])
    rows = rows.sort_values(["start", "team_id"], ignore_index=True)
    return Problem(
        rows,
        rows["start"].to_numpy(),
        (rows["actual"] - rows["predicted"]).to_numpy(dtype="float64"),
        rows[list(TESTED)].to_numpy(dtype="float64"),
    )


def fit_evidence(
    tables: Tables,
    model: ValueModel,
    archetypes: ArchetypeSet,
    spec: FitSpec,
    *,
    revision: int,
    fitted_at: datetime,
) -> FitEvidence:
    """Gather the evidence on ``tables``; raise :class:`NotEnoughEvidence` if it cannot be."""
    problem = prepare(tables, model, archetypes)
    first_test = Season.parse(spec.first_test_season).start_year
    tested, _ = _expanding(
        problem.features[:, :0], problem.residual, problem.start, first_test, spec
    )
    if not tested.any():
        raise NotEnoughEvidence(
            f"fit is tested from {spec.first_test_season} and needs at least "
            f"{spec.min_training_seasons} seasons of the value model's test before that; "
            f"the test on file runs from {problem.rows['season'].iloc[0]} to "
            f"{problem.rows['season'].iloc[-1]}"
        )
    residual = problem.residual[tested]
    season_of = problem.start[tested]
    columns = {key: position for position, key in enumerate(TESTED)}

    def corrected(keys: Sequence[str]) -> np.ndarray:
        """Errors on the tested rows after the correction fitted from ``keys`` alone."""
        chosen = [columns[key] for key in keys]
        _, adjustment = _expanding(
            problem.features[:, chosen], problem.residual, problem.start, first_test, spec
        )
        return residual - adjustment[tested]

    def change(errors: np.ndarray, against: np.ndarray) -> Interval:
        low, high = interval(rmse_differences(errors, against, season_of, spec), spec)
        return Interval(
            difference=_round(_rmse(errors) - _rmse(against)), low=_round(low), high=_round(high)
        )

    measures = []
    for key in TESTED:
        column = problem.features[:, columns[key]]
        errors = corrected([key])
        coefficient, low, high = _coefficient(
            column[:, None], problem.residual, problem.start, spec
        )
        item = measure(key)
        measures.append(
            MeasureEvidence(
                key=key,
                name=item.name,
                area=str(item.area),
                teams=int(np.isfinite(column[tested]).sum()),
                coefficient=_round(coefficient[0]),
                coefficient_low=_round(low[0]),
                coefficient_high=_round(high[0]),
                rmse=_round(_rmse(errors)),
                change=change(errors, residual),
            )
        )

    combined_errors = corrected(TESTED)
    coefficients, lows, highs = _coefficient(
        problem.features, problem.residual, problem.start, spec
    )
    means, scales = _moments(problem.features)
    standardised = _standardise(problem.features, means, scales)
    intercept = float(np.nanmean(problem.residual) - standardised.mean(axis=0) @ coefficients)
    ablations = []
    for area in Area:
        keys = [key for key in TESTED if measure(key).area is area]
        if not keys:
            continue
        errors = corrected([key for key in TESTED if key not in keys])
        ablations.append(
            AreaEvidence(
                key=area.name.lower(),
                label=str(area),
                rmse=_round(_rmse(errors)),
                change=change(errors, combined_errors),
            )
        )
    combined = CombinedEvidence(
        rmse=_round(_rmse(combined_errors)),
        change=change(combined_errors, residual),
        intercept=_round(intercept),
        terms=tuple(
            Term(
                key=key,
                coefficient=_round(coefficients[position]),
                low=_round(lows[position]),
                high=_round(highs[position]),
                mean=_round(means[position]),
                scale=_round(scales[position]),
            )
            for key, position in columns.items()
        ),
        ablations=tuple(ablations),
    )
    seasons = problem.rows.loc[tested, "season"]
    return FitEvidence(
        revision=revision,
        fitted_at=fitted_at,
        spec=spec,
        value_model_version=model.version,
        archetype_version=archetypes.label,
        first_test_season=str(seasons.iloc[0]),
        last_test_season=str(seasons.iloc[-1]),
        team_seasons=int(tested.sum()),
        baseline_rmse=_round(_rmse(residual)),
        tested=TESTED,
        measures=tuple(measures),
        combined=combined,
    )


def adjustment(evidence: FitEvidence, profile: Mapping[str, float]) -> float | None:
    """The correction the evidence supports for a roster with this profile, in points of
    net rating; ``None`` when the evidence supports none. A measure the profile lacks is
    taken at its average, which adds nothing."""
    combined = evidence.combined
    if not combined.is_usable:
        return None
    total = combined.intercept
    for term in combined.terms:
        value = profile.get(term.key, np.nan)
        if value is None or not np.isfinite(value) or term.scale == 0:
            continue
        total += term.coefficient * (float(value) - term.mean) / term.scale
    return float(total)


# --- the arithmetic ---------------------------------------------------------------------


def _moments(features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Column means and standard deviations, missing values ignored; a column with
    nothing to measure, or no spread, scales by one."""
    if features.shape[1] == 0:
        return np.zeros(0), np.ones(0)
    with np.errstate(invalid="ignore"):
        means = np.nanmean(features, axis=0)
        scales = np.nanstd(features, axis=0)
    means = np.where(np.isfinite(means), means, 0.0)
    scales = np.where(np.isfinite(scales) & (scales > 0), scales, 1.0)
    return means, scales


def _standardise(features: np.ndarray, means: np.ndarray, scales: np.ndarray) -> np.ndarray:
    """Standardised columns, a missing value standing at the mean."""
    with np.errstate(invalid="ignore"):
        standardised = (features - means) / scales
    return np.where(np.isfinite(standardised), standardised, 0.0)


def _solve(standardised: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Least squares with an intercept: the intercept first, then one weight a column."""
    design = np.column_stack([np.ones(len(target)), standardised])
    return np.linalg.lstsq(design, target, rcond=None)[0]


def _expanding(
    features: np.ndarray, residual: np.ndarray, start: np.ndarray, first_test: int, spec: FitSpec
) -> tuple[np.ndarray, np.ndarray]:
    """Correct each season from ``first_test`` on with weights fitted to earlier seasons.

    Standardisation is learned from the training seasons too. Returns which rows were
    corrected and the correction, zero elsewhere.
    """
    tested = np.zeros(len(start), dtype=bool)
    adjustment = np.zeros(len(start))
    for year in sorted({int(value) for value in start if value >= first_test}):
        train, test = start < year, start == year
        if len(set(start[train])) < spec.min_training_seasons:
            continue
        means, scales = _moments(features[train])
        weights = _solve(_standardise(features[train], means, scales), residual[train])
        design = np.column_stack(
            [np.ones(int(test.sum())), _standardise(features[test], means, scales)]
        )
        adjustment[test] = design @ weights
        tested |= test
    return tested, adjustment


def _coefficient(
    features: np.ndarray, residual: np.ndarray, start: np.ndarray, spec: FitSpec
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weights per standard deviation fitted on every season, with intervals from
    resampling seasons: the coefficients, their lows and their highs."""
    means, scales = _moments(features)
    standardised = _standardise(features, means, scales)
    fitted = _solve(standardised, residual)[1:]
    seasons, position = np.unique(start, return_inverse=True)
    members = [np.flatnonzero(position == index) for index in range(len(seasons))]
    draws = season_draws(seasons, spec)
    sampled = np.empty((len(draws), features.shape[1]))
    for number, draw in enumerate(draws):
        rows = np.concatenate([members[index] for index in draw])
        sampled[number] = _solve(standardised[rows], residual[rows])[1:]
    tail = 100 * (1 - spec.confidence) / 2
    low, high = np.percentile(sampled, [tail, 100 - tail], axis=0)
    return fitted, low, high


def _rmse(errors: np.ndarray) -> float:
    return float(np.sqrt(np.mean(errors**2)))


def _round(value: float) -> float:
    return round(float(value), DECIMALS) + 0.0
