"""How much a player is likely to play next season.

A rating is worth nothing on the bench or in the treatment room, so value needs minutes
as well as quality. The projection is deliberately plain: next season's share of team
minutes from the last three seasons' shares and from age, fitted on every player seen
in those three seasons - including the ones who then did not play at all, because
that, too, is what happens to players.

It knows nothing about injuries, contracts or depth charts, and it is tested against
the obvious alternative: assuming the same share as last season.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import numpy as np
import pandas as pd

from front_office.domain.value_model import Availability, ValueSpec
from front_office.modeling.value.resampling import interval, rmse_differences

LAGS = (1, 2, 3)
SHARE_KEYS = tuple(f"share_{lag}" for lag in LAGS)
# Where the fitted line is allowed to bend: playing time falls away after 30 and is
# still growing before 25. Two knots of a fitted curve, not findings.
VETERAN_AGE = 30
YOUNG_AGE = 25
OVER, UNDER = f"years_over_{VETERAN_AGE}", f"years_under_{YOUNG_AGE}"
INTERCEPT = "intercept"
TERMS: tuple[str, ...] = (INTERCEPT, *SHARE_KEYS, OVER, UNDER)
DECIMALS = 6


class NotEnoughHistory(ValueError):
    """There are too few seasons to fit or to test the projection."""


def season_shares(played: pd.DataFrame) -> pd.DataFrame:
    """Each player's share of team minutes in each season, every team added up."""
    shares = played.assign(share=played["share"].fillna(0.0))
    return shares.groupby(["player_id", "start"], as_index=False)["share"].sum()


def history(features: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """One row per player per season entered: the three shares before it, and age.

    ``features`` supplies each season's age and ``shares`` is :func:`season_shares`. A
    player appears for a season if any of the three before it has minutes. Returns
    ``player_id``, ``target``, :data:`SHARE_KEYS` and ``age``, the age the newest of
    those seasons implies.
    """
    seasons = features[["player_id", "start", "age"]].merge(
        shares, on=["player_id", "start"], how="left"
    )
    seasons["share"] = seasons["share"].fillna(0.0)
    parts = []
    for lag in LAGS:
        part = seasons.copy()
        part["target"] = part["start"] + lag
        part["age"] = part["age"] + lag
        part["lag"] = lag
        parts.append(part)
    stacked = pd.concat(parts, ignore_index=True)
    index = ["player_id", "target"]
    wide = (
        stacked.pivot_table(index=index, columns="lag", values="share", aggfunc="sum")
        .reindex(columns=list(LAGS))
        .fillna(0.0)
    )
    wide.columns = list(SHARE_KEYS)
    wide["age"] = stacked.sort_values("lag").groupby(index)["age"].first()
    return wide[wide[list(SHARE_KEYS)].sum(axis=1) > 0].reset_index()


def terms(known: pd.DataFrame) -> pd.DataFrame:
    """The projection's terms for each row of ``known``: shares and age."""
    age = known["age"].astype("float64")
    return pd.DataFrame(
        {
            INTERCEPT: 1.0,
            **{key: known[key].astype("float64").fillna(0.0) for key in SHARE_KEYS},
            OVER: (age - VETERAN_AGE).clip(lower=0).fillna(0.0),
            UNDER: (YOUNG_AGE - age).clip(lower=0).fillna(0.0),
        },
        index=known.index,
    )[list(TERMS)]


def project(known: pd.DataFrame, coefficients: Mapping[str, float]) -> pd.Series:
    """Projected share of team minutes: never below zero, never above the whole game."""
    weights = np.array([coefficients[key] for key in TERMS])
    return pd.Series(terms(known).to_numpy() @ weights, index=known.index).clip(0.0, 1.0)


def fit_availability(
    features: pd.DataFrame, played: pd.DataFrame, finished: Collection[int], spec: ValueSpec
) -> Availability:
    """Fit the projection and test it one season at a time on seasons it had not seen.

    ``finished`` are the start years of the seasons whose minutes are final.
    """
    shares = season_shares(played)
    known = history(features, shares)
    known = known[known["target"].isin(list(finished)) & known["age"].notna()]
    actual = shares.rename(columns={"start": "target", "share": "actual"})
    known = known.merge(actual, on=["player_id", "target"], how="left")
    known["actual"] = known["actual"].fillna(0.0)

    design = terms(known).to_numpy()
    actual_share = known["actual"].to_numpy()
    target = known["target"].to_numpy()
    first_test = int(spec.first_test_season[:4])
    tested = np.zeros(len(known), dtype=bool)
    predicted = np.zeros(len(known))
    for year in sorted({int(value) for value in target if value >= first_test}):
        train, test = target < year, target == year
        if not train.any():
            continue
        weights = np.linalg.lstsq(design[train], actual_share[train], rcond=None)[0]
        predicted[test] = np.clip(design[test] @ weights, 0.0, 1.0)
        tested |= test
    if not tested.any():
        raise NotEnoughHistory(
            f"no season from {spec.first_test_season} has earlier seasons to learn minutes from"
        )

    errors = (predicted - actual_share)[tested]
    same_again = (known[SHARE_KEYS[0]].to_numpy() - actual_share)[tested]
    low, high = interval(rmse_differences(errors, same_again, target[tested], spec), spec)
    fitted = np.linalg.lstsq(design, actual_share, rcond=None)[0]
    return Availability(
        coefficients={key: _round(weight) for key, weight in zip(TERMS, fitted, strict=True)},
        players=int(tested.sum()),
        rmse=_round(_rmse(errors)),
        mae=_round(np.abs(errors).mean()),
        baseline_rmse=_round(_rmse(same_again)),
        baseline_mae=_round(np.abs(same_again).mean()),
        difference=_round(_rmse(errors) - _rmse(same_again)),
        low=_round(low),
        high=_round(high),
    )


def _rmse(errors: np.ndarray) -> float:
    return float(np.sqrt((errors**2).mean()))


def _round(value: float) -> float:
    return round(float(value), DECIMALS)
