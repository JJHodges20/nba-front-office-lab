"""Player metrics: a season's line, or any span of games, turned into comparable numbers.

Two kinds of metric come out of here. *Derived* metrics are computed by the formulas in
:mod:`front_office.analytics.formulas` from box-score totals. *Measured* metrics - usage,
assist and rebound percentages, on-court ratings - are the league's own, counted from
play-by-play, and are passed through unchanged: they cannot be recomputed from a box
score, and a home-made approximation shown next to the league's number would only invite
doubt about both.
"""

from __future__ import annotations

import pandas as pd

from front_office.analytics import formulas as f
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS

AVAILABILITY = "Availability"
SCORING = "Scoring"
CREATION = "Creation"
REBOUNDING = "Rebounding"
DEFENSE = "Defense"
IMPACT = "Impact"

_MEASURED, _DERIVED = Provenance.MEASURED, Provenance.DERIVED
_PCT, _COUNT, _SIGNED = MetricFormat.PERCENT, MetricFormat.COUNT, MetricFormat.SIGNED


def _per_game(
    stat: str, label: str, name: str, category: str, better: bool | None = True
) -> MetricSpec:
    return MetricSpec(
        f"{stat}_per_game",
        label,
        f"{name} per game",
        f"{name} divided by games played.",
        category,
        higher_is_better=better,
    )


def _per_36(
    stat: str, label: str, name: str, category: str, better: bool | None = True
) -> MetricSpec:
    return MetricSpec(
        f"{stat}_per_36",
        f"{label}/36",
        f"{name} per 36 minutes",
        f"{name} scaled to 36 minutes, so players with different minutes can be compared.",
        category,
        higher_is_better=better,
    )


