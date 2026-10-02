"""Apply a fitted value model: every player's season, projection and wins.

Two estimates come out for each player-season, built from the same weights.

* **Impact** is what the season itself showed: that season's features, trusted in
  proportion to the minutes behind them. It is centred so that the league's average
  minute is zero in every season.
* **The projection** is what was expected going into the season: the seasons before it
  pooled, plus age. This is the estimate the model was tested on.

Neither splits up what a team actually did. A team's impacts add up to roughly its net
rating - the fitted model reports how closely - but an estimate of ability is not an
account of results, and nothing here forces the two to agree.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from front_office.domain.seasons import Season
from front_office.domain.tables.value import BASELINE_PART, PART_PREFIX, PLAYER_VALUE_SCORES
from front_office.domain.value_model import DEFENSE, OFFENSE, SIDES, ValueModel, ValueSpec
from front_office.modeling.value import availability
from front_office.modeling.value.design import (
    PRIOR_LEVEL,
    PRIOR_MINUTES,
    TERM_KEYS,
    player_terms,
)
from front_office.modeling.value.features import (
    COMPONENT_KEYS,
    FEATURE_KEYS,
    features_of,
    season_features,
    stints,
    weighted_mean_by_season,
)
from front_office.modeling.value.pooling import entering, reliability
from front_office.modeling.value.wins import FULL_SEASON_GAMES, wins_per_net_point

Tables = Mapping[str, pd.DataFrame]


class ModelMismatch(ValueError):
    """The fitted model's terms are not the ones this version of the lab computes."""


def check_terms(model: ValueModel) -> None:
    if model.keys != TERM_KEYS:
        missing = sorted(set(TERM_KEYS) - set(model.keys))
        extra = sorted(set(model.keys) - set(TERM_KEYS))
        raise ModelMismatch(
            "the fitted value model does not match this version of the lab "
            f"(missing terms {missing}, unknown terms {extra}); fit it again: fol value fit --write"
        )


Weights = Mapping[str, Mapping[str, float]]
"""Every term's weight on each side of the ball: ``{"offense": {...}, "defense": {...}}``."""


def side_weights(model: ValueModel) -> dict[str, dict[str, float]]:
    return {side: model.weights(side) for side in SIDES}


def season_impact(features: pd.DataFrame, spec: ValueSpec, weights: Weights) -> pd.DataFrame:
    """What each season showed, on ``features``' index.

    Returns ``reliability``, ``impact``, ``impact_offense``, ``impact_defense`` and one
    ``impact_from_...`` column per part; the parts add up to ``impact``.
    """
    own = features[[*FEATURE_KEYS, "mpg_centred"]].copy()
    own["reliability"] = reliability(features["evidence_minutes"], spec)
    own["age"] = spec.age_centre  # a season is described as it was: no aging
    terms = player_terms(own, spec)

    scored = pd.DataFrame({"reliability": own["reliability"]}, index=features.index)
    centre = 0.0
    for side in SIDES:
        uncentred = _weigh(terms, weights[side])
        side_centre = weighted_mean_by_season(
            features.assign(uncentred=uncentred), "uncentred", "minutes"
        )
        scored[f"impact_{side}"] = uncentred - side_centre
        centre = centre + side_centre
    scored["impact"] = scored[f"impact_{OFFENSE}"] + scored[f"impact_{DEFENSE}"]

    net = {key: weights[OFFENSE][key] + weights[DEFENSE][key] for key in TERM_KEYS}
    for key in COMPONENT_KEYS:
        scored[f"{PART_PREFIX}{key}"] = _weigh(terms, net, features_of(key))
    assumed = _weigh(terms, net, (PRIOR_LEVEL, PRIOR_MINUTES))
    scored[f"{PART_PREFIX}{BASELINE_PART}"] = assumed - centre
    return scored


def projection(known: pd.DataFrame, spec: ValueSpec, weights: Weights) -> pd.DataFrame:
    """What the model expects of each row of ``known``, on its index.

    ``known`` is what :func:`~front_office.modeling.value.pooling.entering` returns for
    the players wanted, with missing values where a player has no earlier season.
    """
    terms = player_terms(known, spec)
    projected = pd.DataFrame(index=known.index)
    for side in SIDES:
        projected[f"projected_{side}"] = _weigh(terms, weights[side])
    projected["projected_impact"] = (
        projected[f"projected_{OFFENSE}"] + projected[f"projected_{DEFENSE}"]
    )
    return projected


