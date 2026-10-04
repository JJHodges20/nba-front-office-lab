"""Archetypes: every player scored against every role's rule.

A role's score is the weakest of a player's percentiles on the role's measures, taken
among the players the role is open to in that season. Percentiles within a season keep
eras comparable: a floor spacer of 2004 is one against the shooters of 2004.

Nothing here is fitted or tested for accuracy - a rule has no accuracy. What can be
checked is whether a role is a lasting trait or a one-season accident, and
:func:`persistence` measures that.

The measures are what thirty seasons of box scores, listed positions and the value
model can see. They cannot see who a player guarded, whether a shot came off movement,
or a screen: each archetype's note says what its measures stand in for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from front_office.analytics import formulas as f
from front_office.domain.archetypes import EVERYONE, ArchetypeSet
from front_office.domain.seasons import SeasonType

Tables = Mapping[str, pd.DataFrame]
REGULAR = SeasonType.REGULAR.value

THREE_POINT_PRIOR_ATTEMPTS = 240
"""League-average attempts mixed into a three-point percentage before it is ranked: a
season's worth for a regular shooter. Forty makes on a hundred tries says less than
forty percent on four hundred."""
WING_POSITIONS = ("G-F", "F-G", "F")
WING_HEIGHT = (77, 82)
"""Inches: 6'5" to 6'10"."""
BIG_HEIGHT = 83
"""Inches: at 6'11" a player is a big whatever position is listed."""
LOW_USAGE_PERCENTILE = 40

ASSIGNMENT_COLUMNS = (
    "player_id",
    "season",
    "archetype",
    "score",
    "fills",
    "is_primary",
    "archetype_version",
)


@dataclass(frozen=True, slots=True)
class Named:
    key: str
    label: str
    description: str


MEASURES: tuple[Named, ...] = (
    Named("usage_pct", "Usage", "Share of the team's plays the player used while on the court."),
    Named("assist_pct", "Assist percentage", "Share of teammates' baskets the player assisted."),
    Named("fg3a_per_100", "Three-point attempts", "Three-point attempts per 100 possessions."),
    Named(
        "fg3_pct_regressed",
        "Three-point accuracy",
        f"Three-point percentage with {THREE_POINT_PRIOR_ATTEMPTS} league-average attempts "
        "mixed in, so that a few hot nights do not make a shooter.",
    ),
    Named("stl_per_100", "Steals", "Steals per 100 possessions on the court."),
    Named("blk_per_100", "Blocks", "Blocks per 100 possessions on the court."),
    Named("stocks_per_100", "Steals and blocks", "Steals plus blocks per 100 possessions."),
    Named("impact_defense", "Defensive impact", "The value model's estimate of points saved."),
    Named("ast_per_tov", "Assists per turnover", "Assists for every turnover."),
    Named("ts_pct", "True shooting", "Points per scoring attempt, halved."),
)
MEASURE_KEYS: tuple[str, ...] = tuple(measure.key for measure in MEASURES)

GROUPS: tuple[Named, ...] = (
    Named(EVERYONE, "Everyone", "Every player with enough minutes."),
    Named("guards", "Guards", "Players listed at guard, alone or with another position."),
    Named(
        "wings",
        "Wings",
        f"Players listed {', '.join(WING_POSITIONS[:-1])} or {WING_POSITIONS[-1]} who stand "
        f"{WING_HEIGHT[0]} to {WING_HEIGHT[1]} inches.",
    ),
    Named(
        "bigs",
        "Big men",
        f"Players listed at center, alone or with another position, or {BIG_HEIGHT} inches "
        "and taller.",
    ),
    Named(
        "low_usage",
        "Low-usage players",
        f"Players in the bottom {LOW_USAGE_PERCENTILE}% of the league by usage.",
    ),
)
GROUP_KEYS: tuple[str, ...] = tuple(group.key for group in GROUPS)


class UnknownDefinition(ValueError):
    """An archetype names a measure or a group this version of the lab does not compute."""


def check_definitions(spec: ArchetypeSet) -> None:
    for archetype in spec:
        unknown = [key for key in archetype.measures if key not in MEASURE_KEYS]
        if unknown:
            raise UnknownDefinition(
                f"archetype {archetype.key!r} uses unknown measures {unknown}; "
                f"known: {list(MEASURE_KEYS)}"
            )
        if archetype.among not in GROUP_KEYS:
            raise UnknownDefinition(
                f"archetype {archetype.key!r} is open to an unknown group "
                f"{archetype.among!r}; known: {list(GROUP_KEYS)}"
            )


def percentile(values: pd.Series, season: pd.Series) -> pd.Series:
    """Each value's standing among the values of its season: the share it is ahead of,
    ties counted as half, from 0 to 100. Missing values have no standing and are no one's
    peers."""
    grouped = values.groupby(season)
    return (grouped.rank(method="average") - 0.5) / grouped.transform("count") * 100