PLAYER_METRICS = MetricCatalog(
    (
        # --- Availability -------------------------------------------------------------
        MetricSpec(
            "games_played",
            "GP",
            "Games played",
            "Games the player appeared in.",
            AVAILABILITY,
            _COUNT,
            _MEASURED,
        ),
        MetricSpec(
            "games_started",
            "GS",
            "Games started",
            "Games the player started.",
            AVAILABILITY,
            _COUNT,
            _MEASURED,
        ),
        MetricSpec(
            "start_share",
            "GS%",
            "Share of games started",
            "Games started divided by games played.",
            AVAILABILITY,
            _PCT,
            higher_is_better=None,
        ),
        MetricSpec(
            "games_played_share",
            "GP%",
            "Share of the season played",
            "Games played divided by the number of games in the season. Low values mean "
            "injury, a late arrival or a small role.",
            AVAILABILITY,
            _PCT,
        ),
        MetricSpec(
            "minutes",
            "MIN",
            "Minutes",
            "Total minutes played.",
            AVAILABILITY,
            _COUNT,
            _MEASURED,
            higher_is_better=None,
        ),
        MetricSpec(
            "minutes_per_game",
            "MPG",
            "Minutes per game",
            "Minutes divided by games played.",
            AVAILABILITY,
            higher_is_better=None,
        ),
        # --- Scoring ------------------------------------------------------------------
        _per_game("pts", "PPG", "Points", SCORING),
        _per_36("pts", "PTS", "Points", SCORING),
        MetricSpec(
            "pts_per_100",
            "PTS/100",
            "Points per 100 possessions",
            "Points per 100 team possessions while the player was on the court, which "
            "removes the effect of pace.",
            SCORING,
        ),
        MetricSpec(
            "fg_pct",
            "FG%",
            "Field goal percentage",
            "Field goals made divided by attempted.",
            SCORING,
            _PCT,
        ),
        MetricSpec(
            "fg3_pct",
            "3P%",
            "Three-point percentage",
            "Three-pointers made divided by attempted.",
            SCORING,
            _PCT,
        ),
        MetricSpec(
            "ft_pct",
            "FT%",
            "Free throw percentage",
            "Free throws made divided by attempted.",
            SCORING,
            _PCT,
        ),
        MetricSpec(
            "efg_pct",
            "eFG%",
            "Effective field goal percentage",
            "(FGM + 0.5 x 3PM) / FGA. Field goal percentage that credits a three as one and "
            "a half makes.",
            SCORING,
            _PCT,
        ),
        MetricSpec(
            "ts_pct",
            "TS%",
            "True shooting percentage",
            "PTS / (2 x (FGA + 0.44 x FTA)). Scoring efficiency counting twos, threes and "
            "free throws together.",
            SCORING,
            _PCT,
        ),
        _per_game("fg3m", "3PM", "Three-pointers made", SCORING),
        _per_game("fg3a", "3PA", "Three-point attempts", SCORING, better=None),
        MetricSpec(
            "fg3a_rate",
            "3PAr",
            "Three-point attempt rate",
            "Share of field goal attempts taken from three: 3PA / FGA.",
            SCORING,
            _PCT,
            higher_is_better=None,
        ),
        _per_game("fta", "FTA", "Free throw attempts", SCORING),
        MetricSpec(
            "ft_rate",
            "FTr",
            "Free throw rate",
            "Free throw attempts per field goal attempt: FTA / FGA. How often a player "
            "gets to the line.",
            SCORING,
            decimals=3,
        ),
        # --- Creation -----------------------------------------------------------------
        _per_game("ast", "APG", "Assists", CREATION),
        _per_36("ast", "AST", "Assists", CREATION),
        MetricSpec(
            "assist_pct",
            "AST%",
            "Assist percentage",
            "Share of teammates' field goals the player assisted while on the court. "
            "Measured by the league from play-by-play.",
            CREATION,
            _PCT,
            _MEASURED,
        ),
        MetricSpec(
            "usage_pct",
            "USG%",
            "Usage percentage",
            "Share of team plays the player used - shots, free throws, turnovers - while "
            "on the court. Measured by the league from play-by-play.",
            CREATION,
            _PCT,
            _MEASURED,
            higher_is_better=None,
        ),
        _per_game("tov", "TOV", "Turnovers", CREATION, better=False),
        MetricSpec(
            "tov_pct",
            "TOV%",
            "Turnover percentage",
            "TOV / (FGA + 0.44 x FTA + TOV). Share of the player's own plays that end in a "
            "turnover.",
            CREATION,
            _PCT,
            higher_is_better=False,
        ),
        MetricSpec(
            "ast_to_tov",
            "AST/TO",
            "Assist-to-turnover ratio",
            "Assists divided by turnovers.",
            CREATION,
            decimals=2,
        ),
        # --- Rebounding ---------------------------------------------------------------
        _per_game("reb", "RPG", "Rebounds", REBOUNDING),
        _per_game("oreb", "ORB", "Offensive rebounds", REBOUNDING),
        _per_game("dreb", "DRB", "Defensive rebounds", REBOUNDING),
        _per_36("reb", "REB", "Rebounds", REBOUNDING),
        MetricSpec(
            "oreb_pct",
            "ORB%",
            "Offensive rebound percentage",
            "Share of available offensive rebounds the player took while on the court. "
            "Measured by the league.",
            REBOUNDING,
            _PCT,
            _MEASURED,
        ),
        MetricSpec(
            "dreb_pct",
            "DRB%",
            "Defensive rebound percentage",
            "Share of available defensive rebounds the player took while on the court. "
            "Measured by the league.",
            REBOUNDING,
            _PCT,
            _MEASURED,
        ),
        MetricSpec(
            "reb_pct",
            "REB%",
            "Rebound percentage",
            "Share of all available rebounds the player took while on the court. Measured "
            "by the league.",
            REBOUNDING,
            _PCT,
            _MEASURED,
        ),
        # --- Defense ------------------------------------------------------------------
        _per_game("stl", "SPG", "Steals", DEFENSE),
        _per_game("blk", "BPG", "Blocks", DEFENSE),
        _per_36("stl", "STL", "Steals", DEFENSE),
        _per_36("blk", "BLK", "Blocks", DEFENSE),
        MetricSpec(
            "stocks_per_36",
            "STK/36",
            "Steals plus blocks per 36 minutes",
            "Steals and blocks together, scaled to 36 minutes. A rough count of defensive "
            "events, not a measure of defensive quality.",
            DEFENSE,
        ),
        _per_36("pf", "PF", "Personal fouls", DEFENSE, better=False),
        MetricSpec(
            "def_rating",
            "DRtg",
            "On-court defensive rating",
            "Points the opponent scored per 100 possessions while the player was on the "
            "court. Measured by the league. It describes the lineups around the player as "
            "much as the player.",
            DEFENSE,
            provenance=_MEASURED,
            higher_is_better=False,
        ),
        # --- Impact -------------------------------------------------------------------
        MetricSpec(
            "off_rating",
            "ORtg",
            "On-court offensive rating",
            "Points the team scored per 100 possessions while the player was on the court. "
            "Measured by the league.",
            IMPACT,
            provenance=_MEASURED,
        ),
        MetricSpec(
            "net_rating",
            "NetRtg",
            "On-court net rating",
            "Team points scored minus allowed per 100 possessions while the player was on "
            "the court. Measured by the league.",
            IMPACT,
            _SIGNED,
            _MEASURED,
        ),
        MetricSpec(
            "on_off_net",
            "On/Off",
            "On/off net rating difference",
            "Team net rating with the player on the court minus its net rating with the "
            "player off it. For a player traded mid-season, each team's ratings are "
            "weighted by the minutes behind them.",
            IMPACT,
            _SIGNED,
        ),
        MetricSpec(
            "plus_minus_per_game",
            "+/-",
            "Plus-minus per game",
            "Team point margin while the player was on the court, per game played.",
            IMPACT,
            _SIGNED,
        ),
        MetricSpec(
            "player_impact_estimate",
            "PIE",
            "Player impact estimate",
            "The league's PIE: the player's share of the box-score events in the games played.",
            IMPACT,
            _PCT,
            _MEASURED,
        ),
    )
)

