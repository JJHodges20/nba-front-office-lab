"""Normalise stats.nba.com team datasets into the team tables."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from front_office.domain.schema import conform_frame
from front_office.domain.snapshots import Snapshot
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS
from front_office.domain.tables.teams import TEAM_GAMES, TEAM_SEASONS, TEAMS
from front_office.processing.nba_stats import convert
from front_office.processing.nba_stats.resultsets import (
    PayloadError,
    result_set_frame,
    snapshot_season,
    snapshot_season_type,
)

# Source column for each box-score statistic.
_BOX_SOURCE = {name: name.upper() for name in BOX_SCORE_COLUMNS}
_OUTCOME_COLUMNS = (
    "made_play_in",
    "made_playoffs",
    "playoff_round_reached",
    "playoff_series_won",
    "playoff_wins",
    "playoff_losses",
    "made_conference_finals",
    "made_finals",
    "won_championship",
)


def build_teams(team_years: Snapshot, standings: Snapshot) -> pd.DataFrame:
    """The current franchises: identity from the newest standings, history from team years."""
    current = result_set_frame(
        standings, required=("TeamID", "TeamCity", "TeamName", "Conference", "Division")
    )
    years = result_set_frame(team_years, required=("TEAM_ID", "MIN_YEAR", "ABBREVIATION"))

    frame = pd.DataFrame(
        {
            "team_id": convert.integers(current["TeamID"]),
            "city": convert.text(current["TeamCity"]),
            "nickname": convert.text(current["TeamName"]),
            "conference": convert.text(current["Conference"]),
            "division": convert.text(current["Division"]),
        }
    )
    frame["full_name"] = frame["city"] + " " + frame["nickname"]
    history = pd.DataFrame(
        {
            "team_id": convert.integers(years["TEAM_ID"]),
            "abbreviation": convert.text(years["ABBREVIATION"]),
            "first_season_year": convert.integers(years["MIN_YEAR"]),
        }
    )
    frame = frame.merge(history, on="team_id", how="left", validate="one_to_one")
    return conform_frame(frame[list(TEAMS.column_names)].sort_values("team_id"), TEAMS)


def build_team_games(logs: Sequence[Snapshot], notes: list[str] | None = None) -> pd.DataFrame:
    """Team box scores for every game in the given game-log snapshots.

    Each game appears twice in the source, once per team. The two rows are paired to
    give every row its opponent and the opponent's score.

    A scheduled game that was never played (the source lists it with no result and no
    minutes) is left out, and said so in ``notes``.
    """
    frames = [_team_game_rows(snapshot) for snapshot in logs]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return TEAM_GAMES.empty_frame()
    rows = pd.concat(frames, ignore_index=True)

    never_played = rows["won"].isna() & (rows["minutes"] == 0)
    if never_played.any():
        cancelled = sorted(rows.loc[never_played, "game_id"].unique())
        if notes is not None:
            notes.append(
                f"{len(cancelled)} scheduled game(s) never played and left out: "
                f"{', '.join(cancelled)}"
            )
        rows = rows[~never_played]
        if rows.empty:
            return TEAM_GAMES.empty_frame()

    sizes = rows.groupby("game_id")["team_id"].transform("size")
    if (sizes != 2).any():
        odd = rows.loc[sizes != 2, "game_id"].unique()[:5].tolist()
        raise PayloadError(f"games without exactly two team rows: {odd}")

    other = rows[["game_id", "team_id", "pts", "is_home"]].rename(
        columns={"team_id": "opponent_team_id", "pts": "opp_pts", "is_home": "opponent_is_home"}
    )
    paired = rows.merge(other, on="game_id")
    paired = paired[paired["team_id"] != paired["opponent_team_id"]]
    if len(paired) != len(rows):
        raise PayloadError("a game lists the same team twice")

    both_home = paired["is_home"] & paired["opponent_is_home"]
    if both_home.any():
        games = sorted(paired.loc[both_home, "game_id"].unique())[:5]
        raise PayloadError(f"games in which both teams are listed as the home team: {games}")
    # The source marks both teams as visitors when a game is played at a neutral site
    # (international games, the in-season tournament's final rounds).
    paired["is_neutral_site"] = ~paired["is_home"] & ~paired["opponent_is_home"]

    paired = paired.sort_values(["game_date", "game_id", "team_id"])
    return conform_frame(paired[list(TEAM_GAMES.column_names)], TEAM_GAMES)


def _team_game_rows(snapshot: Snapshot) -> pd.DataFrame:
    season = snapshot_season(snapshot)
    season_type = snapshot_season_type(snapshot)
    source = result_set_frame(
        snapshot,
        required=("TEAM_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "WL", "MIN", *_BOX_SOURCE.values()),
    )
    frame = pd.DataFrame(
        {
            "game_id": convert.text(source["GAME_ID"]),
            "team_id": convert.integers(source["TEAM_ID"]),
            "season": season.label,
            "season_type": season_type.value,
            "game_date": convert.dates(source["GAME_DATE"], format="%Y-%m-%d"),
            "is_home": home_flags(source["MATCHUP"]),
            "won": convert.flags(source["WL"], true="W", false="L"),
            "minutes": convert.integers(source["MIN"]),
        }
    )
    for column, source_column in _BOX_SOURCE.items():
        frame[column] = convert.integers(source[source_column])
    return frame


def home_flags(matchups: pd.Series) -> pd.Series:
    """Whether each matchup string ("BOS vs. NYK" / "BOS @ NYK") is a home game."""
    cleaned = convert.text(matchups)
    home = cleaned.map(lambda value: isinstance(value, str) and " vs. " in value)
    away = cleaned.map(lambda value: isinstance(value, str) and " @ " in value)
    unknown = ~(home ^ away)
    if unknown.any():
        examples = sorted({repr(value) for value in cleaned[unknown]})[:5]
        raise PayloadError(f"unrecognised matchup text: {examples}")
    return home.astype(bool)


def season_abbreviations(regular_season_logs: Snapshot) -> dict[int, str]:
    """Each team's abbreviation as it was that season (from its most recent game)."""
    source = result_set_frame(
        regular_season_logs, required=("TEAM_ID", "TEAM_ABBREVIATION", "GAME_DATE")
    )
    if source.empty:
        return {}
    frame = pd.DataFrame(
        {
            "team_id": convert.integers(source["TEAM_ID"]),
            "abbreviation": convert.text(source["TEAM_ABBREVIATION"]),
            "game_date": convert.text(source["GAME_DATE"]),
        }
    ).sort_values("game_date")
    latest = frame.groupby("team_id")["abbreviation"].last()
    return {int(team_id): abbreviation for team_id, abbreviation in latest.items()}


