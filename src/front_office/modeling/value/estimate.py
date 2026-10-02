"""Fit the value model and gather the evidence for it.

**What is fitted.** A team's rating in a season is modelled as the sum of its players'
estimates, each counted for the share of the minutes the player actually played. The
estimates are built only from seasons *before* the one predicted, so the weights are
chosen for one thing: describing a player in a way that carries over to next season,
on whatever team. Offense and defense are fitted separately, each against the team's
rating relative to the league.

**How it is tested.** One season at a time, on weights fitted to the seasons before
it. Because next season's minutes are taken as given, the test is of the ratings, not
of anyone's ability to forecast playing time; and it is passed only by doing better
than simpler ways of making the same prediction, which are run through the same test.

**What is not claimed.** The weights are not the price of a steal or a rebound. They
are what thirty seasons of team results can tell apart, and for several of them that
is not much: every weight is reported with the interval that resampling seasons gives
it, and every group of features with what the test loses when the group is left out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.analytics.teams import team_season_metrics
from front_office.domain.seasons import Season
from front_office.domain.value_model import (
    DEFENSE,
    OFFENSE,
    SIDES,
    BacktestRow,
    Comparison,
    FittedOn,
    SameSeason,
    Score,
    SeasonScore,
    Term,
    Validation,
    ValueModel,
    ValueSpec,
)
from front_office.modeling.value.availability import NotEnoughHistory, fit_availability
from front_office.modeling.value.design import (
    AGE,
    LEVEL_KEYS,
    NEW_PLAYER,
    PRIOR_MINUTES,
    TERM_KEYS,
    is_complete,
    team_design,
)
from front_office.modeling.value.features import (
    COMPONENTS,
    FEATURE_KEYS,
    ON_COURT_NET,
    PIE,
    PLUS_MINUS,
    RIVAL_KEYS,
    features_of,
    season_features,
    start_years,
    stints,
)
from front_office.modeling.value.pooling import entering
from front_office.modeling.value.resampling import interval, rmse_differences, season_draws
from front_office.modeling.value.scoring import season_impact

Tables = Mapping[str, pd.DataFrame]

MIN_TRAINING_SEASONS = 3
"""Seasons of team results the first out-of-sample prediction must have behind it."""

WEIGHT_DECIMALS = 6
RATING_DECIMALS = 3

BASELINE_LABELS = {
    "league_average": "Every team is average",
    "last_season": "The team's net rating last season",
    "last_season_regressed": "Last season's net rating, pulled toward average",
    ON_COURT_NET: "Players' on-court net rating",
    PLUS_MINUS: "Players' plus-minus per 100 possessions",
    PIE: "Players' PIE, the league's own composite",
}
LEVEL_ABLATIONS = {
    AGE: "Age",
    PRIOR_MINUTES: "Minutes per game, for the unproven part",
}


class NotEnoughData(ValueError):
    """The tables cannot support fitting or testing the model."""


@dataclass(frozen=True, slots=True)
class Problem:
    """What the fit works from, derived once from the tables."""

    features: pd.DataFrame
    played: pd.DataFrame
    pooled: pd.DataFrame
    """What was known of every player entering every season, features and rivals alike."""
    rows: pd.MultiIndex
    """The team-seasons that can be predicted: finished, every player on record, and at
    least one earlier season of player statistics behind them."""
    start: np.ndarray
    actual: np.ndarray
    """Relative offensive and defensive rating of each row: two columns."""
    finished: tuple[int, ...]
    """Start years of the finished seasons that have player statistics."""
    net_ratings: pd.Series
    """Net rating of every finished team-season on record, by ``(season, team_id)``:
    more than ``rows``, because a season can be history without being predictable."""


def prepare(tables: Tables, spec: ValueSpec) -> Problem:
    team_seasons = tables["team_seasons"]
    played = stints(tables["player_seasons"], tables["player_game_logs"], team_seasons)
    features = season_features(tables["player_seasons"], team_seasons, played)
    if features.empty:
        raise NotEnoughData("there are no player statistics to fit the value model on")
    pooled = entering(features, spec, [*FEATURE_KEYS, *RIVAL_KEYS])

    metrics = team_season_metrics(team_seasons)
    finished = metrics[metrics["won_championship"].notna()].set_index(["season", "team_id"])
    design = team_design(played, pooled, spec)
    earliest = int(features["start"].min())
    usable = design[
        is_complete(design)
        & design.index.isin(finished.index)
        & (start_years(design.index.get_level_values("season").to_series()).to_numpy() > earliest)
    ]
    rows = usable.sort_index().index
    actual = finished.reindex(rows)[["rel_off_rating", "rel_def_rating"]].to_numpy(dtype="float64")
    start = start_years(rows.get_level_values("season").to_series()).to_numpy()
    seasons_finished = set(start_years(finished.index.get_level_values("season").to_series()))
    over = tuple(sorted(seasons_finished & set(features["start"])))
    net_ratings = finished["rel_off_rating"] + finished["rel_def_rating"]
    return Problem(features, played, pooled, rows, start, actual, over, net_ratings)


def fit_value_model(
    tables: Tables, spec: ValueSpec, *, revision: int, fitted_at: datetime
) -> ValueModel:
    """Fit the model on ``tables`` and test it; raise :class:`NotEnoughData` if it cannot be."""
    problem = prepare(tables, spec)
    first_test = Season.parse(spec.first_test_season).start_year
    training = sorted({int(year) for year in problem.start if year < first_test})
    if len(training) < MIN_TRAINING_SEASONS or not (problem.start >= first_test).any():
        raise NotEnoughData(
            f"the value model is tested from {spec.first_test_season} and needs at least "
            f"{MIN_TRAINING_SEASONS} finished seasons of complete player statistics before "
            f"that, each with a season before it; the tables hold {len(training)} "
            f"and {int((problem.start >= first_test).sum())} team-seasons to test on"
        )

    design = _design(problem, spec, FEATURE_KEYS, LEVEL_KEYS)
    fitted = _solve(design, problem.actual)
    tested, predicted = _expanding(design, problem.actual, problem.start, first_test)
    errors = (predicted - problem.actual)[tested]
    net_errors = errors.sum(axis=1)
    actual = problem.actual[tested]
    season_of = problem.start[tested]

    def compare(key: str, label: str, other: np.ndarray, *, baseline: bool) -> Comparison:
        """``other`` is another method's net-rating errors on the tested rows."""
        pair = (net_errors, other) if baseline else (other, net_errors)
        low, high = interval(rmse_differences(*pair, season_of, spec), spec)
        return Comparison(
            key=key,
            label=label,
            rmse=_round(_rmse(other)),
            mae=_round(np.abs(other).mean()),
            difference=_round(_rmse(pair[0]) - _rmse(pair[1])),
            low=_round(low),
            high=_round(high),
        )

    net_actual = actual.sum(axis=1)
    baselines = [
        compare(key, BASELINE_LABELS[key], prediction[tested] - net_actual, baseline=True)
        for key, prediction in _team_baselines(problem, first_test).items()
    ]
    for rival in RIVAL_KEYS:
        other = _net_errors(problem, spec, [rival], [NEW_PLAYER], first_test, tested)
        baselines.append(compare(rival, BASELINE_LABELS[rival], other, baseline=True))

    ablations = []
    for component in COMPONENTS:
        kept = [key for key in FEATURE_KEYS if key not in features_of(component.key)]
        other = _net_errors(problem, spec, kept, LEVEL_KEYS, first_test, tested)
        ablations.append(compare(component.key, component.label, other, baseline=False))
    for level, label in LEVEL_ABLATIONS.items():
        kept_levels = [key for key in LEVEL_KEYS if key != level]
        other = _net_errors(problem, spec, FEATURE_KEYS, kept_levels, first_test, tested)
        ablations.append(compare(level, label, other, baseline=False))

    weights = {
        side: dict(zip(TERM_KEYS, fitted[:, column].tolist(), strict=True))
        for column, side in enumerate(SIDES)
    }
    weights = {
        side: {key: _round(value) for key, value in by.items()} for side, by in weights.items()
    }
    impact = season_impact(problem.features, spec, weights)
    finished_starts = [int(year) for year in problem.finished]
    try:
        availability = fit_availability(problem.features, problem.played, finished_starts, spec)
    except NotEnoughHistory as error:
        raise NotEnoughData(str(error)) from error

    tested_rows = problem.rows[tested]
    return ValueModel(
        revision=revision,
        fitted_at=fitted_at,
        spec=spec,
        fitted_on=FittedOn(
            first_season=Season(min(finished_starts)).label,
            last_season=Season(int(problem.start.max())).label,
            team_seasons=len(problem.rows),
            player_seasons=int(
                (
                    problem.features["start"].isin(finished_starts)
                    & (problem.features["evidence_minutes"] > 0)
                ).sum()
            ),
        ),
        terms=_terms(design, problem, weights, spec),
        replacement_level=_round(_replacement_level(problem, impact, finished_starts, spec)),
        availability=availability,
        validation=Validation(
            first_test_season=Season(int(season_of.min())).label,
            last_test_season=Season(int(season_of.max())).label,
            team_seasons=int(tested.sum()),
            net=_score(net_errors, net_actual),
            offense=_score(errors[:, 0], actual[:, 0]),
            defense=_score(errors[:, 1], actual[:, 1]),
            baselines=tuple(baselines),
            ablations=tuple(ablations),
            by_season=tuple(
                SeasonScore(
                    season=Season(int(year)).label,
                    teams=int((season_of == year).sum()),
                    rmse=_round(_rmse(net_errors[season_of == year])),
                )
                for year in sorted(set(season_of.tolist()))
            ),
            same_season=_same_season(problem, impact),
        ),
        backtest=tuple(
            BacktestRow(
                season=season,
                team_id=int(team_id),
                predicted_offense=round(float(row[0]), RATING_DECIMALS),
                predicted_defense=round(float(row[1]), RATING_DECIMALS),
                actual_offense=round(float(truth[0]), RATING_DECIMALS),
                actual_defense=round(float(truth[1]), RATING_DECIMALS),
            )
            for (season, team_id), row, truth in zip(
                tested_rows, predicted[tested], actual, strict=True
            )
        ),
    )


