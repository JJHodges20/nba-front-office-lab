"""Player views for the workbench: the season table, a player's profile, comparisons.

This module assembles: it reads tables, calls analytics, and joins the results with
names, teams and contracts. It contains no formulas.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from front_office.analytics import comparison as compare
from front_office.analytics import players as analytics
from front_office.analytics.comparison import Qualification
from front_office.domain.metrics import MetricCatalog, MetricSpec
from front_office.domain.seasons import SeasonType
from front_office.services.lab import Lab
from front_office.services.window import Window

DEFAULT_QUALIFICATION = Qualification(min_games=20, min_minutes=300)

_CONTRACT_COLUMNS = ("salary", "salary_cap_pct", "years_remaining", "option", "guarantee")
_BIO_COLUMNS = ("position", "height_inches", "weight_lbs", "birth_date", "country", "college")

GAME_LOG_COLUMNS = (
    "game_id",
    "game_date",
    "team",
    "opponent",
    "venue",
    "result",
    "minutes",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
    "plus_minus",
    "ts_pct",
)


@dataclass(frozen=True, slots=True)
class PlayerTable:
    """Every player of one season: identity, contract, metrics and percentiles."""

    season: str
    season_type: str
    payroll_season: str | None
    window: Window
    qualification: Qualification
    players: pd.DataFrame
    """Indexed by ``player_id``: identity and contract columns, then one per metric."""
    percentiles: pd.DataFrame
    """Same index; one column per metric, 0-100 with higher always better."""
    metrics: MetricCatalog
    """The metrics available in this view. A narrowed window has box-score metrics only."""

    @property
    def qualified_count(self) -> int:
        return int(self.players["is_qualified"].sum())


@dataclass(frozen=True, slots=True)
class PlayerProfile:
    player: dict
    seasons: pd.DataFrame
    """One row per season and season type, newest first, with every metric."""
    on_off: pd.DataFrame
    """One row per team stint with on-court and off-court ratings."""
    contract_years: pd.DataFrame
    contract: dict | None
    metrics: MetricCatalog = field(default=analytics.PLAYER_METRICS)


class PlayerService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def metrics(self) -> MetricCatalog:
        return analytics.PLAYER_METRICS

    def table(
        self,
        season: str,
        season_type: str = SeasonType.REGULAR.value,
        *,
        window: Window | None = None,
        qualification: Qualification = DEFAULT_QUALIFICATION,
        payroll_season: str | None = None,
        by_position: bool = False,
    ) -> PlayerTable:
        """The player table for one season.

        ``window`` narrows the games considered; the qualification thresholds then apply
        to the games and minutes inside the window. ``by_position`` ranks each player
        against his own position group instead of the whole league.
        """
        window = window or Window()
        where = {"season": season, "season_type": season_type}
        seasons = self._lab.read("player_seasons", where)
        catalog = analytics.PLAYER_METRICS

        if window.is_full_season:
            on_off = self._lab.read("player_on_off", where)
            metrics = analytics.player_season_metrics(seasons, on_off, self._season_games(season))
            metrics = metrics.set_index("player_id")
        else:
            logs = self._lab.read("player_game_logs", where)
            spans = analytics.window_metrics(
                logs,
                last_games=window.last_games,
                start=window.start_timestamp,
                end=window.end_timestamp,
            )
            identity = seasons.set_index("player_id")[
                [c for c in analytics.IDENTITY_COLUMNS if c != "player_id"]
            ]
            metrics = identity.join(spans, how="inner")
            catalog = MetricCatalog(
                tuple(spec for spec in catalog if spec.key in analytics.BOX_METRIC_KEYS)
            )

        players = self._with_identity(metrics, season)
        players = self._with_contracts(players, payroll_season)
        players["is_qualified"] = qualification.mask(players)
        group = players["position_group"] if by_position else None
        ranked = compare.percentiles(
            players, catalog, qualified=players["is_qualified"], group=group
        )
        ordered = _ordered_columns(players, catalog)
        return PlayerTable(
            season=season,
            season_type=season_type,
            payroll_season=payroll_season,
            window=window,
            qualification=qualification,
            players=players[ordered].sort_values("player_name"),
            percentiles=ranked.reindex(players.sort_values("player_name").index),
            metrics=catalog,
        )

    def compare(
        self, table: PlayerTable, player_ids: Sequence[int], keys: Sequence[str]
    ) -> pd.DataFrame:
        """A side-by-side of several players on the chosen metrics.

        One row per metric per player with the metric's label, the value, its formatted
        form and the percentile from ``table``.
        """
        tidy = compare.comparison(table.players, table.percentiles, list(player_ids), list(keys))
        specs = [table.metrics[key] for key in tidy["metric"]]
        tidy["player_name"] = tidy["player_id"].map(table.players["player_name"])
        tidy["label"] = [spec.label for spec in specs]
        tidy["name"] = [spec.name for spec in specs]
        tidy["category"] = [spec.category for spec in specs]
        tidy["shown"] = [
            spec.format_value(value) for spec, value in zip(specs, tidy["value"], strict=True)
        ]
        return tidy

    def profile(self, player_id: int, *, payroll_season: str | None = None) -> PlayerProfile:
        """Everything about one player: who he is, every season, on/off, contract."""
        found = self._lab.read("players", {"player_id": int(player_id)})
        if found.empty:
            raise KeyError(f"no player with id {player_id}")
        teams = self._lab.team_labels()
        player = found.iloc[0].to_dict()
        team_id = player["current_team_id"]
        player["current_team"] = None if pd.isna(team_id) else teams.at[int(team_id), "full_name"]
        player["position_group"] = compare.position_group(player["position"])

        seasons = self._lab.read("player_seasons", {"player_id": int(player_id)})
        on_off = self._lab.read("player_on_off", {"player_id": int(player_id)})
        lengths = self._lab.read("team_seasons").groupby("season")["games_played"].max()
        lines = analytics.player_season_metrics(seasons, on_off, lengths)
        lines.insert(4, "team", lines["team_id"].map(teams["abbreviation"]))
        lines = lines.sort_values(["season", "season_type"], ascending=[False, False])

        stints = on_off.copy()
        stints.insert(4, "team", stints["team_id"].map(teams["abbreviation"]))
        stints["on_off_net"] = stints["on_court_net_rating"] - stints["off_court_net_rating"]

        years = self._lab.read("contract_years", {"player_id": int(player_id)}, order_by=["season"])
        years.insert(2, "team", years["team_id"].map(teams["abbreviation"]))
        contracts = self._lab.read("contracts", {"player_id": int(player_id)})
        return PlayerProfile(
            player=player,
            seasons=lines.reset_index(drop=True),
            on_off=stints.sort_values("season", ascending=False).reset_index(drop=True),
            contract_years=years,
            contract=None if contracts.empty else contracts.iloc[0].to_dict(),
        )

    def game_log(self, player_id: int, season: str, season_type: str = "regular") -> pd.DataFrame:
        """One player's games in a season, newest first, with each game's true shooting."""
        logs = self._lab.read(
            "player_game_logs",
            {"player_id": int(player_id), "season": season, "season_type": season_type},
        )
        if logs.empty:
            return pd.DataFrame(columns=list(GAME_LOG_COLUMNS))
        teams = self._lab.team_labels()["abbreviation"]
        games = self._lab.read("team_games", {"game_id": logs["game_id"].tolist()})
        scores = games.set_index(["game_id", "team_id"])[["pts", "opp_pts"]]
        index = pd.MultiIndex.from_frame(logs[["game_id", "team_id"]])
        team_pts = scores["pts"].reindex(index).to_numpy()
        opp_pts = scores["opp_pts"].reindex(index).to_numpy()

        frame = logs.copy()
        frame["team"] = frame["team_id"].map(teams)
        frame["opponent"] = frame["opponent_team_id"].map(teams)
        frame["venue"] = "Away"
        frame.loc[frame["is_home"], "venue"] = "Home"
        frame.loc[frame["is_neutral_site"], "venue"] = "Neutral"
        outcome = (
            frame["won"].map({True: "W", False: "L"}).astype(object).where(frame["won"].notna(), "")
        )
        frame["result"] = [
            f"{letter} {ours}-{theirs}".strip()
            for letter, ours, theirs in zip(outcome, team_pts, opp_pts, strict=True)
        ]
        per_game = analytics.box_metrics(frame.assign(games_played=1))
        frame["ts_pct"] = per_game["ts_pct"]
        frame = frame.sort_values(["game_date", "game_id"], ascending=False)
        return frame[list(GAME_LOG_COLUMNS)].reset_index(drop=True)

    def rolling(
        self, player_id: int, season: str, season_type: str = "regular", *, games: int = 10
    ) -> pd.DataFrame:
        """Box metrics over the player's trailing ``games`` games, oldest first."""
        logs = self._lab.read(
            "player_game_logs",
            {"player_id": int(player_id), "season": season, "season_type": season_type},
        )
        return analytics.rolling_metrics(logs, games=games).drop(columns="player_id")

    def availability(self, season: str, *, team_games_back: int = 20) -> pd.DataFrame:
        """Each player's appearances in his team's most recent regular-season games."""
        where = {"season": season, "season_type": SeasonType.REGULAR.value}
        logs = self._lab.read("player_game_logs", where)
        games = self._lab.read("team_games", where)
        return analytics.recent_availability(logs, games, team_games_back=team_games_back)

    def metric(self, key: str) -> MetricSpec:
        return analytics.PLAYER_METRICS[key]

    # --- assembly -----------------------------------------------------------------------

    def _season_games(self, season: str) -> pd.Series:
        lengths = self._lab.read("team_seasons", {"season": season})
        return lengths.groupby("season")["games_played"].max()

    def _with_identity(self, metrics: pd.DataFrame, season: str) -> pd.DataFrame:
        teams = self._lab.team_labels()
        bio = self._lab.read("players", {"player_id": metrics.index.tolist()}).set_index(
            "player_id"
        )
        rosters = self._lab.read("team_rosters", {"season": season})
        experience = rosters.drop_duplicates("player_id").set_index("player_id")["experience_years"]

        frame = metrics.copy()
        frame.insert(2, "team", frame["team_id"].map(teams["abbreviation"]))
        frame.insert(3, "team_name", frame["team_id"].map(teams["full_name"]))
        for column in _BIO_COLUMNS:
            frame[column] = bio[column].reindex(frame.index)
        frame["position_group"] = frame["position"].map(compare.position_group)
        frame["experience_years"] = experience.reindex(frame.index)
        return frame

    def _with_contracts(self, players: pd.DataFrame, payroll_season: str | None) -> pd.DataFrame:
        frame = players.copy()
        if payroll_season is None:
            for column in _CONTRACT_COLUMNS:
                frame[column] = None
            return frame
        years = self._lab.read("contract_years", {"season": payroll_season})
        contracts = self._lab.read("contracts")[["contract_id", "status"]]
        active = years.merge(contracts, on="contract_id")
        active = active[active["status"] == "active"].drop_duplicates("player_id")
        active = active.set_index("player_id")
        for column in _CONTRACT_COLUMNS:
            frame[column] = active[column].reindex(frame.index)
        return frame


def _ordered_columns(players: pd.DataFrame, catalog: MetricCatalog) -> list[str]:
    leading = [
        "player_name",
        "team",
        "team_name",
        "team_id",
        "team_count",
        "position",
        "position_group",
        "age",
        "height_inches",
        "weight_lbs",
        "experience_years",
        "birth_date",
        "country",
        "college",
        "is_qualified",
        *_CONTRACT_COLUMNS,
    ]
    return [*leading, *(key for key in catalog.keys if key in players.columns)]
