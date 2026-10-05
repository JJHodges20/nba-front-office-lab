"""A roster's profile: what its players add up to in the roadmap's areas of fit.

Everything is weighted by the minutes each player plays for the roster - a real team's
players by the minutes they played for it, a built roster's by the minutes they played
in the statistics season. Roles are counted among the rotation (the ten most-used
players) and the bench (the sixth to tenth). A player with no statistics to build a
profile from counts toward ``unprofiled_share`` and toward nothing else: the other
measures are averages over the players who have one.

Nothing here is fitted. Whether any measure matters beyond the sum of the players'
impacts is :mod:`front_office.modeling.fit.evidence`'s question.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from front_office.analytics import formulas as f
from front_office.domain.archetypes import ArchetypeSet
from front_office.domain.fit import (
    MEASURE_KEYS,
    MEASURES,
    ON_COURT,
    ROTATION_SIZE,
    STARTERS,
    TOP_USAGE,
    Measure,
    Method,
)
from front_office.domain.seasons import SeasonType
from front_office.modeling.archetypes import measured
from front_office.modeling.value.features import start_years, stints

Tables = Mapping[str, pd.DataFrame]
REGULAR = SeasonType.REGULAR.value

FILLS = "fills_"
"""Prefix of the profile columns that say which roles a player fills."""
PROFILE_COLUMNS: tuple[str, ...] = (
    "season",
    "player_id",
    "season_minutes",
    "usage_pct",
    "assist_pct",
    "fg3a_per_100",
    "fg3_pct_regressed",
    "stl_per_100",
    "blk_per_100",
    "free_throw_rate",
    "turnover_pct",
    "reb_pct",
    "height_inches",
    "two_positions",
    "in_guards",
    "in_wings",
    "in_bigs",
    "impact",
    "impact_offense",
    "impact_defense",
    "wins_added",
    "projected_impact",
)
"""What a player's profile holds, before the ``fills_<archetype>`` columns."""
PROFILED = "usage_pct"
"""A member with this column missing has no profile at all."""
TEAM_COLUMNS: tuple[str, ...] = ("season", "team_id", "players", *MEASURE_KEYS)


def fills_column(archetype_key: str) -> str:
    return f"{FILLS}{archetype_key}"


def player_profiles(tables: Tables, archetypes: ArchetypeSet) -> pd.DataFrame:
    """One row per player per regular season: :data:`PROFILE_COLUMNS` and, for each
    archetype in ``archetypes``, whether the player fills it.

    Every player with a season line and possessions on the court has a profile, however
    few minutes; value columns are missing where the season has not been valued.
    """
    base = measured(tables, min_minutes=0)
    lines = tables["player_seasons"]
    lines = lines[lines["season_type"] == REGULAR].set_index(["season", "player_id"])
    at = pd.MultiIndex.from_frame(base[["season", "player_id"]])
    rows = lines.reindex(at)

    frame = base[
        [
            "season",
            "player_id",
            "usage_pct",
            "assist_pct",
            "fg3a_per_100",
            "fg3_pct_regressed",
            "stl_per_100",
            "blk_per_100",
            "impact_defense",
            "in_guards",
            "in_wings",
            "in_bigs",
        ]
    ].copy()
    # The formulas take series; these are aligned to the profile rows, not to the lines.
    fga, fta, tov = (
        pd.Series(rows[column].to_numpy(dtype="float64"), index=frame.index)
        for column in ("fga", "fta", "tov")
    )
    frame["season_minutes"] = rows["minutes"].to_numpy(dtype="float64")
    frame["free_throw_rate"] = f.free_throw_rate(fta, fga)
    frame["turnover_pct"] = f.turnover_pct(tov, fga, fta)
    frame["reb_pct"] = rows["reb_pct"].to_numpy(dtype="float64")

    known = tables["players"].set_index("player_id")
    frame["height_inches"] = frame["player_id"].map(known["height_inches"]).astype("float64")
    position = frame["player_id"].map(known["position"]).fillna("").astype("str")
    frame["two_positions"] = position.str.contains("-")

    scores = tables["player_value_scores"].set_index(["season", "player_id"])
    for column in ("impact", "impact_offense", "wins_added", "projected_impact"):
        frame[column] = scores[column].reindex(at).to_numpy(dtype="float64")

    roles = tables["player_archetypes"]
    fills = pd.DataFrame(False, index=at, columns=list(archetypes.keys))
    if not roles.empty:
        wide = roles.assign(fills=roles["fills"].astype(bool)).pivot(
            index=["season", "player_id"], columns="archetype", values="fills"
        )
        wide = wide.reindex(columns=list(archetypes.keys)).reindex(at)
        fills = wide.fillna(False).astype(bool)
    for key in archetypes.keys:
        frame[fills_column(key)] = fills[key].to_numpy()
    return frame[[*PROFILE_COLUMNS, *(fills_column(key) for key in archetypes.keys)]]


def place_among(values: pd.Series, value: float) -> tuple[float, int, float]:
    """Where ``value`` stands among ``values``: the share of them it is ahead of, ties
    counted as half, from 0 to 100; its rank from the top; and the median of ``values``."""
    below, equal = int((values < value).sum()), int((values == value).sum())
    standing = 100 * (below + 0.5 * equal) / len(values)
    rank = int((values > value).sum()) + 1
    return standing, rank, float(values.median())