# --- the regression ---------------------------------------------------------------------


def _design(
    problem: Problem, spec: ValueSpec, keys: Sequence[str], levels: Sequence[str]
) -> np.ndarray:
    design = team_design(problem.played, problem.pooled, spec, keys, levels)
    return design.loc[problem.rows, [*keys, *levels]].to_numpy(dtype="float64")


def _solve(design: np.ndarray, actual: np.ndarray) -> np.ndarray:
    """Least squares with no intercept: a team of average players is an average team."""
    return np.linalg.lstsq(design, actual, rcond=None)[0]


def _expanding(
    design: np.ndarray, actual: np.ndarray, start: np.ndarray, first_test: int
) -> tuple[np.ndarray, np.ndarray]:
    """Predict each season from ``first_test`` on with weights fitted to earlier ones.

    Returns which rows were predicted and the predictions, zero elsewhere.
    """
    tested = np.zeros(len(start), dtype=bool)
    predicted = np.zeros_like(actual)
    for year in sorted({int(value) for value in start if value >= first_test}):
        train, test = start < year, start == year
        predicted[test] = design[test] @ _solve(design[train], actual[train])
        tested |= test
    return tested, predicted


def _net_errors(
    problem: Problem,
    spec: ValueSpec,
    keys: Sequence[str],
    levels: Sequence[str],
    first_test: int,
    tested: np.ndarray,
) -> np.ndarray:
    """Net-rating errors of the model built from ``keys`` and ``levels`` alone."""
    design = _design(problem, spec, keys, levels)
    _, predicted = _expanding(design, problem.actual, problem.start, first_test)
    return (predicted - problem.actual)[tested].sum(axis=1)


