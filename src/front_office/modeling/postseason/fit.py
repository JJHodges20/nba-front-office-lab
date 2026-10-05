"""Fitting the postseason model, and testing it on seasons it had not seen.

Every test here is an expanding window: a season is scored with parameters fitted to the
seasons before it alone, from the first test season on. The series model is scored on
series, then carried through each season's actual bracket and scored on where every
playoff team got to; the season model is scored on every team-season. Each is set
beside simpler methods and beside the alternatives that were tried, with intervals from
resampling seasons, so that what was kept and what was left out is on the record.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.domain.eras import Era
from front_office.domain.postseason import (
    Baseline,
    BeforeSeasonEvaluation,
    BracketEvaluation,
    Comparison,
    Draw,
    EraParameters,
    Evaluation,
    FittedOn,
    GameModel,
    PostseasonModel,
    PostseasonSpec,
    RoundEvaluation,
    SeasonEvaluation,
    SeasonFavourite,
    SeriesEvaluation,
    SpanEvaluation,
    StageEvaluation,
    TypicalTop,
)
from front_office.domain.seasons import Season
from front_office.domain.stages import BRACKET_STAGE_KEYS, ROUND_STAGE_KEYS
from front_office.domain.value_model import BacktestRow
from front_office.modeling.postseason.bracket import (
    BracketError,
    bracket_from_series,
    propagate,
)
from front_office.modeling.postseason.features import (
    Tables,
    head_to_head,
    keyed,
    playoff_games,
    series_table,
    team_features,
)
from front_office.modeling.postseason.fitting import (
    brier,
    calibration,
    difference_interval,
    log_loss,
    percentile_interval,
    reliability,
    rounded,
    row_losses,
    season_draws,
    season_members,
)
from front_office.modeling.postseason.hierarchy import (
    QUADRATURE_NODES,
    STEP_COLUMNS,
    apply_steps,
    fit_step_weights,
    fit_steps,
)
from front_office.modeling.postseason.series import GAME_COLUMNS, fit_game_model, predict_series

SERIES_ALTERNATIVES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("net_rating_alone", "Net rating alone", ("home", "net_rating_diff")),
    (
        "best_player",
        "The best player instead of the top three",
        ("home", "net_rating_diff", "best_player_diff"),
    ),
    (
        "with_experience",
        "With playoff experience added",
        ("home", "net_rating_diff", "top_players_diff", "experience_diff"),
    ),
    (
        "win_pct",
        "Winning percentage instead of net rating",
        ("home", "win_pct_diff", "top_players_diff"),
    ),
)
"""What the series model was compared with, each tested the same way."""
SEASON_ALTERNATIVES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("net_rating_alone", "Net rating alone", ("net_rating",), False),
    ("direct", "One classifier per stage, fitted on every team", STEP_COLUMNS, True),
    ("with_experience", "With playoff experience added", (*STEP_COLUMNS, "experience"), False),
    ("win_pct", "Winning percentage instead of net rating", ("win_pct", "top_players"), False),
    (
        "conference_relative",
        "With the gap to the conference's eighth-best net rating added",
        (*STEP_COLUMNS, "conference_gap"),
        False,
    ),
)
"""What the season model was compared with. The last column says whether the stages are
fitted directly rather than as conditional steps."""
PLAYOFF_PLACES = 8
UNIFORM: dict[str, float] = {
    key: 1 / 2 ** (position + 1) for position, key in enumerate(ROUND_STAGE_KEYS)
}
"""Each stage's share of a sixteen-team bracket: what a coin flip at every series gives."""


class NotEnoughHistory(ValueError):
    """The tables cannot support the test the specification asks for."""


