"""Team views for the workbench: the season table, a franchise's profile, its games.

This module assembles: it reads tables, calls analytics, and joins the results with
names. It contains no formulas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from front_office.analytics import comparison as compare
from front_office.analytics import players as player_analytics
from front_office.analytics import teams as analytics
from front_office.domain.metrics import MetricCatalog, MetricSpec
from front_office.domain.seasons import SeasonType
from front_office.services.lab import Lab
from front_office.services.window import Window

GAME_COLUMNS = ("game_id", "game_date", "opponent", "opponent_name", "venue", "result")
ROTATION_IDENTITY = (
    "player_name",
    "position",
    "position_group",
    "age",
    "height_inches",
    "experience_years",
    "salary",
    "salary_cap_pct",
    "years_remaining",
)


@dataclass(frozen=True, slots=True)
class TeamTable:
    """Every team of one season: identity, metrics, ranks and the league's averages."""

    season: str
    season_type: str
    window: Window
    teams: pd.DataFrame
    """Indexed by ``team_id``: identity, one column per metric, then how the season ended."""
    ranks: pd.DataFrame
    """Same index; position on each metric, 1 being best, or highest where neither is better."""
    league: pd.Series
    """The league's regular-season average of each metric that season: the reference line."""
    metrics: MetricCatalog
    """The metrics available in this view. A span of games has no league-relative ratings."""
    estimated: tuple[str, ...]
    """Metrics that are estimates in this view rather than the league's published figures."""


@dataclass(frozen=True, slots=True)
class TeamProfile:
    team: dict
    """The franchise as it is now: names, conference and division."""
    seasons: pd.DataFrame
    """One row per season, newest first: metrics, rating ranks and how the season ended."""
    metrics: MetricCatalog = field(default=analytics.TEAM_METRICS)


