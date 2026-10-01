"""Normalise stats.nba.com player datasets into the player tables."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from front_office.domain.schema import conform_frame
from front_office.domain.snapshots import Snapshot
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS
from front_office.domain.tables.players import (
    PLAYER_GAME_LOGS,
    PLAYER_ON_OFF,
    PLAYER_SEASONS,
    PLAYERS,
    TEAM_ROSTERS,
)
from front_office.processing.nba_stats import convert
from front_office.processing.nba_stats.resultsets import (
    PayloadError,
    result_set_frame,
    snapshot_season,
    snapshot_season_type,
)

_BOX_SOURCE = {name: name.upper() for name in BOX_SCORE_COLUMNS}
_ROSTER_BIRTH_DATE = "%b %d, %Y"  # "MAR 03, 1998"
_ON_COURT = "PlayersOnCourtTeamPlayerOnOffSummary"
_OFF_COURT = "PlayersOffCourtTeamPlayerOnOffSummary"

_ADVANCED_SOURCE = {
    "possessions": "POSS",
    "off_rating": "OFF_RATING",
    "def_rating": "DEF_RATING",
    "net_rating": "NET_RATING",
    "usage_pct": "USG_PCT",
    "assist_pct": "AST_PCT",
    "oreb_pct": "OREB_PCT",
    "dreb_pct": "DREB_PCT",
    "reb_pct": "REB_PCT",
    "pace": "PACE",
    "player_impact_estimate": "PIE",
}


def build_players(player_index: Snapshot, rosters: Sequence[Snapshot] = ()) -> pd.DataFrame:
    """The player table, from the all-time index plus birth dates found on rosters."""
    source = result_set_frame(
        player_index,
        required=(
            "PERSON_ID",
            "PLAYER_LAST_NAME",
            "PLAYER_FIRST_NAME",
            "TEAM_ID",
            "POSITION",
            "HEIGHT",
            "WEIGHT",
            "COLLEGE",
            "COUNTRY",
            "DRAFT_YEAR",
            "DRAFT_ROUND",
            "DRAFT_NUMBER",
            "ROSTER_STATUS",
            "FROM_YEAR",
            "TO_YEAR",
        ),
    )
    first = convert.text(source["PLAYER_FIRST_NAME"])
    last = convert.text(source["PLAYER_LAST_NAME"])
    roster_status = convert.integers(source["ROSTER_STATUS"])
    is_active = (roster_status == 1).fillna(False).astype(bool)
    team_id = convert.integers(source["TEAM_ID"])

    frame = pd.DataFrame(
        {
            "player_id": convert.integers(source["PERSON_ID"]),
            "full_name": [
                " ".join(part for part in pair if part) for pair in zip(first, last, strict=True)
            ],
            "first_name": first,
            "last_name": last,
            "position": convert.text(source["POSITION"]),
            "height_inches": convert.heights(source["HEIGHT"]),
            "weight_lbs": convert.integers(convert.text(source["WEIGHT"])),
            "country": convert.text(source["COUNTRY"]),
            "college": convert.text(source["COLLEGE"]),
            "draft_year": convert.integers(source["DRAFT_YEAR"]),
            "draft_round": convert.integers(source["DRAFT_ROUND"]),
            "draft_number": convert.integers(source["DRAFT_NUMBER"]),
            "first_season_year": convert.integers(source["FROM_YEAR"]),
            "last_season_year": convert.integers(source["TO_YEAR"]),
            "is_active": is_active,
            # The index lists a retired player's last team; only an active player's
            # team is his current one.
            "current_team_id": team_id.where(is_active & (team_id > 0)),
        }
    )

    birth_dates = _roster_birth_dates(rosters)
    frame["birth_date"] = frame["player_id"].map(birth_dates)
    return conform_frame(frame[list(PLAYERS.column_names)].sort_values("player_id"), PLAYERS)


def _roster_birth_dates(rosters: Sequence[Snapshot]) -> dict[int, pd.Timestamp]:
    """Birth date per player; the most recent season's roster wins a disagreement."""
    found: dict[int, pd.Timestamp] = {}
    for snapshot in sorted(rosters, key=snapshot_season):
        source = result_set_frame(snapshot, required=("PLAYER_ID", "BIRTH_DATE"))
        if source.empty:
            continue
        ids = convert.integers(source["PLAYER_ID"])
        born = convert.dates(source["BIRTH_DATE"], format=_ROSTER_BIRTH_DATE)
        for player_id, birth_date in zip(ids, born, strict=True):
            if pd.notna(birth_date):
                found[int(player_id)] = birth_date
    return found


