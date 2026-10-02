"""Describing a group of players as a group: what a hand-built roster adds up to.

Everything here is description, not projection. Pooled figures say what these players
produced on the teams they actually played for; they do not say what the players would
produce together, which depends on roles, minutes and fit that no sum can capture.
"""

from __future__ import annotations

import pandas as pd

from front_office.analytics import formulas as f
from front_office.analytics.comparison import POSITION_GROUPS, pooled_metrics
from front_office.analytics.players import PLAYER_METRICS
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS

COMPOSITION = "Composition"
SHOOTING = "Shooting, pooled"
PRODUCTION = "Production, pooled"

PLAYER_MINUTES_PER_GAME = 5 * f.GAME_MINUTES
"""Player-minutes a team has to fill in a regulation game."""

_POOLED_SHOOTING = ("ts_pct", "efg_pct", "fg3_pct", "ft_pct", "fg3a_rate", "ft_rate")
_POOLED_PRODUCTION = (
    "pts_per_36",
    "reb_per_36",
    "ast_per_36",
    "stl_per_36",
    "blk_per_36",
    "tov_pct",
    "ast_to_tov",
)
POOLED_KEYS: tuple[str, ...] = (*_POOLED_SHOOTING, *_POOLED_PRODUCTION)
"""Indicators that are a pooled rate, and so have a league-wide value to compare with."""


def _pooled(key: str, category: str) -> MetricSpec:
    """A player metric, restated for a group whose totals are pooled."""
    spec = PLAYER_METRICS[key]
    return MetricSpec(
        key,
        spec.label,
        spec.name,
        f"{spec.description} Computed from the group's pooled totals.",
        category,
        spec.format,
        higher_is_better=spec.higher_is_better,
        decimals=spec.decimals,
    )


ROSTER_METRICS = MetricCatalog(
    (
        MetricSpec(
            "players",
            "Players",
            "Players",
            "Players on the roster.",
            COMPOSITION,
            MetricFormat.COUNT,
            higher_is_better=None,
        ),
        MetricSpec(
            "players_with_stats",
            "With stats",
            "Players with statistics",
            "Players on the roster who played in the statistics season. The rest add "
            "nothing to the pooled figures.",
            COMPOSITION,
            MetricFormat.COUNT,
            higher_is_better=None,
        ),
        *(
            MetricSpec(
                f"{name.lower()}s",
                f"{name}s",
                f"{name}s",
                f"Players whose first listed position is {name.lower()}.",
                COMPOSITION,
                MetricFormat.COUNT,
                higher_is_better=None,
            )
            for name in POSITION_GROUPS.values()
        ),
        MetricSpec(
            "age",
            "Age",
            "Average age, weighted by minutes",
            "Average age during the statistics season, each player weighted by minutes "
            "played: the age of the minutes, not of the bench.",
            COMPOSITION,
            higher_is_better=None,
        ),
        MetricSpec(
            "minutes_share",
            "MIN%",
            "Share of a team season's minutes",
            "Minutes the group played in the statistics season, as a share of the minutes "
            "a team has to fill. Above 100% the group has played more minutes than one "
            "team has; below it, someone has to play more than before.",
            COMPOSITION,
            MetricFormat.PERCENT,
            higher_is_better=None,
        ),
        *(_pooled(key, SHOOTING) for key in _POOLED_SHOOTING),
        *(_pooled(key, PRODUCTION) for key in _POOLED_PRODUCTION),
    )
)


def roster_indicators(members: pd.DataFrame, *, team_games: float) -> pd.Series:
    """What a group of players adds up to, one value per key in :data:`ROSTER_METRICS`.

    ``members`` has one row per player on the roster with ``position_group``, ``age``
    and the player's season totals (``games_played``, ``minutes``, ``plus_minus`` and
    the box-score columns). A player with no season line has missing totals, counts as
    a player and toward a position, and adds nothing to the pooled figures.
    ``team_games`` is the number of games a team played that season.
    """
    played = members[members["minutes"].notna()]
    minutes = played["minutes"].astype("float64")

    indicators = pd.Series(index=list(ROSTER_METRICS.keys), dtype="float64")
    indicators["players"] = len(members)
    indicators["players_with_stats"] = len(played)
    for name in POSITION_GROUPS.values():
        indicators[f"{name.lower()}s"] = int((members["position_group"] == name).sum())
    indicators["age"] = f.safe_divide(
        (played["age"].astype("float64") * minutes).sum(), minutes.sum()
    )
    indicators["minutes_share"] = f.share(minutes.sum(), PLAYER_MINUTES_PER_GAME * team_games)

    if not played.empty:
        pooled = pooled_metrics(played)
        indicators[list(POOLED_KEYS)] = pooled[list(POOLED_KEYS)].astype("float64")
    return indicators


def league_reference(player_seasons: pd.DataFrame) -> pd.Series:
    """The league-wide value of each pooled indicator: every player's totals pooled.

    ``player_seasons`` is one season's regular-season lines. Indicators that describe
    the composition of a roster have no league value and are missing.
    """
    reference = pd.Series(index=list(ROSTER_METRICS.keys), dtype="float64")
    if player_seasons.empty:
        return reference
    columns = ["games_played", "minutes", "plus_minus", *BOX_SCORE_COLUMNS]
    pooled = pooled_metrics(player_seasons[columns])
    reference[list(POOLED_KEYS)] = pooled[list(POOLED_KEYS)].astype("float64")
    return reference