def fit_postseason_model(
    tables: Tables,
    spec: PostseasonSpec,
    eras: Sequence[Era],
    *,
    revision: int,
    fitted_at: datetime,
    value_model_version: str,
    value_backtest: Sequence[BacktestRow] = (),
    value_error: float | None = None,
    rating_basis: str = "projected",
) -> PostseasonModel:
    """Fit the series model and the season model on every season on record and test both
    out of sample; raise :class:`NotEnoughHistory` if the test cannot be run.

    ``value_backtest`` and ``value_error`` are the value model's out-of-sample team
    predictions and their error: with them the season model is also scored as a
    forecast reads it, from the rating predicted before each season.
    """
    features = team_features(tables, spec)
    decided = features[features["decided"]].reset_index(drop=True)
    games = playoff_games(tables, features, spec).dropna(subset=list(GAME_COLUMNS))
    series = series_table(tables, features, spec)
    pairings = head_to_head(tables["team_games"])
    if games.empty or series.empty or decided.empty:
        raise NotEnoughHistory("no decided playoff games and series with the inputs known")
    first_test = Season.parse(spec.first_test_season).start_year
    on_record = sorted(series["start_year"].unique())
    test_years = [
        int(year)
        for year in on_record
        if year >= first_test
        and sum(1 for other in on_record if other < year) >= spec.min_training_seasons
    ]
    if not test_years:
        raise NotEnoughHistory(
            f"the model is tested from {spec.first_test_season} and needs "
            f"{spec.min_training_seasons} seasons of playoffs before that; the series on "
            f"record run from {series['season'].iloc[0]} to {series['season'].iloc[-1]}"
        )
    series_evaluation = _series_evaluation(games, series, test_years, eras, spec)
    bracket_evaluation = _bracket_evaluation(games, series, features, pairings, test_years, spec)
    season_evaluation = _season_evaluation(decided, test_years, spec)
    before_season = _before_season_evaluation(
        decided, test_years, value_backtest, value_error, rating_basis
    )
    game = _game_model(games, spec)
    by_era = _by_era(games, eras)
    steps = fit_steps(features, spec)
    with_inputs = decided.dropna(subset=list(STEP_COLUMNS))
    slope, intercept = np.polyfit(
        with_inputs["net_rating"].to_numpy(dtype="float64"),
        with_inputs["top_players"].to_numpy(dtype="float64"),
        1,
    )
    return PostseasonModel(
        revision=revision,
        fitted_at=fitted_at,
        spec=spec,
        value_model_version=value_model_version,
        fitted_on=FittedOn(
            first_season=str(decided["season"].iloc[0]),
            last_season=str(decided["season"].iloc[-1]),
            seasons=int(decided["season"].nunique()),
            playoff_games=int(len(games)),
            series=int(len(series)),
            team_seasons=int(len(decided)),
        ),
        game=game,
        by_era=by_era,
        steps=steps,
        typical_top=TypicalTop(slope=rounded(slope), intercept=rounded(intercept)),
        evaluation=Evaluation(
            series=series_evaluation,
            bracket=bracket_evaluation,
            season=season_evaluation,
            before_season=before_season,
        ),
    )


# --- the series model ----------------------------------------------------------------------


def _expanding_series(
    games: pd.DataFrame, series: pd.DataFrame, columns: Sequence[str], test_years: Sequence[int]
) -> np.ndarray:
    """Each series' probability for its home-court side from a game model fitted to earlier
    seasons; missing where the series was not tested."""
    out = np.full(len(series), np.nan)
    gaps = list(columns[1:])
    for year in test_years:
        train = games[games["start_year"] < year].dropna(subset=list(columns))
        rows = series[series["start_year"] == year].dropna(subset=gaps)
        if train.empty or rows.empty:
            continue
        weights = fit_game_model(train, columns)
        out[rows.index.to_numpy()] = predict_series(weights, rows, columns)
    return out