def _team_baselines(problem: Problem, first_test: int) -> dict[str, np.ndarray]:
    """Predictions of net rating that need no players: one value per row."""
    net = problem.actual.sum(axis=1)
    teams = problem.rows.get_level_values("team_id")
    before = pd.MultiIndex.from_arrays(
        [[Season(int(year) - 1).label for year in problem.start], teams]
    )
    # A team with no season before it on record - an expansion team - is taken as average.
    last = problem.net_ratings.reindex(before).fillna(0.0).to_numpy()
    regressed = np.zeros(len(net))
    for year in sorted({int(value) for value in problem.start if value >= first_test}):
        train, test = problem.start < year, problem.start == year
        spread = (last[train] ** 2).sum()
        slope = (last[train] * net[train]).sum() / spread if spread > 0 else 0.0
        regressed[test] = slope * last[test]
    return {
        "league_average": np.zeros(len(net)),
        "last_season": last,
        "last_season_regressed": regressed,
    }


def _terms(
    design: np.ndarray,
    problem: Problem,
    weights: Mapping[str, Mapping[str, float]],
    spec: ValueSpec,
) -> tuple[Term, ...]:
    """Each weight with the interval that resampling seasons leaves it.

    A refit per draw would be thousands of regressions; the sums a regression needs add
    up season by season, so each season's are computed once and added per draw.
    """
    seasons, position = np.unique(problem.start, return_inverse=True)
    width = design.shape[1]
    gram = np.zeros((len(seasons), width, width))
    moment = np.zeros((len(seasons), width, 2))
    for index in range(len(seasons)):
        rows = position == index
        gram[index] = design[rows].T @ design[rows]
        moment[index] = design[rows].T @ problem.actual[rows]
    draws = season_draws(seasons, spec)
    solved = np.linalg.pinv(gram[draws].sum(axis=1)) @ moment[draws].sum(axis=1)

    terms = []
    for column, key in enumerate(TERM_KEYS):
        offense, defense = solved[:, column, 0], solved[:, column, 1]
        bounds = {
            OFFENSE: interval(offense, spec),
            DEFENSE: interval(defense, spec),
            "net": interval(offense + defense, spec),
        }
        terms.append(
            Term(
                key=key,
                offense=weights[OFFENSE][key],
                defense=weights[DEFENSE][key],
                **{
                    f"{side}_{end}": _round(value)
                    for side, pair in bounds.items()
                    for end, value in zip(("low", "high"), pair, strict=True)
                },
            )
        )
    return tuple(terms)