def build_player_seasons(
    *, base: Snapshot, advanced: Snapshot, starters: Snapshot | None = None
) -> pd.DataFrame:
    """One season and season type of player totals with the league's on-court measurements."""
    season = snapshot_season(base)
    season_type = snapshot_season_type(base)
    for other in (advanced, starters):
        if other is not None and (
            snapshot_season(other) != season or snapshot_season_type(other) != season_type
        ):
            raise PayloadError(f"{other.describe()} does not match {base.describe()}")

    totals = result_set_frame(
        base,
        required=(
            "PLAYER_ID",
            "PLAYER_NAME",
            "TEAM_ID",
            "AGE",
            "GP",
            "W",
            "L",
            "MIN",
            *_BOX_SOURCE.values(),
            "BLKA",
            "PFD",
            "PLUS_MINUS",
            "DD2",
            "TD3",
            "TEAM_COUNT",
        ),
    )
    if totals.empty:
        return PLAYER_SEASONS.empty_frame()
    measured = result_set_frame(advanced, required=("PLAYER_ID", *_ADVANCED_SOURCE.values()))

    frame = pd.DataFrame(
        {
            "player_id": convert.integers(totals["PLAYER_ID"]),
            "season": season.label,
            "season_type": season_type.value,
            "player_name": convert.text(totals["PLAYER_NAME"]),
            "team_id": convert.integers(totals["TEAM_ID"]),
            "team_count": convert.integers(totals["TEAM_COUNT"]),
            "age": convert.integers(totals["AGE"]),
            "games_played": convert.integers(totals["GP"]),
            "wins": convert.integers(totals["W"]),
            "losses": convert.integers(totals["L"]),
            "minutes": convert.floats(totals["MIN"]),
            "blocked_attempts": convert.integers(totals["BLKA"]),
            "fouls_drawn": convert.integers(totals["PFD"]),
            "plus_minus": convert.integers(totals["PLUS_MINUS"]),
            "double_doubles": convert.integers(totals["DD2"]),
            "triple_doubles": convert.integers(totals["TD3"]),
        }
    )
    for column, source_column in _BOX_SOURCE.items():
        frame[column] = convert.integers(totals[source_column])

    on_court = pd.DataFrame({"player_id": convert.integers(measured["PLAYER_ID"])})
    for column, source_column in _ADVANCED_SOURCE.items():
        convert_column = convert.integers if column == "possessions" else convert.floats
        on_court[column] = convert_column(measured[source_column])
    if set(on_court["player_id"]) != set(frame["player_id"]):
        raise PayloadError(
            f"{base.describe()}: the advanced dataset covers different players from the base totals"
        )
    frame = frame.merge(on_court, on="player_id", how="left", validate="one_to_one")

    if starters is None:
        frame["games_started"] = None
    else:
        started = result_set_frame(starters, required=("PLAYER_ID", "GP"))
        starts = pd.Series(
            convert.integers(started["GP"]).to_numpy(),
            index=convert.integers(started["PLAYER_ID"]).to_numpy(),
        )
        # A player missing from the starters dataset started no games.
        frame["games_started"] = frame["player_id"].map(starts).fillna(0).astype("Int64")

    return conform_frame(
        frame[list(PLAYER_SEASONS.column_names)].sort_values("player_id"), PLAYER_SEASONS
    )


def build_player_game_logs(logs: Snapshot, team_games: pd.DataFrame) -> pd.DataFrame:
    """One season and season type of player box scores.

    ``team_games`` supplies each row's opponent and home/away flag, so those are stated
    once, by the team table, and can never disagree with it.
    """
    season = snapshot_season(logs)
    season_type = snapshot_season_type(logs)
    source = result_set_frame(
        logs,
        required=(
            "PLAYER_ID",
            "TEAM_ID",
            "GAME_ID",
            "GAME_DATE",
            "WL",
            "MIN",
            *_BOX_SOURCE.values(),
            "PLUS_MINUS",
        ),
    )
    if source.empty:
        return PLAYER_GAME_LOGS.empty_frame()

    frame = pd.DataFrame(
        {
            "player_id": convert.integers(source["PLAYER_ID"]),
            "game_id": convert.text(source["GAME_ID"]),
            "season": season.label,
            "season_type": season_type.value,
            "game_date": convert.dates(source["GAME_DATE"], format="%Y-%m-%d"),
            "team_id": convert.integers(source["TEAM_ID"]),
            "won": convert.flags(source["WL"], true="W", false="L"),
            "minutes": convert.integers(source["MIN"]),
            "plus_minus": convert.integers(source["PLUS_MINUS"]),
        }
    )
    for column, source_column in _BOX_SOURCE.items():
        frame[column] = convert.integers(source[source_column])

    context = team_games[
        ["game_id", "team_id", "opponent_team_id", "is_home", "is_neutral_site"]
    ].astype({"team_id": "Int64"})
    frame = frame.merge(context, on=["game_id", "team_id"], how="left", validate="many_to_one")
    unmatched = frame["opponent_team_id"].isna()
    if unmatched.any():
        games = frame.loc[unmatched, "game_id"].unique()[:5].tolist()
        raise PayloadError(
            f"{logs.describe()}: player rows for games missing from the team game logs: {games}"
        )
    frame = frame.sort_values(["game_date", "game_id", "team_id", "player_id"])
    return conform_frame(frame[list(PLAYER_GAME_LOGS.column_names)], PLAYER_GAME_LOGS)