def _series_evaluation(
    games: pd.DataFrame,
    series: pd.DataFrame,
    test_years: Sequence[int],
    eras: Sequence[Era],
    spec: PostseasonSpec,
) -> SeriesEvaluation:
    probability = _expanding_series(games, series, GAME_COLUMNS, test_years)
    tested = ~np.isnan(probability)
    if not tested.any():
        raise NotEnoughHistory("no series could be scored out of sample")
    p = probability[tested]
    rows = series[tested]
    y = rows["a_won"].to_numpy(dtype="float64")
    years = rows["start_year"].to_numpy()
    constant = np.array([series.loc[series["start_year"] < year, "a_won"].mean() for year in years])
    baselines = (
        Baseline(
            key="home_court_rate",
            label="The home-court side's past win rate, for every series",
            log_loss=rounded(log_loss(constant, y)),
            brier=rounded(brier(constant, y)),
        ),
        Baseline(
            key="coin_flip",
            label="A coin flip",
            log_loss=rounded(log_loss(np.full(len(y), 0.5), y)),
            brier=rounded(brier(np.full(len(y), 0.5), y)),
        ),
    )
    comparisons = []
    for key, label, columns in SERIES_ALTERNATIVES:
        other = _expanding_series(games, series, columns, test_years)
        both = tested & ~np.isnan(other)
        if not both.any():
            continue
        comparisons.append(
            _comparison(
                key,
                label,
                other[both],
                probability[both],
                series.loc[both, "a_won"].to_numpy(),
                series.loc[both, "start_year"].to_numpy(),
                spec,
            )
        )
    favoured_won = int(((p >= 0.5) == (y == 1)).sum())
    by_round = []
    for playoff_round in sorted(rows["round"].unique()):
        inside = (rows["round"] == playoff_round).to_numpy()
        by_round.append(
            RoundEvaluation(
                round=int(playoff_round),
                series=int(inside.sum()),
                home_side_won=int(y[inside].sum()),
                favourite_won=int(((p[inside] >= 0.5) == (y[inside] == 1)).sum()),
                mean_probability=rounded(p[inside].mean()),
                log_loss=rounded(log_loss(p[inside], y[inside])),
                brier=rounded(brier(p[inside], y[inside])),
            )
        )
    by_era = []
    labels = rows["season"].to_numpy()
    for era in eras:
        covered = set(era.seasons(sorted(set(labels))))
        inside = np.isin(labels, list(covered))
        if not inside.any():
            continue
        by_era.append(
            SpanEvaluation(
                key=era.key,
                label=era.name,
                first_season=min(covered),
                last_season=max(covered),
                series=int(inside.sum()),
                log_loss=rounded(log_loss(p[inside], y[inside])),
                brier=rounded(brier(p[inside], y[inside])),
                calibration=calibration(p[inside], y[inside]),
            )
        )
    return SeriesEvaluation(
        first_test_season=str(rows["season"].iloc[0]),
        last_test_season=str(rows["season"].iloc[-1]),
        series=int(len(rows)),
        home_side_won=int(y.sum()),
        favourite_won=favoured_won,
        log_loss=rounded(log_loss(p, y)),
        brier=rounded(brier(p, y)),
        calibration=calibration(p, y),
        baselines=baselines,
        comparisons=tuple(comparisons),
        reliability=reliability(p, y, spec.reliability_edges, confidence=spec.confidence),
        by_round=tuple(by_round),
        by_era=tuple(by_era),
    )


def _comparison(
    key: str,
    label: str,
    other: np.ndarray,
    model: np.ndarray,
    outcome: np.ndarray,
    seasons: np.ndarray,
    spec: PostseasonSpec,
) -> Comparison:
    difference, low, high = difference_interval(
        row_losses(other, outcome),
        row_losses(model, outcome),
        seasons,
        resamples=spec.resamples,
        seed=spec.seed + 2,
        confidence=spec.confidence,
    )
    return Comparison(
        key=key,
        label=label,
        log_loss=rounded(log_loss(other, outcome)),
        brier=rounded(brier(other, outcome)),
        difference=difference,
        low=low,
        high=high,
    )


def _game_model(games: pd.DataFrame, spec: PostseasonSpec) -> GameModel:
    fitted = fit_game_model(games, GAME_COLUMNS)
    _, members = season_members(games["start_year"].to_numpy())
    draws = season_draws(len(members), spec.resamples, spec.seed)
    sampled = np.empty((len(draws), len(GAME_COLUMNS)))
    for number, draw in enumerate(draws):
        rows = np.concatenate([members[index] for index in draw])
        sampled[number] = fit_game_model(games.iloc[rows], GAME_COLUMNS)
    home_low, home_high = percentile_interval(sampled[:, 0], spec.confidence)
    net_low, net_high = percentile_interval(sampled[:, 1], spec.confidence)
    top_low, top_high = percentile_interval(sampled[:, 2], spec.confidence)
    kept = np.linspace(0, len(draws) - 1, spec.kept_draws).round().astype(int)
    return GameModel(
        home_advantage=rounded(fitted[0]),
        home_low=rounded(home_low),
        home_high=rounded(home_high),
        net_rating=rounded(fitted[1]),
        net_low=rounded(net_low),
        net_high=rounded(net_high),
        top_players=rounded(fitted[2]),
        top_low=rounded(top_low),
        top_high=rounded(top_high),
        games=int(len(games)),
        draws=tuple(
            Draw(
                home=rounded(sampled[index, 0]),
                net_rating=rounded(sampled[index, 1]),
                top_players=rounded(sampled[index, 2]),
            )
            for index in kept
        ),
    )