def measured(tables: Tables, spec: ArchetypeSet) -> pd.DataFrame:
    """Every player-season with enough minutes: its measures and the groups it is in.

    One row per player per regular season with ``season``, ``player_id``, a column per
    measure and a boolean ``in_<group>`` per group. ``impact_defense`` is missing where
    the season has not been valued.
    """
    seasons = tables["player_seasons"]
    seasons = seasons[seasons["season_type"] == REGULAR].reset_index(drop=True)
    possessions = seasons["possessions"].astype("float64")
    frame = seasons[["season", "player_id"]].copy()
    frame["usage_pct"] = seasons["usage_pct"].astype("float64")
    frame["assist_pct"] = seasons["assist_pct"].astype("float64")
    frame["fg3a_per_100"] = f.per_100(seasons["fg3a"], possessions)
    frame["stl_per_100"] = f.per_100(seasons["stl"], possessions)
    frame["blk_per_100"] = f.per_100(seasons["blk"], possessions)
    frame["stocks_per_100"] = f.per_100(seasons["stl"] + seasons["blk"], possessions)
    frame["ast_per_tov"] = f.assist_to_turnover(seasons["ast"], seasons["tov"])
    frame["ts_pct"] = f.true_shooting_pct(seasons["pts"], seasons["fga"], seasons["fta"])

    made = seasons["fg3m"].astype("float64")
    tried = seasons["fg3a"].astype("float64")
    league = f.safe_divide(
        made.groupby(seasons["season"]).transform("sum"),
        tried.groupby(seasons["season"]).transform("sum"),
    )
    frame["fg3_pct_regressed"] = f.safe_divide(
        made + THREE_POINT_PRIOR_ATTEMPTS * league, tried + THREE_POINT_PRIOR_ATTEMPTS
    )

    scores = tables["player_value_scores"].set_index(["season", "player_id"])["impact_defense"]
    at = pd.MultiIndex.from_frame(frame[["season", "player_id"]])
    frame["impact_defense"] = scores.reindex(at).to_numpy()

    enough = (seasons["minutes"] >= spec.min_minutes) & (possessions > 0)
    frame = frame[enough.to_numpy()].reset_index(drop=True)

    known = tables["players"].set_index("player_id")
    position = frame["player_id"].map(known["position"]).fillna("").astype("str")
    height = frame["player_id"].map(known["height_inches"]).astype("float64")
    usage = percentile(frame["usage_pct"], frame["season"])
    frame[f"in_{EVERYONE}"] = True
    frame["in_guards"] = position.str.contains("G")
    frame["in_wings"] = position.isin(WING_POSITIONS) & height.between(*WING_HEIGHT)
    frame["in_bigs"] = position.str.contains("C") | (height >= BIG_HEIGHT)
    frame["in_low_usage"] = usage <= LOW_USAGE_PERCENTILE
    return frame


def classify(players: pd.DataFrame, spec: ArchetypeSet) -> pd.DataFrame:
    """Score every player in ``players`` (:func:`measured`) against every archetype.

    One row per player per season per archetype the player is open to and has every
    measure for: :data:`ASSIGNMENT_COLUMNS`. ``fills`` is the archetype's cut-off
    applied to the score; ``is_primary`` marks, of the roles a player fills, the one
    with the highest score - the first in the set's order if two are level.
    """
    check_definitions(spec)
    parts = []
    for order, archetype in enumerate(spec):
        open_to = players[f"in_{archetype.among}"].to_numpy()
        ranked = pd.DataFrame(
            {
                key: percentile(players[key].where(open_to), players["season"])
                for key in archetype.measures
            }
        )
        score = ranked.min(axis=1, skipna=False)
        part = players.loc[score.notna(), ["player_id", "season"]].copy()
        part["archetype"] = archetype.key
        part["score"] = score[score.notna()]
        part["fills"] = part["score"] >= spec.cut(archetype)
        if archetype.fills_below is not None:
            part["fills"] &= part["score"] < archetype.fills_below
        part["order"] = order
        parts.append(part)
    if not parts:
        return pd.DataFrame(columns=list(ASSIGNMENT_COLUMNS))
    rows = pd.concat(parts, ignore_index=True)

    filled = rows[rows["fills"]].sort_values(["score", "order"], ascending=[False, True])
    best = filled.drop_duplicates(["player_id", "season"]).index
    rows["is_primary"] = rows.index.isin(best)
    rows["archetype_version"] = spec.label
    ordered = rows.sort_values(["season", "player_id", "order"], ignore_index=True)
    return ordered[list(ASSIGNMENT_COLUMNS)]


def assign_archetypes(tables: Tables, spec: ArchetypeSet) -> pd.DataFrame:
    """Every row of ``player_archetypes`` that the tables support."""
    return classify(measured(tables, spec), spec)


def persistence(assignments: pd.DataFrame, spec: ArchetypeSet) -> pd.DataFrame:
    """How well each role carries over from one season to the next.

    For each archetype, among players scored for it in two seasons running: how many
    filled it in the first (``filled``), what share of those filled it again in the
    second (``again``), and what share of everyone scored in the second filled it
    (``anyone``). A role that carries over has ``again`` well above ``anyone``.
    """
    columns = ["archetype", "name", "pairs", "filled", "again", "anyone"]
    rows = []
    start = assignments["season"].str.slice(0, 4).astype("int64")
    now = assignments.assign(start=start)
    later = now[["player_id", "archetype", "start", "fills"]].assign(start=start - 1)
    both = now.merge(later, on=["player_id", "archetype", "start"], suffixes=("", "_next"))
    for archetype in spec:
        mine = both[both["archetype"] == archetype.key]
        first = mine["fills"].astype(bool)
        rows.append(
            {
                "archetype": archetype.key,
                "name": archetype.name,
                "pairs": len(mine),
                "filled": int(first.sum()),
                "again": f.safe_divide(mine.loc[first, "fills_next"].sum(), first.sum()),
                "anyone": f.safe_divide(mine["fills_next"].sum(), len(mine)),
            }
        )
    return pd.DataFrame(rows, columns=columns)