# Metrics that need only a box score and so can be computed for any span of games.
BOX_METRIC_KEYS: tuple[str, ...] = (
    "games_played",
    "minutes",
    "minutes_per_game",
    "pts_per_game",
    "pts_per_36",
    "fg_pct",
    "fg3_pct",
    "ft_pct",
    "efg_pct",
    "ts_pct",
    "fg3m_per_game",
    "fg3a_per_game",
    "fg3a_rate",
    "fta_per_game",
    "ft_rate",
    "ast_per_game",
    "ast_per_36",
    "tov_per_game",
    "tov_pct",
    "ast_to_tov",
    "reb_per_game",
    "oreb_per_game",
    "dreb_per_game",
    "reb_per_36",
    "stl_per_game",
    "blk_per_game",
    "stl_per_36",
    "blk_per_36",
    "stocks_per_36",
    "pf_per_36",
    "plus_minus_per_game",
)

_MEASURED_KEYS = tuple(
    spec.key
    for spec in PLAYER_METRICS
    if spec.provenance is _MEASURED and spec.key not in ("games_played", "games_started", "minutes")
)
IDENTITY_COLUMNS = (
    "player_id",
    "season",
    "season_type",
    "player_name",
    "team_id",
    "team_count",
    "age",
)


def box_metrics(totals: pd.DataFrame) -> pd.DataFrame:
    """Every metric that needs only box-score totals.

    ``totals`` holds ``games_played``, ``minutes``, ``plus_minus`` and the box-score
    counting columns, one row per player (or per anything else that has a box score).
    The result has one column per key in :data:`BOX_METRIC_KEYS`, on the same index.
    """
    games, minutes = totals["games_played"], totals["minutes"]
    metrics = pd.DataFrame(index=totals.index)
    metrics["games_played"] = games
    metrics["minutes"] = minutes
    metrics["minutes_per_game"] = f.per_game(minutes, games)

    metrics["pts_per_game"] = f.per_game(totals["pts"], games)
    metrics["pts_per_36"] = f.per_36(totals["pts"], minutes)
    metrics["fg_pct"] = f.shooting_pct(totals["fgm"], totals["fga"])
    metrics["fg3_pct"] = f.shooting_pct(totals["fg3m"], totals["fg3a"])
    metrics["ft_pct"] = f.shooting_pct(totals["ftm"], totals["fta"])
    metrics["efg_pct"] = f.effective_fg_pct(totals["fgm"], totals["fg3m"], totals["fga"])
    metrics["ts_pct"] = f.true_shooting_pct(totals["pts"], totals["fga"], totals["fta"])
    metrics["fg3m_per_game"] = f.per_game(totals["fg3m"], games)
    metrics["fg3a_per_game"] = f.per_game(totals["fg3a"], games)
    metrics["fg3a_rate"] = f.three_point_attempt_rate(totals["fg3a"], totals["fga"])
    metrics["fta_per_game"] = f.per_game(totals["fta"], games)
    metrics["ft_rate"] = f.free_throw_rate(totals["fta"], totals["fga"])

    metrics["ast_per_game"] = f.per_game(totals["ast"], games)
    metrics["ast_per_36"] = f.per_36(totals["ast"], minutes)
    metrics["tov_per_game"] = f.per_game(totals["tov"], games)
    metrics["tov_pct"] = f.turnover_pct(totals["tov"], totals["fga"], totals["fta"])
    metrics["ast_to_tov"] = f.assist_to_turnover(totals["ast"], totals["tov"])

    metrics["reb_per_game"] = f.per_game(totals["reb"], games)
    metrics["oreb_per_game"] = f.per_game(totals["oreb"], games)
    metrics["dreb_per_game"] = f.per_game(totals["dreb"], games)
    metrics["reb_per_36"] = f.per_36(totals["reb"], minutes)

    metrics["stl_per_game"] = f.per_game(totals["stl"], games)
    metrics["blk_per_game"] = f.per_game(totals["blk"], games)
    metrics["stl_per_36"] = f.per_36(totals["stl"], minutes)
    metrics["blk_per_36"] = f.per_36(totals["blk"], minutes)
    metrics["stocks_per_36"] = f.per_36(totals["stl"] + totals["blk"], minutes)
    metrics["pf_per_36"] = f.per_36(totals["pf"], minutes)

    metrics["plus_minus_per_game"] = f.per_game(totals["plus_minus"], games)
    return metrics[list(BOX_METRIC_KEYS)]


