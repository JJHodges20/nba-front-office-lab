"""What is known of a player entering a season: the seasons before it, pooled.

A recent season says more than an older one and a long season more than a short one, so
earlier seasons are averaged by minutes played, discounted by how long ago they were.
``reliability`` is how much of the estimate those minutes can carry: weighted minutes
over weighted minutes plus the ballast, the minutes of an unknown player mixed into
every estimate. The rest of the estimate is what the model assumes of any player in
that role.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from front_office.domain.value_model import ValueSpec

POOLED_COLUMNS = ("mpg_centred", "reliability", "age", "seasons", "weight")


def reliability(weighted_minutes: pd.Series, spec: ValueSpec) -> pd.Series:
    """The share of an estimate that rests on the player's own numbers."""
    return weighted_minutes / (weighted_minutes + spec.ballast_minutes)


def entering(features: pd.DataFrame, spec: ValueSpec, keys: Sequence[str]) -> pd.DataFrame:
    """One row per player per season entered, from the seasons before it.

    ``features`` is :func:`~front_office.modeling.value.features.season_features`;
    ``keys`` are the columns to pool. A season ``lag`` seasons back counts
    ``spec.season_weights[lag - 1]`` per minute. Returns ``player_id``, ``target`` (the
    start year of the season entered), the pooled ``keys`` and :data:`POOLED_COLUMNS`:

    * ``mpg_centred`` - pooled like the features;
    * ``reliability`` - see the module docstring;
    * ``age`` - the age the newest of those seasons implies for the season entered;
    * ``seasons`` - how many earlier seasons the estimate draws on;
    * ``weight`` - the weighted minutes behind it.

    A player with no minutes in any of those seasons has no row.
    """
    pooled_keys = [*keys, "mpg_centred"]
    parts = []
    for lag, season_weight in enumerate(spec.season_weights, start=1):
        part = features[["player_id", "start", "age", *pooled_keys]].copy()
        part["target"] = part["start"] + lag
        part["weight"] = season_weight * features["evidence_minutes"]
        parts.append(part[part["weight"] > 0])
    stacked = pd.concat(parts, ignore_index=True)
    index = ["player_id", "target"]

    weighted = stacked[pooled_keys].mul(stacked["weight"], axis=0)
    weighted[index] = stacked[index]
    weighted["weight"] = stacked["weight"]
    sums = weighted.groupby(index).sum()
    pooled = sums[pooled_keys].div(sums["weight"], axis=0)
    pooled["reliability"] = reliability(sums["weight"], spec)

    newest = stacked.sort_values("start").groupby(index).tail(1).set_index(index)
    newest = newest.reindex(pooled.index)
    pooled["age"] = newest["age"] + (pooled.index.get_level_values("target") - newest["start"])
    pooled["seasons"] = stacked.groupby(index).size()
    pooled["weight"] = sums["weight"]
    return pooled.reset_index()