# --- what the ratings imply --------------------------------------------------------------


def _replacement_level(
    problem: Problem, impact: pd.DataFrame, finished: Sequence[int], spec: ValueSpec
) -> float:
    """Minutes-weighted impact of the players outside their team's most-used few."""
    played = problem.played[problem.played["start"].isin(list(finished))]
    rank = played.groupby(["season", "team_id"])["minutes"].rank(ascending=False, method="first")
    best = rank.groupby([played["season"], played["player_id"]]).min()
    features = problem.features
    place = best.reindex(pd.MultiIndex.from_frame(features[["season", "player_id"]])).to_numpy()
    spare = (place > spec.replacement_rank) & (features["minutes"].to_numpy() > 0)
    if not spare.any():
        raise NotEnoughData(
            f"no team has more than {spec.replacement_rank} players with minutes, so there "
            "is nobody to measure a replacement level on"
        )
    minutes = features.loc[spare, "minutes"].to_numpy()
    return float((impact.loc[spare, "impact"].to_numpy() * minutes).sum() / minutes.sum())


def _same_season(problem: Problem, impact: pd.DataFrame) -> SameSeason:
    """A team's impacts, added up by minutes, against its own net rating that season."""
    rated = problem.features[["season", "player_id"]].assign(impact=impact["impact"])
    joined = problem.played.merge(rated, on=["season", "player_id"])
    joined["points"] = joined["share"].fillna(0.0) * joined["impact"]
    summed = joined.groupby(["season", "team_id"])["points"].sum().reindex(problem.rows)
    net = problem.actual.sum(axis=1)
    total = summed.fillna(0.0).to_numpy()
    spread = (total**2).sum()
    return SameSeason(
        slope=_round((total * net).sum() / spread if spread > 0 else 0.0),
        correlation=_round(np.corrcoef(total, net)[0, 1] if spread > 0 else 0.0),
    )


def _score(errors: np.ndarray, actual: np.ndarray) -> Score:
    spread = ((actual - actual.mean()) ** 2).sum()
    return Score(
        rmse=_round(_rmse(errors)),
        mae=_round(np.abs(errors).mean()),
        r2=_round(1 - (errors**2).sum() / spread if spread > 0 else 0.0),
    )


def _rmse(errors: np.ndarray) -> float:
    return float(np.sqrt((errors**2).mean()))


def _round(value: float) -> float:
    return round(float(value), WEIGHT_DECIMALS)