def combined_on_off(on_off: pd.DataFrame) -> pd.DataFrame:
    """Each player's on/off net rating difference for a season, across every team played for.

    Input is ``player_on_off``. For a player who appeared for several teams, the on-court
    ratings are averaged weighted by on-court minutes and the off-court ratings by
    off-court minutes, before the difference is taken. Returns ``on_off_net`` indexed by
    ``(player_id, season, season_type)``.
    """
    keys = ["player_id", "season", "season_type"]
    if on_off.empty:
        empty = pd.MultiIndex.from_arrays([[], [], []], names=keys)
        return pd.DataFrame({"on_off_net": pd.Series(dtype="float64")}, index=empty)

    frame = on_off[keys].copy()
    # A stint with no off-court minutes has no off-court rating to compare with.
    usable = on_off["off_court_net_rating"].notna() & on_off["on_court_net_rating"].notna()
    frame["on_minutes"] = on_off["on_court_minutes"].where(usable, 0.0)
    frame["off_minutes"] = on_off["off_court_minutes"].where(usable, 0.0)
    frame["on_weighted"] = (on_off["on_court_net_rating"] * on_off["on_court_minutes"]).where(
        usable, 0.0
    )
    frame["off_weighted"] = (on_off["off_court_net_rating"] * on_off["off_court_minutes"]).where(
        usable, 0.0
    )
    sums = frame.groupby(keys).sum()
    on = f.safe_divide(sums["on_weighted"], sums["on_minutes"])
    off = f.safe_divide(sums["off_weighted"], sums["off_minutes"])
    return pd.DataFrame({"on_off_net": on - off})


def player_season_metrics(
    player_seasons: pd.DataFrame,
    on_off: pd.DataFrame | None = None,
    season_games: pd.Series | None = None,
) -> pd.DataFrame:
    """One row per player-season with every metric in :data:`PLAYER_METRICS`.

    ``player_seasons`` and ``on_off`` are the tables of those names. ``season_games`` maps
    a season label to the number of games each team played in it, for the share of the
    season a player appeared in; without it that metric is missing.
    """
    seasons = player_seasons.reset_index(drop=True)
    metrics = box_metrics(seasons)

    metrics["games_started"] = seasons["games_started"]
    metrics["start_share"] = f.share(seasons["games_started"], seasons["games_played"])
    if season_games is None:
        metrics["games_played_share"] = f.NAN
    else:
        length = seasons["season"].map(season_games)
        # Only the regular season has a fixed length to measure against.
        is_regular = seasons["season_type"] == "regular"
        metrics["games_played_share"] = f.share(seasons["games_played"], length).where(is_regular)

    metrics["pts_per_100"] = f.per_100(seasons["pts"], seasons["possessions"])
    for key in _MEASURED_KEYS:
        metrics[key] = seasons[key].astype("float64")

    keys = ["player_id", "season", "season_type"]
    if on_off is None:
        metrics["on_off_net"] = f.NAN
    else:
        difference = combined_on_off(on_off)["on_off_net"]
        index = pd.MultiIndex.from_frame(seasons[keys])
        metrics["on_off_net"] = difference.reindex(index).to_numpy()

    identity = seasons[list(IDENTITY_COLUMNS)]
    return pd.concat([identity, metrics[list(PLAYER_METRICS.keys)]], axis=1)


