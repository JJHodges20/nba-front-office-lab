"""Derive playoff series and postseason outcomes from game results.

The league's own series identifiers are unreliable before the 2001-02 season, so series
are reconstructed from the games themselves: two teams meet in at most one series per
postseason, and a team's first series is the first round, its second the conference
semifinals, and so on. That rule holds for every season since the 16-team bracket began
in 1984, which covers all of the lab's history.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from front_office.domain.schema import conform_frame
from front_office.domain.seasons import Season, SeasonType
from front_office.domain.tables.teams import PLAYOFF_RESULTS, ROUND_NAMES

LAST_BEST_OF_FIVE_FIRST_ROUND = Season(2001)
"""First-round series were best-of-five through the 2001-02 season, best-of-seven since."""

FINALS_ROUND = len(ROUND_NAMES)


class BracketError(ValueError):
    """Game results do not form a consistent playoff bracket."""


def best_of(season: Season, playoff_round: int) -> int:
    """Scheduled length of a series."""
    if playoff_round == 1 and season <= LAST_BEST_OF_FIVE_FIRST_ROUND:
        return 5
    return 7


def build_playoff_results(season: Season, team_games: pd.DataFrame) -> pd.DataFrame:
    """Every playoff series of one season, from that season's ``team_games`` rows."""
    games = team_games[
        (team_games["season"] == season.label)
        & (team_games["season_type"] == SeasonType.PLAYOFFS.value)
    ]
    if games.empty:
        return PLAYOFF_RESULTS.empty_frame()

    # One row per game: the home team's or, at a neutral site, the lower team id's.
    hosts = games.sort_values(
        ["game_date", "game_id", "is_home", "team_id"], ascending=[True, True, False, True]
    ).drop_duplicates("game_id")
    if len(hosts) * 2 != len(games):
        raise BracketError(f"{season.label}: playoff games do not each have two team rows")

    low = hosts[["team_id", "opponent_team_id"]].min(axis=1)
    high = hosts[["team_id", "opponent_team_id"]].max(axis=1)

    series_played: dict[int, int] = {}
    rows = []
    # Series are taken in the order they began, so earlier rounds are counted first.
    grouped = hosts.groupby([low, high], sort=False)
    ordered = sorted(
        grouped, key=lambda item: (item[1]["game_date"].iloc[0], item[1]["game_id"].iloc[0])
    )
    for _, series_games in ordered:
        first = series_games.iloc[0]
        team_a, team_b = int(first["team_id"]), int(first["opponent_team_id"])
        round_a = series_played.get(team_a, 0) + 1
        round_b = series_played.get(team_b, 0) + 1
        if round_a != round_b or round_a > FINALS_ROUND:
            raise BracketError(
                f"{season.label}: teams {team_a} and {team_b} meet in inconsistent rounds "
                f"({round_a} and {round_b})"
            )
        series_played[team_a] = round_a
        series_played[team_b] = round_b

        decided = series_games[series_games["won"].notna()]
        # Each row is one game seen from one team; team A won it if that team is A and
        # it won, or that team is B and it lost.
        row_team_won = decided["won"].astype(bool)
        a_wins = int(((decided["team_id"] == team_a) == row_team_won).sum())
        b_wins = len(decided) - a_wins
        length = best_of(season, round_a)
        needed = length // 2 + 1
        if max(a_wins, b_wins) > needed:
            raise BracketError(
                f"{season.label}: a round {round_a} series between {team_a} and {team_b} "
                f"has {max(a_wins, b_wins)} wins for one team in a best-of-{length}"
            )
        complete = max(a_wins, b_wins) == needed
        winner = (team_a if a_wins > b_wins else team_b) if complete else None
        loser = (team_b if a_wins > b_wins else team_a) if complete else None
        rows.append(
            {
                "season": season.label,
                "series_id": f"{season.label}-R{round_a}-{min(team_a, team_b)}-{max(team_a, team_b)}",
                "round": round_a,
                "round_name": ROUND_NAMES[round_a - 1],
                "team_a_id": team_a,
                "team_b_id": team_b,
                "team_a_wins": a_wins,
                "team_b_wins": b_wins,
                "games_played": len(series_games),
                "best_of": length,
                "is_complete": complete,
                "winner_team_id": winner,
                "loser_team_id": loser,
                "start_date": series_games["game_date"].iloc[0],
                "end_date": series_games["game_date"].iloc[-1],
            }
        )

    frame = pd.DataFrame(rows, columns=list(PLAYOFF_RESULTS.column_names))
    frame = frame.sort_values(["round", "start_date", "series_id"])
    return conform_frame(frame, PLAYOFF_RESULTS)


def postseason_is_complete(series: pd.DataFrame) -> bool:
    """Whether the season has a decided NBA Finals and no series left open."""
    if series.empty:
        return False
    finals = series[series["round"] == FINALS_ROUND]
    return len(finals) == 1 and bool(series["is_complete"].all())


def postseason_outcomes(
    series: pd.DataFrame, team_ids: Iterable[int], play_in_team_ids: Iterable[int] = ()
) -> pd.DataFrame | None:
    """Each team's postseason outcome, or ``None`` while the postseason is unfinished.

    Outcomes are withheld until the Finals are decided: a "did not reach the conference
    finals" recorded mid-playoffs could silently become wrong a week later.
    """
    if not postseason_is_complete(series):
        return None

    play_in = set(play_in_team_ids)
    rows = []
    for team_id in sorted(set(team_ids)):
        as_a = series[series["team_a_id"] == team_id]
        as_b = series[series["team_b_id"] == team_id]
        furthest = int(
            max(as_a["round"].max() if len(as_a) else 0, as_b["round"].max() if len(as_b) else 0)
        )
        wins = int(as_a["team_a_wins"].sum() + as_b["team_b_wins"].sum())
        losses = int(as_a["team_b_wins"].sum() + as_b["team_a_wins"].sum())
        series_won = int((series["winner_team_id"] == team_id).sum())
        rows.append(
            {
                "team_id": team_id,
                "made_play_in": team_id in play_in,
                "made_playoffs": furthest >= 1,
                "playoff_round_reached": furthest,
                "playoff_series_won": series_won,
                "playoff_wins": wins,
                "playoff_losses": losses,
                "made_conference_finals": furthest >= FINALS_ROUND - 1,
                "made_finals": furthest >= FINALS_ROUND,
                "won_championship": series_won == FINALS_ROUND,
            }
        )
    return pd.DataFrame(rows)
