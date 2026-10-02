"""What the value model sees of a player in one season.

Every feature is a rate per 100 possessions the player was on the court for, measured
against the league of the same season, so that a season of the 1990s and a season of
the 2020s are described on the same scale and an average player is zero throughout.

The model never sees a raw total, a per-game figure or a shooting percentage: totals
reward minutes, per-game figures reward pace, and a percentage says nothing about how
often the shot is taken.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from front_office.analytics import formulas as f
from front_office.analytics.players import team_minutes
from front_office.analytics.teams import league_averages, team_season_metrics
from front_office.domain.seasons import SeasonType

REGULAR = SeasonType.REGULAR.value

EFFICIENCY = "efficiency"
CREATION = "creation"
SHOOTING = "shooting"
REBOUNDING = "rebounding"
BALL_SECURITY = "ball_security"
DEFENSIVE_ACTIVITY = "defensive_activity"
ON_COURT = "on_court"
TEAM_CONTEXT = "team_context"


@dataclass(frozen=True, slots=True)
class Component:
    """A group of features that is shown, and can be removed, as one thing."""

    key: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class Feature:
    key: str
    component: str
    label: str
    description: str


COMPONENTS: tuple[Component, ...] = (
    Component(
        EFFICIENCY,
        "Scoring efficiency",
        "Points beyond what an average scorer gets from the same shots and free throws.",
    ),
    Component(
        CREATION,
        "Creation",
        "How much offense runs through the player: scoring attempts, assists, free throws.",
    ),
    Component(
        SHOOTING,
        "Spacing",
        "Three-point attempts. Accuracy is counted under scoring efficiency; this is the "
        "worth of being a threat a defense has to follow.",
    ),
    Component(REBOUNDING, "Rebounding", "Offensive and defensive rebounds."),
    Component(BALL_SECURITY, "Ball security", "Turnovers."),
    Component(
        DEFENSIVE_ACTIVITY,
        "Defensive activity",
        "Steals, blocks and fouls: the part of defense a box score records.",
    ),
    Component(
        ON_COURT,
        "On-court results",
        "How the team scored and defended with the player on the court, against the same "
        "team over the whole season.",
    ),
    Component(
        TEAM_CONTEXT,
        "Team results",
        "How the player's teams scored and defended against the league. Whatever a team "
        "does well that no box score records is shared among the players who were there.",
    ),
)

_RATE = "per 100 possessions on the court, against the league average"

FEATURES: tuple[Feature, ...] = (
    Feature(
        "score_eff",
        EFFICIENCY,
        "Scoring efficiency",
        "Points per 100 possessions beyond what a league-average scorer gets from the "
        "same number of shots and free throws.",
    ),
    Feature("score_vol", CREATION, "Scoring volume", f"Shots and trips to the line {_RATE}."),
    Feature("ast", CREATION, "Assists", f"Assists {_RATE}."),
    Feature("fta", CREATION, "Free throw attempts", f"Free throw attempts {_RATE}."),
    Feature("fg3a", SHOOTING, "Three-point attempts", f"Three-point attempts {_RATE}."),
    Feature("oreb", REBOUNDING, "Offensive rebounds", f"Offensive rebounds {_RATE}."),
    Feature("dreb", REBOUNDING, "Defensive rebounds", f"Defensive rebounds {_RATE}."),
    Feature("tov", BALL_SECURITY, "Turnovers", f"Turnovers {_RATE}."),
    Feature("stl", DEFENSIVE_ACTIVITY, "Steals", f"Steals {_RATE}."),
    Feature("blk", DEFENSIVE_ACTIVITY, "Blocks", f"Blocks {_RATE}."),
    Feature("pf", DEFENSIVE_ACTIVITY, "Fouls", f"Personal fouls {_RATE}."),
    Feature(
        "rel_off",
        ON_COURT,
        "On-court offense",
        "The team's offensive rating with the player on the court, less the same team's "
        "over the whole season.",
    ),
    Feature(
        "rel_def",
        ON_COURT,
        "On-court defense",
        "The team's defensive rating over the whole season, less the same team's with "
        "the player on the court: positive when the team defends better with the player.",
    ),
    Feature(
        "team_off",
        TEAM_CONTEXT,
        "Team offense",
        "Offensive rating, against the league, of the teams played for.",
    ),
    Feature(
        "team_def",
        TEAM_CONTEXT,
        "Team defense",
        "Defensive rating, against the league, of the teams played for: positive is better.",
    ),
)
FEATURE_KEYS: tuple[str, ...] = tuple(feature.key for feature in FEATURES)
COMPONENT_KEYS: tuple[str, ...] = tuple(component.key for component in COMPONENTS)

# The single numbers a player is often judged by: what the model has to beat.
ON_COURT_NET = "on_court_net"
PLUS_MINUS = "plus_minus_100"
PIE = "pie"
RIVAL_KEYS: tuple[str, ...] = (ON_COURT_NET, PLUS_MINUS, PIE)
AVERAGE_PIE = 0.1
"""Ten players share a game's events, so an average player's PIE is a tenth."""

_COUNTED = ("ast", "fta", "fg3a", "oreb", "dreb", "tov", "stl", "blk", "pf")

STINT_COLUMNS = ("season", "start", "team_id", "player_id", "minutes", "share", "team_games")


def component(key: str) -> Component:
    for candidate in COMPONENTS:
        if candidate.key == key:
            return candidate
    raise KeyError(f"no component named {key!r}")


def features_of(component_key: str) -> tuple[str, ...]:
    return tuple(feature.key for feature in FEATURES if feature.component == component_key)


def start_years(seasons: pd.Series) -> pd.Series:
    """The calendar year each season label starts in: ``2025-26`` is 2025."""
    return seasons.str.slice(0, 4).astype("int64")


def stints(
    player_seasons: pd.DataFrame, player_game_logs: pd.DataFrame, team_seasons: pd.DataFrame
) -> pd.DataFrame:
    """Who played for whom in each regular season, and for what share of the minutes.

    ``share`` is the player's minutes over the team's game minutes, so a player who
    never left the floor has 1 and a team's players add up to 5. It is missing where
    the team's season is not on record. One row per player per team per season:
    :data:`STINT_COLUMNS`.
    """
    seasons = player_seasons[player_seasons["season_type"] == REGULAR]
    logs = player_game_logs[player_game_logs["season_type"] == REGULAR]
    played = team_minutes(seasons, logs)
    teams = team_seasons[["season", "team_id", "minutes", "games_played"]].rename(
        columns={"minutes": "team_minutes", "games_played": "team_games"}
    )
    frame = played.merge(teams, on=["season", "team_id"], how="left")
    frame["share"] = f.safe_divide(frame["minutes"], frame["team_minutes"])
    frame["team_games"] = frame["team_games"].astype("float64")
    frame["start"] = start_years(frame["season"])
    return frame[list(STINT_COLUMNS)]


def season_features(
    player_seasons: pd.DataFrame, team_seasons: pd.DataFrame, played: pd.DataFrame
) -> pd.DataFrame:
    """One row per player per regular season: playing time, age and every feature.

    ``played`` is :func:`stints`. A player with no possessions on record has no
    evidence either way: every feature is zero and ``evidence_minutes`` is zero, so the
    model falls back on what it assumes of any player in that role.
    """
    seasons = player_seasons[player_seasons["season_type"] == REGULAR].reset_index(drop=True)
    frame = seasons[["season", "player_id"]].copy()
    frame["start"] = start_years(frame["season"])
    for column in ("minutes", "games_played", "age"):
        frame[column] = seasons[column].astype("float64")

    possessions = seasons["possessions"].astype("float64")
    possessions = possessions.where(possessions > 0)
    seen = possessions.notna()
    frame["evidence_minutes"] = frame["minutes"].where(seen, 0.0)
    frame["minutes_per_game"] = f.safe_divide(frame["minutes"], frame["games_played"]).fillna(0.0)
    frame["mpg_centred"] = frame["minutes_per_game"] - weighted_mean_by_season(
        frame, "minutes_per_game", "minutes"
    )

    attempts = f.scoring_attempts(seasons["fga"], seasons["fta"])
    rates = pd.DataFrame(
        {column: f.per_100(seasons[column], possessions) for column in ("pts", *_COUNTED)}
    )
    rates["attempts"] = f.per_100(attempts, possessions)
    pooled = (
        seasons[["pts", *_COUNTED]]
        .astype("float64")
        .assign(attempts=attempts, possessions=possessions)[seen]
        .groupby(frame.loc[seen, "season"])
        .sum()
    )
    league = pd.DataFrame(
        {
            column: f.per_100(pooled[column], pooled["possessions"])
            for column in ("pts", "attempts", *_COUNTED)
        }
    ).reindex(frame["season"])
    league.index = frame.index
    points_per_attempt = f.safe_divide(league["pts"], league["attempts"])
    frame["score_eff"] = rates["pts"] - points_per_attempt * rates["attempts"]
    frame["score_vol"] = rates["attempts"] - league["attempts"]
    for column in _COUNTED:
        frame[column] = rates[column] - league[column]

    context = _team_context(team_seasons, played).reindex(
        pd.MultiIndex.from_frame(frame[["season", "player_id"]])
    )
    frame["team_off"] = context["team_off"].to_numpy()
    frame["team_def"] = context["team_def"].to_numpy()
    league_rating = frame["season"].map(league_averages(team_seasons)["off_rating"])
    on_court_off = seasons["off_rating"].astype("float64") - league_rating
    on_court_def = league_rating - seasons["def_rating"].astype("float64")
    frame["rel_off"] = on_court_off - frame["team_off"]
    frame["rel_def"] = on_court_def - frame["team_def"]

    frame[ON_COURT_NET] = seasons["net_rating"].astype("float64")
    frame[PLUS_MINUS] = f.per_100(seasons["plus_minus"], possessions)
    frame[PIE] = seasons["player_impact_estimate"].astype("float64") - AVERAGE_PIE

    measured = [*FEATURE_KEYS, *RIVAL_KEYS]
    frame[measured] = frame[measured].where(seen, 0.0).fillna(0.0)
    return frame


def weighted_mean_by_season(frame: pd.DataFrame, column: str, weight: str) -> pd.Series:
    """Each row's season average of ``column``, weighted by ``weight``; zero if unweighted."""
    weighted = (frame[column] * frame[weight]).groupby(frame["season"]).transform("sum")
    total = frame[weight].groupby(frame["season"]).transform("sum")
    return f.safe_divide(weighted, total).fillna(0.0)


def _team_context(team_seasons: pd.DataFrame, played: pd.DataFrame) -> pd.DataFrame:
    """Relative ratings of the teams each player appeared for, weighted by minutes there."""
    metrics = team_season_metrics(team_seasons)[
        ["season", "team_id", "rel_off_rating", "rel_def_rating"]
    ]
    joined = played.merge(metrics, on=["season", "team_id"], how="left")
    known = joined["rel_off_rating"].notna() & joined["rel_def_rating"].notna()
    weight = joined["minutes"].where(known, 0.0)
    sums = (
        pd.DataFrame(
            {
                "season": joined["season"],
                "player_id": joined["player_id"],
                "off": (joined["rel_off_rating"] * weight).fillna(0.0),
                "def": (joined["rel_def_rating"] * weight).fillna(0.0),
                "weight": weight,
            }
        )
        .groupby(["season", "player_id"])[["off", "def", "weight"]]
        .sum()
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        return pd.DataFrame(
            {
                "team_off": f.safe_divide(sums["off"], sums["weight"]).fillna(0.0),
                "team_def": f.safe_divide(sums["def"], sums["weight"]).fillna(0.0),
            }
        )