def window_totals(
    game_logs: pd.DataFrame,
    *,
    last_games: int | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Box-score totals per player over a span of games.

    ``game_logs`` is ``player_game_logs`` (already narrowed to the season and season
    type wanted). The span is each player's most recent ``last_games`` games, a date
    range, or both: the date range is applied first. The result is indexed by
    ``player_id`` and holds what :func:`box_metrics` needs, plus the dates of the first
    and last game in the span.
    """
    if last_games is not None and last_games < 1:
        raise ValueError("last_games must be at least 1")
    logs = game_logs
    if start is not None:
        logs = logs[logs["game_date"] >= start]
    if end is not None:
        logs = logs[logs["game_date"] <= end]
    logs = logs.sort_values(["player_id", "game_date", "game_id"])
    if last_games is not None:
        logs = logs.groupby("player_id").tail(last_games)

    columns = {column: (column, "sum") for column in (*BOX_SCORE_COLUMNS, "minutes", "plus_minus")}
    return logs.groupby("player_id").agg(
        games_played=("game_id", "size"),
        first_game=("game_date", "min"),
        last_game=("game_date", "max"),
        **columns,
    )


def window_metrics(
    game_logs: pd.DataFrame,
    *,
    last_games: int | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Box metrics for each player over a span of games; see :func:`window_totals`."""
    totals = window_totals(game_logs, last_games=last_games, start=start, end=end)
    metrics = box_metrics(totals)
    metrics.insert(0, "first_game", totals["first_game"])
    metrics.insert(1, "last_game", totals["last_game"])
    return metrics


def recent_availability(
    player_logs: pd.DataFrame, team_games: pd.DataFrame, *, team_games_back: int = 20
) -> pd.DataFrame:
    """How many of the team's most recent games each player appeared in.

    Both frames are narrowed to one season and season type. A player's team is the one
    most recently appeared for. Returns ``team_id``, ``team_games``, ``games_played``
    and ``availability`` (their ratio), indexed by ``player_id``.
    """
    if team_games_back < 1:
        raise ValueError("team_games_back must be at least 1")
    columns = ["team_id", "team_games", "games_played", "availability"]
    if player_logs.empty:
        return pd.DataFrame(columns=columns, index=pd.Index([], name="player_id"))

    latest = player_logs.sort_values(["game_date", "game_id"]).groupby("player_id").tail(1)
    current_team = latest.set_index("player_id")["team_id"]

    recent = (
        team_games.sort_values(["game_date", "game_id"])
        .groupby("team_id")
        .tail(team_games_back)[["team_id", "game_id"]]
    )
    team_count = recent.groupby("team_id").size()
    played = player_logs.merge(recent, on=["team_id", "game_id"])
    played = played[played["team_id"] == played["player_id"].map(current_team)]
    appearances = played.groupby("player_id").size()

    result = pd.DataFrame({"team_id": current_team})
    result["team_games"] = result["team_id"].map(team_count).fillna(0).astype(int)
    result["games_played"] = appearances.reindex(result.index).fillna(0).astype(int)
    result["availability"] = f.share(result["games_played"], result["team_games"])
    return result[columns]


def rolling_metrics(
    game_logs: pd.DataFrame, *, games: int = 10, full_spans: bool = False
) -> pd.DataFrame:
    """Box metrics over each player's trailing ``games`` games, one row per game played.

    ``game_logs`` is ``player_game_logs`` narrowed to one season and season type. Each
    row describes the span ending with that game; early in a season the span is however
    many games the player has played so far, and ``games_played`` says how many that is.
    With ``full_spans`` those early rows are left out, so that every row covers exactly
    ``games`` games and the rows can be compared with one another.
    Returns ``player_id``, ``game_id`` and ``game_date`` followed by the box metrics.
    """
    if games < 1:
        raise ValueError("games must be at least 1")
    logs = game_logs.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)
    columns = [*BOX_SCORE_COLUMNS, "minutes", "plus_minus"]
    trailing = (
        logs.groupby("player_id")[columns]
        .rolling(games, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .sort_index()
    )
    trailing["games_played"] = (
        logs.groupby("player_id").cumcount().add(1).clip(upper=games).to_numpy()
    )
    metrics = box_metrics(trailing)
    rolling = pd.concat([logs[["player_id", "game_id", "game_date"]], metrics], axis=1)
    if full_spans:
        rolling = rolling[rolling["games_played"] == games].reset_index(drop=True)
    return rolling