def _by_era(games: pd.DataFrame, eras: Sequence[Era]) -> tuple[EraParameters, ...]:
    labels = games["season"].to_numpy()
    on_record = sorted(set(labels))
    out = []
    for era in eras:
        covered = era.seasons(on_record)
        inside = np.isin(labels, list(covered))
        if len(covered) < 2 or not inside.any():
            continue
        fitted = fit_game_model(games[inside], GAME_COLUMNS)
        out.append(
            EraParameters(
                key=era.key,
                label=era.name,
                first_season=covered[0],
                last_season=covered[-1],
                games=int(inside.sum()),
                home_advantage=rounded(fitted[0]),
                net_rating=rounded(fitted[1]),
                top_players=rounded(fitted[2]),
            )
        )
    return tuple(out)


# --- the bracket -----------------------------------------------------------------------------


def _bracket_evaluation(
    games: pd.DataFrame,
    series: pd.DataFrame,
    features: pd.DataFrame,
    pairings: dict[tuple[str, int, int], int],
    test_years: Sequence[int],
    spec: PostseasonSpec,
) -> BracketEvaluation:
    table = keyed(features)
    records = []
    favourites = []
    for year in test_years:
        train = games[games["start_year"] < year]
        season_series = series[series["start_year"] == year]
        if train.empty or season_series.empty:
            continue
        season = str(season_series["season"].iloc[0])
        try:
            bracket = bracket_from_series(season_series)
            teams = table.loc[season]
            weights = fit_game_model(train, GAME_COLUMNS)
            odds = propagate(
                bracket, teams, weights[0], weights[1], weights[2], spec=spec, head_to_head=pairings
            ).frame()
        except (BracketError, KeyError):
            continue
        for team in odds.index:
            actual = teams.loc[team]
            record = {
                "season": season,
                "start_year": year,
                "team_id": int(team),
                "seed": int(min(max(actual["conference_rank"], 1), PLAYOFF_PLACES))
                if pd.notna(actual["conference_rank"])
                else PLAYOFF_PLACES,
            }
            for key in ROUND_STAGE_KEYS:
                record[f"p_{key}"] = float(odds.at[team, key])
                record[key] = float(bool(actual[key]))
            records.append(record)
        champion = odds.index[odds["won_championship"].to_numpy().argmax()]
        actual_champion = teams.index[teams["won_championship"].to_numpy().astype(bool)]
        if len(actual_champion) == 1:
            favourites.append(
                SeasonFavourite(
                    season=season,
                    favourite_team_id=int(champion),
                    favourite_probability=rounded(odds.at[champion, "won_championship"]),
                    champion_team_id=int(actual_champion[0]),
                    champion_probability=rounded(odds.at[actual_champion[0], "won_championship"]),
                )
            )
    if not records:
        raise NotEnoughHistory("no season's bracket could be carried out of sample")
    frame = pd.DataFrame(records)
    history = features[features["decided"] & features["made_playoffs"]].assign(
        seed=lambda f: (
            f["conference_rank"].fillna(PLAYOFF_PLACES).clip(1, PLAYOFF_PLACES).astype(int)
        )
    )
    stages = []
    pooled_p: list[np.ndarray] = []
    pooled_y: list[np.ndarray] = []
    for key in ROUND_STAGE_KEYS:
        p = frame[f"p_{key}"].to_numpy()
        y = frame[key].to_numpy()
        seed_rate = np.array(
            [
                _seed_rate(history, int(year), int(seed), key)
                for year, seed in zip(frame["start_year"], frame["seed"], strict=True)
            ]
        )
        uniform = np.full(len(y), UNIFORM[key])
        stages.append(
            StageEvaluation(
                key=key,
                cases=int(len(y)),
                reached=int(y.sum()),
                mean_probability=rounded(p.mean()),
                log_loss=rounded(log_loss(p, y)),
                brier=rounded(brier(p, y)),
                calibration=calibration(p, y),
                baselines=(
                    Baseline(
                        key="seed_rate",
                        label="How often that seed got there before",
                        log_loss=rounded(log_loss(seed_rate, y)),
                        brier=rounded(brier(seed_rate, y)),
                    ),
                    Baseline(
                        key="uniform",
                        label="Every series a coin flip",
                        log_loss=rounded(log_loss(uniform, y)),
                        brier=rounded(brier(uniform, y)),
                    ),
                ),
            )
        )
        pooled_p.append(p)
        pooled_y.append(y)
    return BracketEvaluation(
        team_postseasons=int(len(frame)),
        stages=tuple(stages),
        reliability=reliability(
            np.concatenate(pooled_p),
            np.concatenate(pooled_y),
            spec.reliability_edges,
            confidence=spec.confidence,
        ),
        favourites=tuple(favourites),
    )