def score_players(tables: Tables, model: ValueModel) -> pd.DataFrame:
    """Every row of ``player_value_scores`` that the tables and the model support."""
    check_terms(model)
    played = stints(tables["player_seasons"], tables["player_game_logs"], tables["team_seasons"])
    features = season_features(tables["player_seasons"], tables["team_seasons"], played)
    if features.empty:
        return PLAYER_VALUE_SCORES.empty_frame()
    spec, weights = model.spec, side_weights(model)
    pooled = entering(features, spec, FEATURE_KEYS)

    seasons = features[["player_id", "season", "start", "age"]].rename(columns={"start": "target"})
    seasons = pd.concat([seasons, season_impact(features, spec, weights)], axis=1)
    by_team = played.assign(full_season=played["share"] * played["team_games"] / FULL_SEASON_GAMES)
    totals = by_team.groupby(["player_id", "start"])[["share", "full_season"]].sum(min_count=1)
    at = pd.MultiIndex.from_frame(seasons[["player_id", "target"]])
    seasons["minutes_share"] = totals["share"].reindex(at).to_numpy()
    seasons["full_season_share"] = totals["full_season"].reindex(at).to_numpy()

    # The one season still to be played or still being played: the newest on record
    # while it is unfinished, for the players who have yet to appear in it, and the
    # season after it once it is over.
    upcoming = _upcoming(features, tables["team_seasons"])
    ahead = pooled.loc[pooled["target"] == upcoming, ["player_id", "target", "age"]]
    appeared = pd.MultiIndex.from_frame(ahead[["player_id", "target"]]).isin(at)
    ahead = ahead[~appeared].assign(
        season=lambda rows: [Season(int(year)).label for year in rows["target"]]
    )
    rows = pd.concat([seasons, ahead], ignore_index=True)

    earlier = pooled.drop(columns="age")
    known = rows[["player_id", "target", "age"]].merge(
        earlier, on=["player_id", "target"], how="left"
    )
    known.index = rows.index
    rows = pd.concat([rows, projection(known, spec, weights)], axis=1)
    rows["projection_reliability"] = known["reliability"]
    rows["projection_seasons"] = known["seasons"].fillna(0).astype("int64")

    minutes = availability.history(features, availability.season_shares(played))
    usage = rows[["player_id", "target", "age"]].merge(
        minutes.drop(columns="age"), on=["player_id", "target"], how="left"
    )
    usage.index = rows.index
    rows["projected_share"] = availability.project(usage, model.availability.coefficients)

    per_point = _per_point(tables["team_seasons"], spec.wins_window, rows["target"])
    above = rows["impact"] - model.replacement_level
    rows["wins_added"] = above * rows["full_season_share"] * per_point
    expected = rows["projected_impact"] - model.replacement_level
    rows["projected_wins"] = expected * rows["projected_share"] * per_point

    rows["model_version"] = model.version
    rows["age"] = rows["age"].round().astype("Int64")
    return rows[list(PLAYER_VALUE_SCORES.column_names)].sort_values(
        ["season", "player_id"], ignore_index=True
    )


def _upcoming(features: pd.DataFrame, team_seasons: pd.DataFrame) -> int:
    """Start year of the season that projections look ahead to."""
    latest = int(features["start"].max())
    label = Season(latest).label
    decided = team_seasons.loc[team_seasons["season"] == label, "won_championship"]
    return latest + 1 if decided.notna().any() else latest


def _weigh(terms: pd.DataFrame, weights: Mapping[str, float], keys: tuple[str, ...] | None = None):  # type: ignore[no-untyped-def]
    """The weighted sum of ``keys`` (every term by default) for each row."""
    chosen = list(TERM_KEYS if keys is None else keys)
    return pd.Series(
        terms[chosen].to_numpy() @ np.array([weights[key] for key in chosen]), index=terms.index
    )


def _per_point(team_seasons: pd.DataFrame, window: int, starts: pd.Series) -> pd.Series:
    """Wins per point of net rating for each start year; a season not yet played takes
    the newest figure there is."""
    by_season = wins_per_net_point(team_seasons, window=window)
    if by_season.empty:
        return pd.Series(np.nan, index=starts.index)
    by_start = pd.Series(
        by_season.to_numpy(), index=[Season.parse(label).start_year for label in by_season.index]
    )
    years = range(min(by_start.index.min(), int(starts.min())), int(starts.max()) + 1)
    return starts.map(by_start.reindex(years).ffill().bfill())
