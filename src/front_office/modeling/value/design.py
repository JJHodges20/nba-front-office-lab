"""The model's terms: how what is known of a player becomes an estimate.

An estimate is a weighted sum of terms, and the same terms serve twice. Summed over a
team's players by their share of the minutes they are one row of the regression that
finds the weights; taken for one player they are that player's rating. Fitting and
scoring therefore cannot drift apart: there is one definition of the model, here.

For a player with earlier seasons on record::

    estimate = reliability x (weights . features)
             + (1 - reliability) x (prior level + prior slope x minutes per game)
             + age slope x (age - centre)

The middle line is what is assumed where the player's own numbers run out. It depends
on minutes per game because that is all that is known about a player who has barely
played: someone used 30 minutes a night for a month is not the same unknown as someone
used for five. A player with no earlier season at all gets a single fitted level.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from front_office.domain.value_model import ValueSpec
from front_office.modeling.value.features import FEATURE_KEYS

PRIOR_LEVEL = "prior_level"
PRIOR_MINUTES = "prior_minutes"
AGE = "age"
NEW_PLAYER = "new_player"
LEVEL_KEYS: tuple[str, ...] = (PRIOR_LEVEL, PRIOR_MINUTES, AGE, NEW_PLAYER)
TERM_KEYS: tuple[str, ...] = (*FEATURE_KEYS, *LEVEL_KEYS)

LEVEL_LABELS = {
    PRIOR_LEVEL: "Unproven part: level",
    PRIOR_MINUTES: "Unproven part: per minute a game",
    AGE: "Age, per year",
    NEW_PLAYER: "No earlier season",
}
LEVEL_DESCRIPTIONS = {
    PRIOR_LEVEL: (
        "What is assumed of the part of a player the minutes do not yet vouch for, at the "
        "league's average minutes per game."
    ),
    PRIOR_MINUTES: (
        "How that assumption moves with each minute per game above or below the "
        "league's average: playing time is itself evidence."
    ),
    AGE: "Change in next season's estimate for each year of age past the centre.",
    NEW_PLAYER: "The level of a player with no earlier season on record.",
}

SHARE_TOLERANCE = 0.05
"""A team's players' shares add up to 5; further off than this, players are missing."""


def player_terms(
    known: pd.DataFrame,
    spec: ValueSpec,
    keys: Sequence[str] = FEATURE_KEYS,
    levels: Sequence[str] = LEVEL_KEYS,
) -> pd.DataFrame:
    """Each row's terms, one column per key in ``keys`` then ``levels``.

    ``known`` holds the pooled ``keys``, ``mpg_centred``, ``reliability`` and ``age``,
    as :func:`~front_office.modeling.value.pooling.entering` returns them. A row whose
    reliability is missing is a player with nothing on record: every term is zero
    except ``new_player``.
    """
    seen = known["reliability"].notna().to_numpy()
    trust = known["reliability"].fillna(0.0).to_numpy()
    values = known[list(keys)].fillna(0.0).to_numpy() * trust[:, None]
    terms = pd.DataFrame(values, columns=list(keys), index=known.index)
    unproven = np.where(seen, 1.0 - trust, 0.0)
    built = {
        PRIOR_LEVEL: unproven,
        PRIOR_MINUTES: unproven * known["mpg_centred"].fillna(0.0).to_numpy(),
        AGE: np.where(seen, known["age"].fillna(spec.age_centre).to_numpy() - spec.age_centre, 0.0),
        NEW_PLAYER: np.where(seen, 0.0, 1.0),
    }
    for level in levels:
        terms[level] = built[level]
    return terms


def team_design(
    played: pd.DataFrame,
    pooled: pd.DataFrame,
    spec: ValueSpec,
    keys: Sequence[str] = FEATURE_KEYS,
    levels: Sequence[str] = LEVEL_KEYS,
) -> pd.DataFrame:
    """One row per team-season: its players' terms, summed by their share of the minutes.

    ``played`` is the stints of the seasons to describe and ``pooled`` what was known
    of each player entering them. Indexed by ``(season, team_id)``; ``share`` is the
    total share on record, which is 5 when every player is.
    """
    joined = played.merge(
        pooled, left_on=["player_id", "start"], right_on=["player_id", "target"], how="left"
    )
    share = joined["share"].fillna(0.0).to_numpy()
    summed = player_terms(joined, spec, keys, levels).mul(share, axis=0)
    summed["share"] = share
    summed["season"], summed["team_id"] = joined["season"].to_numpy(), joined["team_id"].to_numpy()
    return summed.groupby(["season", "team_id"]).sum()


def is_complete(design: pd.DataFrame) -> pd.Series:
    """Whether a team-season's players are all on record."""
    return (design["share"] - 5.0).abs() <= SHARE_TOLERANCE