def _seed_rate(history: pd.DataFrame, year: int, seed: int, key: str) -> float:
    """How often teams of a seed reached a stage in the seasons before ``year``; the share
    among every playoff team when that seed has no history yet."""
    past = history[history["start_year"] < year]
    same = past[past["seed"] == seed]
    if same.empty:
        return float(past[key].mean()) if not past.empty else UNIFORM[key]
    return float(same[key].mean())


# --- the season model ---------------------------------------------------------------------


def _expanding_season(
    rows: pd.DataFrame, columns: Sequence[str], test_years: Sequence[int], *, direct: bool
) -> np.ndarray:
    """Each team-season's chance of every stage from steps fitted to earlier seasons:
    shape (rows, stages), missing where untested."""
    out = np.full((len(rows), len(BRACKET_STAGE_KEYS)), np.nan)
    for year in test_years:
        train = rows[rows["start_year"] < year].dropna(subset=list(columns))
        test = rows[rows["start_year"] == year].dropna(subset=list(columns))
        if train.empty or test.empty:
            continue
        weights = fit_step_weights(train, columns, direct=direct)
        out[test.index.to_numpy()] = apply_steps(weights, test, columns, direct=direct)
    return out


def _season_evaluation(
    decided: pd.DataFrame, test_years: Sequence[int], spec: PostseasonSpec
) -> SeasonEvaluation:
    rows = decided.copy()
    eighth = rows.groupby(["season", "conference"])["net_rating"].transform(
        lambda ratings: ratings.nlargest(PLAYOFF_PLACES).iloc[-1]
    )
    rows["conference_gap"] = rows["net_rating"] - eighth
    probability = _expanding_season(rows, STEP_COLUMNS, test_years, direct=False)
    tested = ~np.isnan(probability[:, 0])
    if not tested.any():
        raise NotEnoughHistory("no team-season could be scored out of sample")
    years = rows.loc[tested, "start_year"].to_numpy()
    stages = []
    pooled_p: list[np.ndarray] = []
    pooled_y: list[np.ndarray] = []
    for position, key in enumerate(BRACKET_STAGE_KEYS):
        p = probability[tested, position]
        y = rows.loc[tested, key].to_numpy(dtype="float64")
        base = np.array([rows.loc[rows["start_year"] < year, key].mean() for year in years])
        stages.append(
            StageEvaluation(
                key=key,
                cases=int(len(y)),
                reached=int(y.sum()),
                mean_probability=rounded(p.mean()),
                log_loss=rounded(log_loss(p, y)),
                brier=rounded(brier(p, y)),
                calibration=calibration(p, y),
                baselines=(
                    Baseline(
                        key="base_rate",
                        label="The share of past teams that got there, for every team",
                        log_loss=rounded(log_loss(base, y)),
                        brier=rounded(brier(base, y)),
                    ),
                ),
            )
        )
        pooled_p.append(p)
        pooled_y.append(y)
    model_losses = _summed_losses(probability, rows)
    comparisons = []
    for key, label, columns, direct in SEASON_ALTERNATIVES:
        other = _expanding_season(rows, columns, test_years, direct=direct)
        both = tested & ~np.isnan(other[:, 0])
        if not both.any():
            continue
        other_losses = _summed_losses(other, rows)
        difference, low, high = difference_interval(
            other_losses[both],
            model_losses[both],
            rows.loc[both, "start_year"].to_numpy(),
            resamples=spec.resamples,
            seed=spec.seed + 3,
            confidence=spec.confidence,
        )
        comparisons.append(
            Comparison(
                key=key,
                label=label,
                log_loss=rounded(other_losses[both].mean() / len(BRACKET_STAGE_KEYS)),
                brier=rounded(
                    np.mean(
                        [
                            brier(other[both, position], rows.loc[both, stage].to_numpy())
                            for position, stage in enumerate(BRACKET_STAGE_KEYS)
                        ]
                    )
                ),
                difference=rounded(difference / len(BRACKET_STAGE_KEYS)),
                low=rounded(low / len(BRACKET_STAGE_KEYS)),
                high=rounded(high / len(BRACKET_STAGE_KEYS)),
            )
        )
    return SeasonEvaluation(
        team_seasons=int(tested.sum()),
        stages=tuple(stages),
        reliability=reliability(
            np.concatenate(pooled_p),
            np.concatenate(pooled_y),
            spec.reliability_edges,
            confidence=spec.confidence,
        ),
        comparisons=tuple(comparisons),
    )