def build_team_seasons(
    *,
    base: Snapshot,
    advanced: Snapshot,
    opponent: Snapshot,
    standings: Snapshot,
    regular_season_logs: Snapshot,
    outcomes: pd.DataFrame | None = None,
    notes: list[str] | None = None,
) -> pd.DataFrame:
    """One season's team table: totals, opponent totals, league ratings and outcomes.

    ``outcomes`` comes from :func:`front_office.processing.nba_stats.playoffs.
    postseason_outcomes`; when it is ``None`` the outcome columns are left null.

    Totals are stored as the league publishes them. The rare published total that is
    not a whole number is rounded, and reported in ``notes``.
    """
    season = snapshot_season(base)
    for other in (advanced, opponent, standings, regular_season_logs):
        if snapshot_season(other) != season:
            raise PayloadError(f"{other.describe()} does not belong to season {season.label}")

    totals = result_set_frame(
        base, required=("TEAM_ID", "TEAM_NAME", "GP", "W", "L", "MIN", *_BOX_SOURCE.values())
    )
    if totals.empty:
        # The season has not started: no team has played a game.
        return TEAM_SEASONS.empty_frame()
    ratings = result_set_frame(
        advanced, required=("TEAM_ID", "POSS", "PACE", "OFF_RATING", "DEF_RATING", "NET_RATING")
    )
    allowed = result_set_frame(
        opponent, required=("TEAM_ID", *(f"OPP_{name}" for name in _BOX_SOURCE.values()))
    )
    table = result_set_frame(
        standings, required=("TeamID", "Conference", "Division", "PlayoffRank")
    )

    frame = pd.DataFrame(
        {
            "season": season.label,
            "team_id": convert.integers(totals["TEAM_ID"]),
            "team_name": convert.text(totals["TEAM_NAME"]),
            "games_played": convert.integers(totals["GP"]),
            "wins": convert.integers(totals["W"]),
            "losses": convert.integers(totals["L"]),
            "minutes": convert.floats(totals["MIN"]),
        }
    )
    rounded: dict[str, int] = {}
    for column, source_column in _BOX_SOURCE.items():
        frame[column], count = convert.rounded_counts(totals[source_column])
        if count:
            rounded[source_column] = count

    against = pd.DataFrame({"team_id": convert.integers(allowed["TEAM_ID"])})
    for column, source_column in _BOX_SOURCE.items():
        against[f"opp_{column}"], count = convert.rounded_counts(allowed[f"OPP_{source_column}"])
        if count:
            rounded[f"OPP_{source_column}"] = count
    if rounded and notes is not None:
        columns = ", ".join(f"{column} ({count})" for column, count in rounded.items())
        notes.append(f"published totals that were not whole numbers were rounded: {columns}")

    measured = pd.DataFrame(
        {
            "team_id": convert.integers(ratings["TEAM_ID"]),
            "possessions": convert.integers(ratings["POSS"]),
            "pace": convert.floats(ratings["PACE"]),
            "off_rating": convert.floats(ratings["OFF_RATING"]),
            "def_rating": convert.floats(ratings["DEF_RATING"]),
            "net_rating": convert.floats(ratings["NET_RATING"]),
        }
    )
    placed = pd.DataFrame(
        {
            "team_id": convert.integers(table["TeamID"]),
            "conference": convert.text(table["Conference"]),
            "division": convert.text(table["Division"]),
            "conference_rank": convert.integers(table["PlayoffRank"]),
        }
    )

    teams = set(frame["team_id"])
    for label, part in (("advanced", measured), ("opponent", against), ("standings", placed)):
        if set(part["team_id"]) != teams:
            raise PayloadError(
                f"{season.label}: the {label} dataset covers different teams from the base totals"
            )
        frame = frame.merge(part, on="team_id", how="left", validate="one_to_one")

    abbreviations = season_abbreviations(regular_season_logs)
    frame["team_abbreviation"] = frame["team_id"].map(abbreviations).astype(object)

    if outcomes is None:
        for column in _OUTCOME_COLUMNS:
            frame[column] = None
    else:
        if set(outcomes["team_id"]) != teams:
            raise PayloadError(f"{season.label}: postseason outcomes cover different teams")
        frame = frame.merge(
            outcomes[["team_id", *_OUTCOME_COLUMNS]],
            on="team_id",
            how="left",
            validate="one_to_one",
        )

    return conform_frame(
        frame[list(TEAM_SEASONS.column_names)].sort_values("team_id"), TEAM_SEASONS
    )