class TeamService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def metrics(self) -> MetricCatalog:
        return analytics.TEAM_METRICS

    def metric(self, key: str) -> MetricSpec:
        return analytics.TEAM_METRICS[key]

    def table(
        self,
        season: str,
        season_type: str = SeasonType.REGULAR.value,
        *,
        window: Window | None = None,
    ) -> TeamTable:
        """The team table for one season.

        The whole regular season carries the league's published ratings. A narrowed
        ``window``, or the postseason, is computed from game box scores: its ratings,
        pace and turnover rates are estimates and are listed in ``estimated``.
        """
        window = window or Window()
        seasons = self._team_seasons(season)
        full = analytics.team_season_metrics(seasons).set_index("team_id")
        catalog = analytics.TEAM_METRICS
        estimated: tuple[str, ...] = ()

        if window.is_full_season and season_type == SeasonType.REGULAR.value:
            teams = full
        else:
            games = self._lab.read("team_games", {"season": season, "season_type": season_type})
            spans = analytics.team_window_metrics(
                games,
                analytics.possession_calibration(seasons),
                last_games=window.last_games,
                start=window.start_timestamp,
                end=window.end_timestamp,
            )
            identity = [column for column in analytics.IDENTITY_COLUMNS if column != "team_id"]
            teams = full[identity].join(spans, how="inner")
            teams = teams.join(full[list(analytics.OUTCOME_COLUMNS)])
            catalog = MetricCatalog(
                tuple(spec for spec in catalog if spec.key in analytics.WINDOW_METRIC_KEYS)
            )
            estimated = analytics.ESTIMATED_IN_A_WINDOW

        teams = teams.sort_values("team_name")
        teams["postseason_result"] = analytics.postseason_result(teams)
        ranks = pd.DataFrame(
            {key: compare.ranks(teams, catalog, key) for key in catalog.keys}, index=teams.index
        )
        league = analytics.league_averages(seasons).loc[season, list(catalog.keys)]
        return TeamTable(season, season_type, window, teams, ranks, league, catalog, estimated)

    def profile(self, team_id: int) -> TeamProfile:
        """One franchise: who it is now, and every season on record."""
        found = self._lab.read("teams", {"team_id": int(team_id)})
        if found.empty:
            raise KeyError(f"no team with id {team_id}")
        history = self._lab.league.history()
        seasons = history[history["team_id"] == int(team_id)]
        return TeamProfile(team=found.iloc[0].to_dict(), seasons=seasons.reset_index(drop=True))

    def game_log(
        self, team_id: int, season: str, season_type: str = SeasonType.REGULAR.value
    ) -> pd.DataFrame:
        """One team's finished games in a season, newest first, with each game's metrics.

        A single game's ratings and pace are estimates from its box score.
        """
        games = self._lab.read("team_games", {"season": season, "season_type": season_type})
        metrics = analytics.rolling_team_metrics(games, self._calibration(season), games=1)
        metrics = metrics[metrics["team_id"] == int(team_id)]
        keys = [key for key in analytics.WINDOW_METRIC_KEYS if key not in _RECORD_KEYS]
        columns = [*GAME_COLUMNS, "pts", "opp_pts", *keys]
        if metrics.empty:
            return pd.DataFrame(columns=columns)

        own = games[games["team_id"] == int(team_id)].set_index("game_id")
        teams = self._lab.team_labels()
        frame = metrics.join(own[_OWN_COLUMNS], on="game_id")
        frame["opponent"] = frame["opponent_team_id"].map(teams["abbreviation"])
        frame["opponent_name"] = frame["opponent_team_id"].map(teams["full_name"])
        frame["venue"] = "Away"
        frame.loc[frame["is_home"].astype(bool), "venue"] = "Home"
        frame.loc[frame["is_neutral_site"].astype(bool), "venue"] = "Neutral"
        frame["result"] = [
            f"{'W' if won else 'L'} {ours}-{theirs}"
            for won, ours, theirs in zip(frame["won"], frame["pts"], frame["opp_pts"], strict=True)
        ]
        frame = frame.sort_values(["game_date", "game_id"], ascending=False)
        return frame[columns].reset_index(drop=True)

    def rolling(
        self,
        team_id: int,
        season: str,
        season_type: str = SeasonType.REGULAR.value,
        *,
        games: int = 10,
    ) -> pd.DataFrame:
        """Team metrics over the trailing ``games`` games, oldest first. Ratings are estimates."""
        played = self._lab.read("team_games", {"season": season, "season_type": season_type})
        metrics = analytics.rolling_team_metrics(played, self._calibration(season), games=games)
        mine = metrics[metrics["team_id"] == int(team_id)]
        return mine.drop(columns="team_id").reset_index(drop=True)

    def rotation(
        self,
        team_id: int,
        season: str,
        season_type: str = SeasonType.REGULAR.value,
        *,
        payroll_season: str | None = None,
    ) -> pd.DataFrame:
        """What each player did in this team's games, most minutes first.

        Unlike a player's season line, this counts only the games he played for this
        team, so a player traded in mid-season shows what he did here. Indexed by
        ``player_id``: who he is, his contract in ``payroll_season`` if one is given,
        then the box-score metrics. Empty for seasons without player detail.
        """
        logs = self._lab.read(
            "player_game_logs",
            {"team_id": int(team_id), "season": season, "season_type": season_type},
        )
        columns = [*ROTATION_IDENTITY, *player_analytics.BOX_METRIC_KEYS]
        if logs.empty:
            return pd.DataFrame(columns=columns, index=pd.Index([], name="player_id"))
        spans = player_analytics.window_metrics(logs)
        league = self._lab.players.table(season, season_type, payroll_season=payroll_season)
        rotation = league.players[list(ROTATION_IDENTITY)].join(spans, how="right")
        return rotation[columns].sort_values("minutes", ascending=False)

    # --- assembly -----------------------------------------------------------------------

    def _team_seasons(self, season: str) -> pd.DataFrame:
        seasons = self._lab.read("team_seasons", {"season": season})
        if seasons.empty:
            raise KeyError(f"no team statistics for {season}")
        return seasons

    def _calibration(self, season: str) -> pd.Series:
        return analytics.possession_calibration(self._lab.read("team_seasons", {"season": season}))


_RECORD_KEYS = ("games_played", "wins", "losses", "win_pct", "pts_per_game", "opp_pts_per_game")
_OWN_COLUMNS = ["opponent_team_id", "is_home", "is_neutral_site", "won", "pts", "opp_pts"]