def rotation_profile(members: pd.DataFrame, *, team_minutes: float) -> pd.Series:
    """What a group of players adds up to: one value per key in :data:`MEASURE_KEYS`.

    ``members`` has one row per player with the profile columns (all missing for a player
    who has no profile) and ``minutes``, the minutes the player plays for this roster.
    ``team_minutes`` is the player-minutes a team has to fill in the season: five times
    the team's game minutes.
    """
    out = pd.Series(np.nan, index=list(MEASURE_KEYS), dtype="float64")
    minutes = pd.to_numeric(members["minutes"], errors="coerce").fillna(0.0)
    playing = members.loc[minutes > 0].assign(minutes=minutes[minutes > 0])
    playing = playing.sort_values("minutes", ascending=False, kind="stable")
    total = float(playing["minutes"].sum())
    out["minutes_covered"] = f.safe_divide(total, team_minutes)
    if playing.empty:
        return out
    profiled = playing[PROFILED].notna() if PROFILED in playing else pd.Series(False, playing.index)
    out["unprofiled_share"] = float(playing.loc[~profiled, "minutes"].sum()) / total
    rotation = playing.head(ROTATION_SIZE)
    bench = rotation.iloc[STARTERS:]
    for item in MEASURES:
        if item.method in (Method.COVERED, Method.UNPROFILED):
            continue
        over = bench if item.bench else playing
        if item.method is Method.COUNT:
            out[item.key] = _count(bench if item.bench else rotation, item)
        elif item.method is Method.MEAN:
            out[item.key] = _weighted_mean(over, item.source)
        elif item.method is Method.LINEUP:
            out[item.key] = ON_COURT * _weighted_mean(over, item.source)
        elif item.method is Method.SHARE:
            out[item.key] = _minutes_share(over, item.source)
        elif item.method is Method.TOP:
            values = pd.to_numeric(rotation[item.source], errors="coerce").dropna()
            out[item.key] = float(values.nlargest(TOP_USAGE).sum()) if len(values) else np.nan
        elif item.method is Method.STAR:
            values = pd.to_numeric(rotation[item.source], errors="coerce").dropna()
            positive = float(values[values > 0].sum())
            out[item.key] = float(values.max()) / positive if positive > 0 else np.nan
    return out


def _count(frame: pd.DataFrame, item: Measure) -> float:
    counted = pd.Series(False, index=frame.index)
    for role in item.roles:
        column = fills_column(role)
        if column in frame:
            counted |= frame[column].fillna(False).astype(bool)
    if item.group is not None and item.group in frame:
        counted |= frame[item.group].fillna(False).astype(bool)
    return float(counted.sum())


def _weighted_mean(frame: pd.DataFrame, column: str | None) -> float:
    if column is None or column not in frame:
        return np.nan
    values = pd.to_numeric(frame[column], errors="coerce")
    weight = frame["minutes"].where(values.notna(), 0.0)
    return float(f.safe_divide((values.fillna(0.0) * weight).sum(), weight.sum()))


def _minutes_share(frame: pd.DataFrame, column: str | None) -> float:
    """Share of the profiled minutes played by players for whom ``column`` is true."""
    if column is None or column not in frame:
        return np.nan
    known = frame[column].notna() & frame[PROFILED].notna()
    flagged = frame[column].fillna(False).astype(bool) & known
    return float(
        f.safe_divide(frame.loc[flagged, "minutes"].sum(), frame.loc[known, "minutes"].sum())
    )


def team_profiles(tables: Tables, archetypes: ArchetypeSet, *, lag: int = 0) -> pd.DataFrame:
    """Every real team-season's profile: :data:`TEAM_COLUMNS`.

    Each player is weighted by the minutes played for the team that season. With ``lag``
    the profiles come from that many seasons earlier - what was known of the players when
    the roster was put together - while the minutes stay the season's own.
    """
    played = stints(tables["player_seasons"], tables["player_game_logs"], tables["team_seasons"])
    if played.empty:
        return pd.DataFrame(columns=list(TEAM_COLUMNS))
    profiles = player_profiles(tables, archetypes)
    profiles = profiles.assign(start=start_years(profiles["season"]) + lag).drop(columns="season")
    profiles = profiles.set_index(["start", "player_id"])
    teams = tables["team_seasons"].set_index(["season", "team_id"])["minutes"].astype("float64")
    to_fill = teams * ON_COURT

    rows = []
    for (season, team_id), group in played.groupby(["season", "team_id"], sort=True):
        start = int(group["start"].iloc[0])
        at = pd.MultiIndex.from_arrays(
            [np.full(len(group), start), group["player_id"].to_numpy()],
            names=["start", "player_id"],
        )
        members = profiles.reindex(at).reset_index(drop=True)
        members["minutes"] = group["minutes"].to_numpy(dtype="float64")
        profile = rotation_profile(
            members, team_minutes=float(to_fill.get((season, team_id), np.nan))
        )
        rows.append(
            {
                "season": season,
                "team_id": int(team_id),
                "players": int((group["minutes"] > 0).sum()),
                **profile.to_dict(),
            }
        )
    return pd.DataFrame(rows, columns=list(TEAM_COLUMNS))
