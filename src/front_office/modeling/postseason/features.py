"""What the postseason model reads about a team-season, and the games and series it is
fitted and tested on.

Everything a team is described by here is known before its first playoff game: its
regular-season record and net rating, the value model's impact for the players who
finished the season with it, and how many playoff games those players had played in
the seasons before. Outcomes come from ``team_seasons`` and ``playoff_results``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from front_office.domain.postseason import PostseasonSpec, home_pattern
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.stages import BRACKET_STAGE_KEYS

FEATURE_TABLES: tuple[str, ...] = (
    "team_seasons",
    "team_games",
    "playoff_results",
    "player_seasons",
    "player_value_scores",
    "player_game_logs",
)
ON_COURT = 5
REGULAR = SeasonType.REGULAR.value
PLAYOFFS = SeasonType.PLAYOFFS.value
GAPS: tuple[str, ...] = ("net_rating", "top_players", "best_player", "experience", "win_pct")
"""Team measures a series is described by as the gap between its sides."""
TEAM_COLUMNS: tuple[str, ...] = (
    "season",
    "start_year",
    "team_id",
    "conference",
    "conference_rank",
    "games_played",
    "wins",
    "losses",
    "win_pct",
    "net_rating",
    "top_players",
    "best_player",
    "experience",
    "decided",
    "round_reached",
    *BRACKET_STAGE_KEYS,
)
Tables = dict[str, pd.DataFrame]


def team_features(tables: Tables, spec: PostseasonSpec) -> pd.DataFrame:
    """One row per team-season: :data:`TEAM_COLUMNS`, oldest season first.

    ``decided`` says whether the postseason is over; the stage flags are false until it
    is. ``top_players`` and ``experience`` are missing for a team none of whose players
    the value model scored, or whose players have no history on record.
    """
    teams = tables["team_seasons"].reset_index(drop=True)
    frame = pd.DataFrame(
        {
            "season": teams["season"].astype(str),
            "start_year": teams["season"]
            .map(lambda label: Season.parse(label).start_year)
            .astype("int64"),
            "team_id": teams["team_id"].astype("int64"),
            "conference": teams["conference"].astype(str),
            "conference_rank": teams["conference_rank"].astype("float64"),
            "games_played": teams["games_played"].astype("int64"),
            "wins": teams["wins"].astype("int64"),
            "losses": teams["losses"].astype("int64"),
            "net_rating": teams["net_rating"].astype("float64"),
        }
    )
    frame["win_pct"] = frame["wins"] / frame["games_played"].where(frame["games_played"] > 0)
    quality = _player_quality(tables, spec)
    frame = frame.merge(quality, on=["season", "team_id"], how="left")
    frame["decided"] = teams["made_playoffs"].notna().to_numpy()
    rounds = teams["playoff_round_reached"].fillna(0).astype("int64")
    frame["round_reached"] = rounds.to_numpy()
    flags = {
        "made_playoffs": teams["made_playoffs"].fillna(False).astype(bool),
        "won_a_round": rounds >= 2,
        "made_conference_finals": teams["made_conference_finals"].fillna(False).astype(bool),
        "made_finals": teams["made_finals"].fillna(False).astype(bool),
        "won_championship": teams["won_championship"].fillna(False).astype(bool),
    }
    for key in BRACKET_STAGE_KEYS:
        frame[key] = (flags[key] & frame["decided"]).to_numpy()
    ordered = frame.sort_values(["start_year", "team_id"]).reset_index(drop=True)
    return ordered[list(TEAM_COLUMNS)]


def keyed(features: pd.DataFrame) -> pd.DataFrame:
    """The features indexed by season and team."""
    return features.set_index(["season", "team_id"])


def _player_quality(tables: Tables, spec: PostseasonSpec) -> pd.DataFrame:
    """Each team-season's top-player quality, best player and experience from the players
    who finished the regular season with it."""
    lines = tables["player_seasons"]
    lines = lines[lines["season_type"] == REGULAR][["player_id", "season", "team_id", "minutes"]]
    lines = lines.assign(
        player_id=lines["player_id"].astype("int64"),
        team_id=lines["team_id"].astype("int64"),
        minutes=lines["minutes"].astype("float64"),
    )
    scores = tables["player_value_scores"][["player_id", "season", "impact"]]
    scores = scores.assign(player_id=scores["player_id"].astype("int64"))
    valued = lines.merge(scores, on=["player_id", "season"], how="inner").dropna(subset=["impact"])
    if valued.empty:
        # No player valued: every team's quality is unknown, and the frame must still key.
        nobody = pd.MultiIndex.from_arrays([[], []], names=["season", "team_id"])
        quality = pd.DataFrame(
            {"top_players": pd.Series(dtype="float64"), "best_player": pd.Series(dtype="float64")},
            index=nobody,
        )
    else:
        ranked = valued.sort_values("impact", ascending=False)
        by_team = ranked.groupby(["season", "team_id"])["impact"]
        top = by_team.apply(lambda impacts: impacts.head(spec.top_players).mean())
        best = by_team.first()
        quality = pd.DataFrame({"top_players": top, "best_player": best})

    experience = _experience(lines, tables["player_game_logs"], spec)
    quality = quality.join(experience, how="outer").reset_index()
    return quality.assign(
        season=quality["season"].astype(str), team_id=quality["team_id"].astype("int64")
    )


def _experience(lines: pd.DataFrame, logs: pd.DataFrame, spec: PostseasonSpec) -> pd.Series:
    """Playoff games the team's players had played in the previous seasons, weighted by
    each player's share of the team's regular-season minutes and scaled to five on the
    floor: games of experience per player on the court."""
    playoff_logs = logs[logs["season_type"] == PLAYOFFS]
    counts = (
        playoff_logs.groupby(["player_id", "season"])
        .size()
        .rename("games")
        .reset_index()
        .assign(player_id=lambda frame: frame["player_id"].astype("int64"))
    )
    # Cast, so that a season without playoff logs (or without players) still keys on an
    # integer year rather than on an empty text column.
    counts["start_year"] = (
        counts["season"].map(lambda label: Season.parse(label).start_year).astype("int64")
    )
    players = lines.assign(
        start_year=lines["season"].map(lambda label: Season.parse(label).start_year).astype("int64")
    )
    prior = np.zeros(len(players))
    for lag in range(1, spec.experience_seasons + 1):
        shifted = counts.assign(start_year=counts["start_year"] + lag)
        merged = players.merge(
            shifted[["player_id", "start_year", "games"]],
            on=["player_id", "start_year"],
            how="left",
        )
        prior += merged["games"].fillna(0).to_numpy(dtype="float64")
    players = players.assign(prior=prior)
    team_minutes = players.groupby(["season", "team_id"])["minutes"].transform("sum")
    players["weighted"] = (
        players["prior"] * players["minutes"] / team_minutes.where(team_minutes > 0)
    )
    return (players.groupby(["season", "team_id"])["weighted"].sum() * ON_COURT).rename(
        "experience"
    )


def head_to_head(team_games: pd.DataFrame) -> dict[tuple[str, int, int], int]:
    """Regular-season wins of each team over each opponent: ``(season, team, opponent)``."""
    regular = team_games[team_games["season_type"] == REGULAR]
    wins = regular[regular["won"].fillna(False).astype(bool)]
    counted = wins.groupby(["season", "team_id", "opponent_team_id"]).size()
    return {
        (str(season), int(team), int(opponent)): int(count)
        for (season, team, opponent), count in counted.items()
    }


def playoff_games(tables: Tables, features: pd.DataFrame, spec: PostseasonSpec) -> pd.DataFrame:
    """One row per playoff game from the home side's point of view: ``season``,
    ``start_year``, ``home`` (0 on neutral ground), the gaps in :data:`GAPS` as
    ``<measure>_diff``, and ``home_won``. Games whose sides lack a measure are kept with
    that gap missing; the fit drops what it cannot use."""
    games = tables["team_games"]
    games = games[(games["season_type"] == PLAYOFFS) & games["is_home"].astype(bool)]
    games = games[games["won"].notna()]
    frame = pd.DataFrame(
        {
            "season": games["season"].astype(str).to_numpy(),
            "game_id": games["game_id"].astype(str).to_numpy(),
            "team_id": games["team_id"].astype("int64").to_numpy(),
            "opponent_team_id": games["opponent_team_id"].astype("int64").to_numpy(),
            "home_won": games["won"].astype(bool).astype("float64").to_numpy(),
        }
    )
    frame["start_year"] = frame["season"].map(lambda label: Season.parse(label).start_year)
    neutral = frame["season"].map(spec.is_neutral).to_numpy(dtype=bool)
    frame["home"] = np.where(neutral, 0.0, 1.0)
    _add_gaps(frame, features, "team_id", "opponent_team_id")
    return frame.sort_values(["start_year", "game_id"]).reset_index(drop=True)


def series_table(tables: Tables, features: pd.DataFrame, spec: PostseasonSpec) -> pd.DataFrame:
    """One row per decided series: the home-court side first (``team_a_id``), ``a_won``,
    the format's ``pattern`` and whether the ground was ``neutral``, the gaps."""
    series = tables["playoff_results"]
    series = series[series["is_complete"].astype(bool) & series["winner_team_id"].notna()]
    frame = pd.DataFrame(
        {
            "season": series["season"].astype(str).to_numpy(),
            "series_id": series["series_id"].astype(str).to_numpy(),
            "round": series["round"].astype("int64").to_numpy(),
            "best_of": series["best_of"].astype("int64").to_numpy(),
            "team_a_id": series["team_a_id"].astype("int64").to_numpy(),
            "team_b_id": series["team_b_id"].astype("int64").to_numpy(),
            "team_a_wins": series["team_a_wins"].astype("int64").to_numpy(),
            "team_b_wins": series["team_b_wins"].astype("int64").to_numpy(),
            "a_won": (series["winner_team_id"] == series["team_a_id"]).astype("float64").to_numpy(),
        }
    )
    frame["start_year"] = frame["season"].map(lambda label: Season.parse(label).start_year)
    frame["pattern"] = [
        pattern_for(spec, int(playoff_round), season, int(best_of))
        for playoff_round, season, best_of in zip(
            frame["round"], frame["season"], frame["best_of"], strict=True
        )
    ]
    frame["neutral"] = frame["season"].map(spec.is_neutral).to_numpy(dtype=bool)
    _add_gaps(frame, features, "team_a_id", "team_b_id")
    return frame.sort_values(["start_year", "round", "series_id"]).reset_index(drop=True)


def pattern_for(spec: PostseasonSpec, playoff_round: int, season: str, best_of: int) -> str:
    """The format of a series: the specification's for that round and season, unless the
    series was scheduled for another length, when the shortest sensible format of that
    length stands in."""
    pattern = spec.pattern_for(playoff_round, season)
    if len(home_pattern(pattern)) == best_of:
        return pattern
    return "2-2-1" if best_of == 5 else spec.default_pattern


def _add_gaps(frame: pd.DataFrame, features: pd.DataFrame, mine: str, theirs: str) -> None:
    table = keyed(features)
    for measure in GAPS:
        values = table[measure]
        ours = values.reindex(pd.MultiIndex.from_arrays([frame["season"], frame[mine]]))
        others = values.reindex(pd.MultiIndex.from_arrays([frame["season"], frame[theirs]]))
        frame[f"{measure}_diff"] = ours.to_numpy() - others.to_numpy()