def _before_season_evaluation(
    decided: pd.DataFrame,
    test_years: Sequence[int],
    backtest: Sequence[BacktestRow],
    error: float | None,
    basis: str,
) -> BeforeSeasonEvaluation | None:
    """The season model scored from the ratings a forecast would have had.

    Each tested team-season is read from the value model's out-of-sample prediction of
    its net rating, averaged over the prediction's error by quadrature as the service
    does, with the top-player quality typical of that rating; the steps and the typical
    quality are fitted on the seasons before. ``None`` without predictions to read.
    """
    if not backtest or error is None or error < 0:
        return None
    ahead: dict[tuple[str, int], float] = {}
    for row in backtest:
        rating = row.projected_net if basis == "projected" else None
        ahead[(row.season, int(row.team_id))] = float(row.predicted if rating is None else rating)
    rows = decided.reset_index(drop=True)
    keys = zip(rows["season"].astype(str), rows["team_id"].astype(int), strict=True)
    rating = np.array([ahead.get(key, np.nan) for key in keys], dtype="float64")
    probability = np.full((len(rows), len(BRACKET_STAGE_KEYS)), np.nan)
    nodes, node_weights = np.polynomial.hermite.hermgauss(QUADRATURE_NODES)
    quadrature = node_weights / np.sqrt(np.pi)
    for year in test_years:
        train = rows[rows["start_year"] < year].dropna(subset=list(STEP_COLUMNS))
        testing = (rows["start_year"] == year).to_numpy() & np.isfinite(rating)
        if train.empty or not testing.any():
            continue
        weights = fit_step_weights(train, STEP_COLUMNS, direct=False)
        slope, intercept = np.polyfit(
            train["net_rating"].to_numpy(dtype="float64"),
            train["top_players"].to_numpy(dtype="float64"),
            1,
        )
        for index in np.flatnonzero(testing):
            ratings = rating[index] + np.sqrt(2.0) * error * nodes
            frame = pd.DataFrame(
                {"net_rating": ratings, "top_players": intercept + slope * ratings}
            )
            probability[index] = quadrature @ apply_steps(weights, frame, STEP_COLUMNS)
    tested = ~np.isnan(probability[:, 0])
    if not tested.any():
        return None
    years = rows.loc[tested, "start_year"].to_numpy()
    stages = []
    for position, key in enumerate(BRACKET_STAGE_KEYS):
        p = probability[tested, position]
        y = rows.loc[tested, key].to_numpy(dtype="float64")
        base = np.array([rows.loc[rows["start_year"] < year, key].mean() for year in years])
        stages.append(
            StageEvaluation(
                key=key,
                cases=int(len(y)),
                reached=int(y.sum()),
                mean_probability=rounded(p.mean()),
                log_loss=rounded(log_loss(p, y)),
                brier=rounded(brier(p, y)),
                calibration=calibration(p, y),
                baselines=(
                    Baseline(
                        key="base_rate",
                        label="The share of past teams that got there, for every team",
                        log_loss=rounded(log_loss(base, y)),
                        brier=rounded(brier(base, y)),
                    ),
                ),
            )
        )
    seasons = sorted(set(rows.loc[tested, "season"].astype(str)))
    return BeforeSeasonEvaluation(
        team_seasons=int(tested.sum()),
        first_test_season=seasons[0],
        last_test_season=seasons[-1],
        rating_basis=basis,
        rating_error=rounded(error),
        stages=tuple(stages),
    )


def _summed_losses(probability: np.ndarray, rows: pd.DataFrame) -> np.ndarray:
    """Each team-season's log loss added over the five stages (missing where untested)."""
    total = np.zeros(len(rows))
    for position, key in enumerate(BRACKET_STAGE_KEYS):
        total += row_losses(
            np.nan_to_num(probability[:, position], nan=0.5), rows[key].to_numpy(dtype="float64")
        )
    total[np.isnan(probability[:, 0])] = np.nan
    return total