def build_team_rosters(rosters: Sequence[Snapshot]) -> pd.DataFrame:
    """Roster membership from one roster snapshot per team per season."""
    frames = []
    for snapshot in rosters:
        season = snapshot_season(snapshot)
        source = result_set_frame(
            snapshot,
            required=(
                "TeamID",
                "SEASON",
                "PLAYER",
                "PLAYER_ID",
                "NUM",
                "POSITION",
                "HEIGHT",
                "WEIGHT",
                "BIRTH_DATE",
                "EXP",
                "SCHOOL",
                "HOW_ACQUIRED",
            ),
        )
        if source.empty:
            continue
        echoed = set(convert.text(source["SEASON"]))
        if echoed != {str(season.start_year)}:
            raise PayloadError(
                f"{snapshot.describe()}: roster rows are for season(s) {sorted(echoed)}"
            )
        team_ids = convert.integers(source["TeamID"])
        if set(team_ids) != {int(snapshot.partition["team_id"])}:
            raise PayloadError(f"{snapshot.describe()}: roster rows belong to another team")
        frames.append(
            pd.DataFrame(
                {
                    "season": season.label,
                    "team_id": team_ids,
                    "player_id": convert.integers(source["PLAYER_ID"]),
                    "player_name": convert.text(source["PLAYER"]),
                    "jersey_number": convert.text(source["NUM"]),
                    "position": convert.text(source["POSITION"]),
                    "height_inches": convert.heights(source["HEIGHT"]),
                    "weight_lbs": convert.integers(convert.text(source["WEIGHT"])),
                    "birth_date": convert.dates(source["BIRTH_DATE"], format=_ROSTER_BIRTH_DATE),
                    "experience_years": _experience(source["EXP"]),
                    "school": convert.text(source["SCHOOL"]),
                    "how_acquired": convert.text(source["HOW_ACQUIRED"]),
                }
            )
        )
    if not frames:
        return TEAM_ROSTERS.empty_frame()
    frame = pd.concat(frames, ignore_index=True).sort_values(["season", "team_id", "player_id"])
    return conform_frame(frame[list(TEAM_ROSTERS.column_names)], TEAM_ROSTERS)


def _experience(series: pd.Series) -> pd.Series:
    """Completed seasons: the source writes a rookie as "R"."""
    cleaned = convert.text(series).map(lambda value: "0" if value == "R" else value)
    return convert.integers(cleaned.rename(series.name))


def build_player_on_off(on_off: Sequence[Snapshot]) -> pd.DataFrame:
    """Team ratings with each player on and off the court, one snapshot per team."""
    frames = []
    for snapshot in on_off:
        season = snapshot_season(snapshot)
        season_type = snapshot_season_type(snapshot)
        team_id = int(snapshot.partition["team_id"])
        on = _on_off_side(snapshot, _ON_COURT, "on_court", team_id)
        off = _on_off_side(snapshot, _OFF_COURT, "off_court", team_id)
        if on.empty:
            continue
        # A rostered player who never took the court appears in the "off" set only. He
        # has no on/off split, so he is left out.
        both = on.merge(off, on="player_id", how="left", validate="one_to_one")
        both.insert(1, "season", season.label)
        both.insert(2, "season_type", season_type.value)
        both.insert(3, "team_id", team_id)
        frames.append(both)
    if not frames:
        return PLAYER_ON_OFF.empty_frame()
    frame = pd.concat(frames, ignore_index=True).sort_values(["season", "team_id", "player_id"])
    return conform_frame(frame[list(PLAYER_ON_OFF.column_names)], PLAYER_ON_OFF)


def _on_off_side(snapshot: Snapshot, result_set: str, prefix: str, team_id: int) -> pd.DataFrame:
    source = result_set_frame(
        snapshot,
        name=result_set,
        required=("TEAM_ID", "VS_PLAYER_ID", "MIN", "OFF_RATING", "DEF_RATING", "NET_RATING"),
    )
    if not source.empty and set(convert.integers(source["TEAM_ID"])) != {team_id}:
        raise PayloadError(f"{snapshot.describe()}: on/off rows belong to another team")
    return pd.DataFrame(
        {
            "player_id": convert.integers(source["VS_PLAYER_ID"]),
            f"{prefix}_minutes": convert.floats(source["MIN"]),
            f"{prefix}_off_rating": convert.floats(source["OFF_RATING"]),
            f"{prefix}_def_rating": convert.floats(source["DEF_RATING"]),
            f"{prefix}_net_rating": convert.floats(source["NET_RATING"]),
        }
    )
