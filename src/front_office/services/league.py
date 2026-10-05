"""League views for the workbench: standings, league averages, history and champions.

This module assembles: it reads tables, calls analytics, and joins the results with
names. It contains no formulas.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from front_office.analytics import comparison as compare
from front_office.analytics import teams as analytics
from front_office.domain.metrics import MetricCatalog
from front_office.domain.seasons import SeasonType
from front_office.services.lab import Lab

RANKED_RATINGS = ("net_rating", "off_rating", "def_rating")
"""The ratings whose league rank is carried in every team-season of the history."""


class LeagueService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def metrics(self) -> MetricCatalog:
        return analytics.TEAM_METRICS

    def season_dates(self, season: str, season_type: str) -> tuple[date, date] | None:
        """The first and last game dates of a season's phase, or ``None`` without games."""
        games = self._lab.read("team_games", {"season": season, "season_type": season_type})
        if games.empty:
            return None
        return games["game_date"].min().date(), games["game_date"].max().date()

    def standings(self, season: str) -> pd.DataFrame:
        """One season's teams in conference order.

        Every team metric, games behind the conference leader, the record at home, on
        the road and over the last ten games, the current streak, and how the season
        ended once that is known.
        """
        seasons = self._team_seasons(season)
        table = analytics.standings(analytics.team_season_metrics(seasons))
        games = self._lab.read(
            "team_games", {"season": season, "season_type": SeasonType.REGULAR.value}
        )
        splits = analytics.record_splits(games)
        table = table.join(splits.reindex(table["team_id"], fill_value=0), on="team_id")
        table["home_record"] = _records(table["home_wins"], table["home_losses"])
        table["road_record"] = _records(table["road_wins"], table["road_losses"])
        table["recent_record"] = _records(table["recent_wins"], table["recent_losses"])
        table["streak_label"] = [_streak_label(streak) for streak in table["streak"]]
        table["postseason_result"] = analytics.postseason_result(table)
        return table

    def averages(self) -> pd.DataFrame:
        """The league's average of every team metric in each season, oldest first."""
        return analytics.league_averages(self._lab.read("team_seasons"))

    def changes(self) -> pd.DataFrame:
        """How each league average moved from the season before it on record.

        Same shape as :meth:`averages`. The first season has nothing to compare with
        and is missing throughout.
        """
        return analytics.season_over_season(self.averages())

    def history(self) -> pd.DataFrame:
        """Every team-season on record, newest first.

        Metrics, the league rank of each rating within its season, the number of teams
        that season, and how the season ended: the dataset that benchmark research on
        what contenders look like starts from.
        """
        metrics = analytics.team_season_metrics(self._lab.read("team_seasons"))
        by_season = metrics["season"]
        for key in RANKED_RATINGS:
            metrics[f"{key}_rank"] = compare.ranks(
                metrics, analytics.TEAM_METRICS, key, group=by_season
            )
        metrics["league_teams"] = metrics.groupby("season")["team_id"].transform("size")
        metrics["postseason_result"] = analytics.postseason_result(metrics)
        ordered = metrics.sort_values(["season", "team_name"], ascending=[False, True])
        return ordered.reset_index(drop=True)

    def champions(self) -> pd.DataFrame:
        """Each decided NBA Finals, newest first: the champion, whom it beat, and how good it was."""
        finals = self._lab.read("playoff_results", {"round": 4})
        finals = finals[finals["is_complete"].astype(bool)]
        history = self.history()
        champion_columns = [
            "season",
            "team_id",
            "team_name",
            "conference",
            "conference_rank",
            "wins",
            "losses",
            "win_pct",
            "net_rating",
            "rel_off_rating",
            "rel_def_rating",
            *(f"{key}_rank" for key in RANKED_RATINGS),
            "league_teams",
        ]
        champion = history[champion_columns].rename(
            columns={"team_id": "winner_team_id", "team_name": "champion"}
        )
        runner_up = history[["season", "team_id", "team_name"]].rename(
            columns={"team_id": "loser_team_id", "team_name": "runner_up"}
        )
        wins = finals[["team_a_wins", "team_b_wins"]]
        table = finals[["season", "winner_team_id", "loser_team_id"]].assign(
            series=_records(wins.max(axis=1), wins.min(axis=1)).to_numpy()
        )
        table = table.astype({"winner_team_id": "int64", "loser_team_id": "int64"})
        table = table.merge(champion, on=["season", "winner_team_id"], how="left")
        table = table.merge(runner_up, on=["season", "loser_team_id"], how="left")
        leading = ["season", "champion", "runner_up", "series"]
        ordered = leading + [column for column in table.columns if column not in leading]
        return table[ordered].sort_values("season", ascending=False).reset_index(drop=True)

    def playoffs(self, season: str) -> pd.DataFrame:
        """The series of one postseason in bracket order, with names and seeds.

        ``conference`` is the conference a series was played in, and missing for the
        NBA Finals.
        """
        series = self._lab.read(
            "playoff_results", {"season": season}, order_by=["round", "start_date", "series_id"]
        )
        teams = self._lab.read("team_seasons", {"season": season}).set_index("team_id")
        for side in ("team_a", "team_b"):
            series[side] = series[f"{side}_id"].map(teams["team_name"])
            series[f"{side}_seed"] = series[f"{side}_id"].map(teams["conference_rank"])
        series["winner"] = series["winner_team_id"].map(teams["team_name"])
        conference_a = series["team_a_id"].map(teams["conference"])
        conference_b = series["team_b_id"].map(teams["conference"])
        series["conference"] = conference_a.where(conference_a == conference_b)
        return series

    def _team_seasons(self, season: str) -> pd.DataFrame:
        seasons = self._lab.read("team_seasons", {"season": season})
        if seasons.empty:
            raise KeyError(f"no team statistics for {season}")
        return seasons


def _records(wins: pd.Series, losses: pd.Series) -> pd.Series:
    """Wins and losses as they are written: ``30-11``."""
    return wins.astype("int64").astype("str") + "-" + losses.astype("int64").astype("str")


def _streak_label(streak: int) -> str | None:
    """A streak as it is written: ``W3`` for three straight wins, ``L2`` for two losses."""
    if streak == 0:
        return None
    return f"{'W' if streak > 0 else 'L'}{abs(int(streak))}"
