"""Measuring the simulator's parameters, and testing the wins it draws.

The test: for every team-season the value model predicted out of sample, seasons are
drawn from the predicted rating with the value model's miss, a season's noise and the
residual wins carry, and the wins that happened are set against the interval the
seasons give. An interval that holds the wins that happened as often as it claims is
one a reader can lean on.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.domain.eras import Era
from front_office.domain.simulator import (
    Coverage,
    FittedOn,
    SimulatorModel,
    SimulatorSpec,
    WinsTest,
)
from front_office.domain.value_model import ValueModel
from front_office.modeling.simulator.measure import (
    EVEN_RECORD,
    FULL_SEASON_GAMES,
    REGULAR,
    development_bands,
    era_noise,
    missed_games,
    recent,
    rounded,
    season_noise,
    wins_residual,
)
from front_office.modeling.value.wins import wins_per_net_point

FEATURE_TABLES: tuple[str, ...] = (
    "team_seasons",
    "team_games",
    "player_seasons",
    "player_value_scores",
)
Tables = dict[str, pd.DataFrame]


class NotEnoughHistory(ValueError):
    """The tables cannot support the measurements or the test."""


def fit_simulator_model(
    tables: Tables,
    spec: SimulatorSpec,
    eras: Sequence[Era],
    value_model: ValueModel,
    *,
    revision: int,
    fitted_at: datetime,
    postseason_model_version: str | None,
) -> SimulatorModel:
    """Measure every parameter and run the wins test; raise :class:`NotEnoughHistory` if
    the tables cannot support them."""
    teams = tables["team_seasons"]
    noise = season_noise(tables["team_games"], teams)
    if noise.empty:
        raise NotEnoughHistory("no regular-season games with results are on record")
    seasons = recent(noise["season"].tolist(), spec.noise_seasons)
    slopes = wins_per_net_point(teams, window=value_model.spec.wins_window)
    if slopes.empty:
        raise NotEnoughHistory("no season with games played to fit wins per point on")
    residual, residual_cases = wins_residual(teams, slopes, seasons)
    bands = development_bands(tables["player_value_scores"], spec.reliability_edges)
    if sum(band.players for band in bands) == 0:
        raise NotEnoughHistory(
            "no player-season has both a projection and what the season showed; the value "
            "model has to be applied by a build first"
        )
    missed = missed_games(
        tables["player_seasons"],
        teams,
        rotation_minutes=spec.rotation_minutes,
        quantiles=spec.missed_quantiles,
    )
    recent_noise = float(noise.loc[noise["season"].isin(seasons), "noise"].mean())
    value_error = float(value_model.validation.net.rmse)
    strength_error = float(np.sqrt(max(value_error**2 - recent_noise**2, 0.0)))
    test = wins_test(
        value_model,
        teams,
        slopes,
        value_error=value_error,
        wins_residual=residual,
        spec=spec,
    )
    played = teams[teams["games_played"] > 0]
    regular = tables["team_games"][tables["team_games"]["season_type"] == REGULAR]
    lines = tables["player_seasons"][tables["player_seasons"]["season_type"] == REGULAR]
    return SimulatorModel(
        revision=revision,
        fitted_at=fitted_at,
        spec=spec,
        value_model_version=value_model.version,
        postseason_model_version=postseason_model_version,
        fitted_on=FittedOn(
            first_season=str(played["season"].min()),
            last_season=str(played["season"].max()),
            team_seasons=int(len(played)),
            games=int(regular["won"].notna().sum() // 2),
            player_seasons=int(len(lines)),
        ),
        value_error=rounded(value_error),
        season_noise=rounded(recent_noise),
        strength_error=rounded(strength_error),
        noise_by_era=era_noise(noise, eras),
        wins_season=str(slopes.index[-1]),
        wins_per_point=rounded(slopes.iloc[-1]),
        wins_residual=residual if residual_cases >= 2 else 0.0,
        development=bands,
        missed=missed,
        test=test,
    )


def wins_test(
    value_model: ValueModel,
    team_seasons: pd.DataFrame,
    slopes: pd.Series,
    *,
    value_error: float,
    wins_residual: float,
    spec: SimulatorSpec,
) -> WinsTest:
    """Seasons drawn for every team-season of the value model's test, scored against the
    wins that happened."""
    rows = value_model.backtest
    if not rows:
        raise NotEnoughHistory("the value model on file carries no out-of-sample test")
    actual = team_seasons.set_index(["season", "team_id"])
    decided = (actual["wins"] + actual["losses"]).astype("float64")
    per_82 = FULL_SEASON_GAMES * actual["wins"].astype("float64") / decided.where(decided > 0)
    generator = np.random.default_rng(spec.seed)
    predicted, happened, intervals = [], [], {level: [] for level in spec.coverage_levels}
    for row in rows:
        key = (row.season, row.team_id)
        if key not in per_82.index or row.season not in slopes.index:
            continue
        wins = float(per_82.loc[key])
        if not np.isfinite(wins):
            continue
        rating = row.predicted + generator.normal(size=spec.test_simulations) * value_error
        drawn = EVEN_RECORD + float(slopes[row.season]) * rating
        drawn = drawn + generator.normal(size=spec.test_simulations) * wins_residual
        drawn = np.clip(drawn, 0.0, FULL_SEASON_GAMES)
        predicted.append(float(np.median(drawn)))
        happened.append(wins)
        for level in spec.coverage_levels:
            tail = 100 * (1 - level) / 2
            low, high = np.percentile(drawn, [tail, 100 - tail])
            intervals[level].append(bool(low <= wins <= high))
    if not predicted:
        raise NotEnoughHistory("no team-season of the value model's test has wins on record")
    errors = np.array(predicted) - np.array(happened)
    seasons = sorted({row.season for row in rows})
    return WinsTest(
        team_seasons=len(predicted),
        first_test_season=seasons[0],
        last_test_season=seasons[-1],
        mae=rounded(np.abs(errors).mean()),
        rmse=rounded(np.sqrt((errors**2).mean())),
        baseline_rmse=rounded(np.sqrt(((EVEN_RECORD - np.array(happened)) ** 2).mean())),
        coverage=tuple(
            Coverage(level=float(level), cases=len(flags), covered=int(sum(flags)))
            for level, flags in intervals.items()
        ),
    )
