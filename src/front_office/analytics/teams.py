"""Team metrics: scoring, efficiency, the four factors, standings and league context.

A season's ratings, pace and possessions are the league's own, counted from play-by-play.
A span of games has no counted possessions, so there they are *estimated* from the box
scores and calibrated to the season: see :func:`possession_calibration`.
"""

from __future__ import annotations

import pandas as pd

from front_office.analytics import formulas as f
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS
from front_office.domain.tables.teams import ROUND_NAMES

RECORD = "Record"
SCORING = "Scoring"
EFFICIENCY = "Efficiency"
OFFENSE = "Offense: four factors"
DEFENSE = "Defense: four factors"
STYLE = "Style"

_MEASURED = Provenance.MEASURED
_PCT, _COUNT, _SIGNED = MetricFormat.PERCENT, MetricFormat.COUNT, MetricFormat.SIGNED

TEAM_METRICS = MetricCatalog(
    (
        # --- Record -------------------------------------------------------------------
        MetricSpec(
            "games_played",
            "GP",
            "Games played",
            "Games played.",
            RECORD,
            _COUNT,
            _MEASURED,
            higher_is_better=None,
        ),
        MetricSpec("wins", "W", "Wins", "Games won.", RECORD, _COUNT, _MEASURED),
        MetricSpec(
            "losses",
            "L",
            "Losses",
            "Games lost.",
            RECORD,
            _COUNT,
            _MEASURED,
            higher_is_better=False,
        ),
        MetricSpec(
            "win_pct",
            "W%",
            "Winning percentage",
            "Wins divided by games played.",
            RECORD,
            _PCT,
        ),
        # --- Scoring ------------------------------------------------------------------
        MetricSpec(
            "pts_per_game",
            "PPG",
            "Points per game",
            "Points scored divided by games played.",
            SCORING,
        ),
        MetricSpec(
            "opp_pts_per_game",
            "Opp PPG",
            "Points allowed per game",
            "Points allowed divided by games played.",
            SCORING,
            higher_is_better=False,
        ),
        MetricSpec(
            "point_diff_per_game",
            "Diff",
            "Point differential per game",
            "Points per game minus points allowed per game. It depends on pace: a fast team "
            "scores and allows more of both.",
            SCORING,
            _SIGNED,
        ),
        # --- Efficiency ---------------------------------------------------------------
        MetricSpec(
            "off_rating",
            "ORtg",
            "Offensive rating",
            "Points scored per 100 possessions. Published by the league for a season; "
            "estimated from box scores for a span of games.",
            EFFICIENCY,
            provenance=_MEASURED,
        ),
        MetricSpec(
            "def_rating",
            "DRtg",
            "Defensive rating",
            "Points allowed per 100 possessions. Published by the league for a season; "
            "estimated from box scores for a span of games.",
            EFFICIENCY,
            provenance=_MEASURED,
            higher_is_better=False,
        ),
        MetricSpec(
            "net_rating",
            "NetRtg",
            "Net rating",
            "Offensive rating minus defensive rating: point differential with pace removed.",
            EFFICIENCY,
            _SIGNED,
            _MEASURED,
        ),
        MetricSpec(
            "rel_off_rating",
            "rORtg",
            "Relative offensive rating",
            "Offensive rating minus the league's average offensive rating that season, "
            "which makes offenses comparable across eras.",
            EFFICIENCY,
            _SIGNED,
        ),
        MetricSpec(
            "rel_def_rating",
            "rDRtg",
            "Relative defensive rating",
            "The league's average offensive rating that season minus the team's defensive "
            "rating. Positive means better than average; comparable across eras.",
            EFFICIENCY,
            _SIGNED,
        ),
        MetricSpec(
            "ts_pct",
            "TS%",
            "True shooting percentage",
            "PTS / (2 x (FGA + 0.44 x FTA)). Scoring efficiency counting twos, threes and "
            "free throws together.",
            EFFICIENCY,
            _PCT,
        ),
        # --- Offense: four factors ----------------------------------------------------
        MetricSpec(
            "efg_pct",
            "eFG%",
            "Effective field goal percentage",
            "(FGM + 0.5 x 3PM) / FGA. Field goal percentage that credits a three as one and "
            "a half makes.",
            OFFENSE,
            _PCT,
        ),
        MetricSpec(
            "tov_pct",
            "TOV%",
            "Turnover rate",
            "Turnovers per possession.",
            OFFENSE,
            _PCT,
            higher_is_better=False,
        ),
        MetricSpec(
            "oreb_pct",
            "ORB%",
            "Offensive rebound percentage",
            "OREB / (OREB + opponent DREB): the share of its own misses a team rebounds. "
            "This is the standard four-factors definition; the league's site publishes a "
            "differently defined, higher figure.",
            OFFENSE,
            _PCT,
        ),
        MetricSpec(
            "ft_rate",
            "FTr",
            "Free throw rate",
            "Free throw attempts per field goal attempt: FTA / FGA.",
            OFFENSE,
            decimals=3,
        ),
        # --- Defense: four factors ----------------------------------------------------
        MetricSpec(
            "opp_efg_pct",
            "Opp eFG%",
            "Opponent effective field goal percentage",
            "Opponents' (FGM + 0.5 x 3PM) / FGA.",
            DEFENSE,
            _PCT,
            higher_is_better=False,
        ),
        MetricSpec(
            "opp_tov_pct",
            "Opp TOV%",
            "Opponent turnover rate",
            "Opponent turnovers per possession: how often the defense forces one.",
            DEFENSE,
            _PCT,
        ),
        MetricSpec(
            "dreb_pct",
            "DRB%",
            "Defensive rebound percentage",
            "DREB / (DREB + opponent OREB): the share of opponents' misses a team rebounds.",
            DEFENSE,
            _PCT,
        ),
        MetricSpec(
            "opp_ft_rate",
            "Opp FTr",
            "Opponent free throw rate",
            "Opponents' free throw attempts per field goal attempt.",
            DEFENSE,
            higher_is_better=False,
            decimals=3,
        ),
        # --- Style --------------------------------------------------------------------
        MetricSpec(
            "pace",
            "Pace",
            "Pace",
            "Possessions per 48 minutes. Published by the league for a season; estimated "
            "from box scores for a span of games.",
            STYLE,
            provenance=_MEASURED,
            higher_is_better=None,
        ),
        MetricSpec(
            "fg3a_rate",
            "3PAr",
            "Three-point attempt rate",
            "Share of field goal attempts taken from three: 3PA / FGA.",
            STYLE,
            _PCT,
            higher_is_better=None,
        ),
        MetricSpec(
            "fg3_pct",
            "3P%",
            "Three-point percentage",
            "Three-pointers made divided by attempted.",
            STYLE,
            _PCT,
        ),
        MetricSpec(
            "ast_pct",
            "AST%",
            "Assist percentage",
            "Share of made field goals that were assisted: AST / FGM.",
            STYLE,
            _PCT,
            higher_is_better=None,
        ),
    )
)

IDENTITY_COLUMNS = (
    "season",
    "team_id",
    "team_name",
    "team_abbreviation",
    "conference",
    "division",
    "conference_rank",
)
OUTCOME_COLUMNS = (
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
CHAMPION = "Champion"
LOST_PLAY_IN = "Lost Play-In"
MISSED_PLAYOFFS = "Missed playoffs"
POSTSEASON_RESULTS: tuple[str, ...] = (
    CHAMPION,
    *(f"Lost {name}" for name in reversed(ROUND_NAMES)),
    LOST_PLAY_IN,
    MISSED_PLAYOFFS,
)
"""How a season can end, best first."""

ESTIMATED_IN_A_WINDOW: tuple[str, ...] = (
    "off_rating",
    "def_rating",
    "net_rating",
    "pace",
    "tov_pct",
    "opp_tov_pct",
)
"""Metrics that rest on possessions: the league's count for a season, an estimate for a span."""

SEASON_ONLY: tuple[str, ...] = ("rel_off_rating", "rel_def_rating")
"""Metrics that compare a team with the whole league's season, so a span has none."""

WINDOW_METRIC_KEYS = tuple(key for key in TEAM_METRICS.keys if key not in SEASON_ONLY)

_OPPONENT_COLUMNS = tuple(f"opp_{column}" for column in BOX_SCORE_COLUMNS)
_TOTAL_COLUMNS = (
    "games_played",
    "wins",
    "losses",
    "possessions",
    "game_minutes",
    *BOX_SCORE_COLUMNS,
    *_OPPONENT_COLUMNS,
)


def _rates(totals: pd.DataFrame, possessions: pd.Series) -> pd.DataFrame:
    """The metrics that follow from totals, opponent totals and a possession count."""
    games = totals["games_played"]
    metrics = pd.DataFrame(index=totals.index)
    metrics["games_played"] = games
    metrics["wins"] = totals["wins"]
    metrics["losses"] = totals["losses"]
    metrics["win_pct"] = f.share(totals["wins"], games)

    metrics["pts_per_game"] = f.per_game(totals["pts"], games)
    metrics["opp_pts_per_game"] = f.per_game(totals["opp_pts"], games)
    metrics["point_diff_per_game"] = metrics["pts_per_game"] - metrics["opp_pts_per_game"]
    metrics["ts_pct"] = f.true_shooting_pct(totals["pts"], totals["fga"], totals["fta"])

    metrics["efg_pct"] = f.effective_fg_pct(totals["fgm"], totals["fg3m"], totals["fga"])
    metrics["tov_pct"] = f.share(totals["tov"], possessions)
    metrics["oreb_pct"] = f.rebound_pct(totals["oreb"], totals["opp_dreb"])
    metrics["ft_rate"] = f.free_throw_rate(totals["fta"], totals["fga"])

    metrics["opp_efg_pct"] = f.effective_fg_pct(
        totals["opp_fgm"], totals["opp_fg3m"], totals["opp_fga"]
    )
    metrics["opp_tov_pct"] = f.share(totals["opp_tov"], possessions)
    metrics["dreb_pct"] = f.rebound_pct(totals["dreb"], totals["opp_oreb"])
    metrics["opp_ft_rate"] = f.free_throw_rate(totals["opp_fta"], totals["opp_fga"])

    metrics["fg3a_rate"] = f.three_point_attempt_rate(totals["fg3a"], totals["fga"])
    metrics["fg3_pct"] = f.shooting_pct(totals["fg3m"], totals["fg3a"])
    metrics["ast_pct"] = f.share(totals["ast"], totals["fgm"])
    return metrics


# --- seasons -------------------------------------------------------------------------


def league_averages(team_seasons: pd.DataFrame) -> pd.DataFrame:
    """The league as a whole in each season, from pooled team totals.

    Indexed by season, with ``teams`` (how many there were) and one column per key in
    :data:`TEAM_METRICS`: the reference line for each team metric. Counts are per team.
    Every point scored is a point allowed, so the league's offensive and defensive
    ratings are the same number and its net rating is zero.
    """
    by_season = team_seasons["season"]
    columns = ["games_played", "wins", "losses", "minutes", "possessions"]
    columns += [*BOX_SCORE_COLUMNS, *_OPPONENT_COLUMNS]
    pooled = team_seasons[columns].astype("float64").groupby(by_season).sum()
    teams = by_season.groupby(by_season).size()

    averages = _rates(pooled, pooled["possessions"])
    for key in ("games_played", "wins", "losses"):
        averages[key] = f.safe_divide(pooled[key], teams)
    averages["off_rating"] = f.rating(pooled["pts"], pooled["possessions"])
    averages["def_rating"] = f.rating(pooled["opp_pts"], pooled["possessions"])
    averages["net_rating"] = averages["off_rating"] - averages["def_rating"]
    averages["rel_off_rating"] = 0.0
    averages["rel_def_rating"] = 0.0
    averages["pace"] = f.pace(pooled["possessions"], pooled["minutes"])

    result = averages[list(TEAM_METRICS.keys)]
    result.insert(0, "teams", teams)
    return result


def season_over_season(averages: pd.DataFrame) -> pd.DataFrame:
    """How each league average moved from the season before it.

    ``averages`` is :func:`league_averages`. Same index and metric columns; the first
    season has nothing before it and is missing throughout. A season is compared with
    the previous row, so ``averages`` should hold consecutive seasons.
    """
    return averages[list(TEAM_METRICS.keys)].sort_index().diff()


def team_season_metrics(team_seasons: pd.DataFrame) -> pd.DataFrame:
    """One row per team-season: identity, every metric in :data:`TEAM_METRICS`, outcomes.

    Ratings and pace are the league's published figures. Relative ratings compare each
    team with the league average of its own season, so every season that appears in
    ``team_seasons`` must be there in full.
    """
    seasons = team_seasons.reset_index(drop=True)
    metrics = _rates(seasons, seasons["possessions"])
    for key in ("off_rating", "def_rating", "net_rating", "pace"):
        metrics[key] = seasons[key].astype("float64")

    league_off_rating = seasons["season"].map(league_averages(seasons)["off_rating"])
    metrics["rel_off_rating"] = metrics["off_rating"] - league_off_rating
    metrics["rel_def_rating"] = league_off_rating - metrics["def_rating"]

    return pd.concat(
        [
            seasons[list(IDENTITY_COLUMNS)],
            metrics[list(TEAM_METRICS.keys)],
            seasons[list(OUTCOME_COLUMNS)],
        ],
        axis=1,
    )


def standings(team_metrics: pd.DataFrame) -> pd.DataFrame:
    """The teams of one season in conference order, with games behind the leader.

    ``team_metrics`` is :func:`team_season_metrics` for a single season. The order is
    the league's published conference rank, which already applies its tie-breakers and,
    in older seasons, its seeding of division winners.
    """
    if team_metrics["season"].nunique() > 1:
        raise ValueError("standings cover one season at a time")
    table = team_metrics.sort_values(["conference", "conference_rank", "team_name"])
    table = table.reset_index(drop=True)
    leader = table.drop_duplicates("conference").set_index("conference")
    ahead_in_wins = table["conference"].map(leader["wins"]) - table["wins"]
    behind_in_losses = table["losses"] - table["conference"].map(leader["losses"])
    table["games_behind"] = (ahead_in_wins + behind_in_losses) / 2
    return table


def postseason_result(teams: pd.DataFrame) -> pd.Series:
    """How each team's season ended, in words: one of :data:`POSTSEASON_RESULTS`.

    ``teams`` carries the outcome columns of ``team_seasons``. Missing while the
    season's postseason is undecided.
    """
    result = pd.Series(pd.NA, index=teams.index, dtype="str")
    result[teams["made_playoffs"].notna()] = MISSED_PLAYOFFS
    result[teams["made_play_in"].fillna(False).astype(bool)] = LOST_PLAY_IN
    for round_number, name in enumerate(ROUND_NAMES, start=1):
        result[(teams["playoff_round_reached"] == round_number).fillna(False)] = f"Lost {name}"
    result[teams["won_championship"].fillna(False).astype(bool)] = CHAMPION
    return result


def record_splits(team_games: pd.DataFrame, *, recent: int = 10) -> pd.DataFrame:
    """Each team's record at home, on the road and lately, and its current streak.

    ``team_games`` is narrowed to one season and season type. A neutral-site game counts
    toward neither the home nor the road record. Indexed by ``team_id``; ``streak`` is
    the run of results the team is on, positive for wins and negative for losses.
    """
    if recent < 1:
        raise ValueError("recent must be at least 1")
    columns = ["home_wins", "home_losses", "road_wins", "road_losses"]
    columns += ["recent_wins", "recent_losses", "streak"]
    games = team_games[team_games["won"].notna()]
    if games.empty:
        return pd.DataFrame(columns=columns, index=pd.Index([], name="team_id"), dtype="int64")

    games = games.sort_values(["team_id", "game_date", "game_id"])
    won = games["won"].astype(bool)
    home = games["is_home"].astype(bool)
    road = ~home & ~games["is_neutral_site"].astype(bool)
    flags = pd.DataFrame(
        {
            "home_wins": home & won,
            "home_losses": home & ~won,
            "road_wins": road & won,
            "road_losses": road & ~won,
        }
    )
    splits = flags.astype(int).groupby(games["team_id"]).sum()

    latest = games.groupby("team_id").tail(recent)
    recent_wins = latest["won"].astype(bool).astype(int).groupby(latest["team_id"]).sum()
    splits["recent_wins"] = recent_wins
    splits["recent_losses"] = latest.groupby("team_id").size() - recent_wins
    splits["streak"] = won.astype(int).groupby(games["team_id"]).agg(_streak)
    return splits[columns]


def _streak(results: pd.Series) -> int:
    """Length of the run a sequence of results (1 won, 0 lost) ends on, negative for losses."""
    outcomes = results.tolist()
    length = 0
    for outcome in reversed(outcomes):
        if outcome != outcomes[-1]:
            break
        length += 1
    return length if outcomes[-1] else -length


# --- spans of games -----------------------------------------------------------------


def _mean_estimate(totals: pd.DataFrame) -> pd.Series:
    """Estimated possessions, averaged over a team's own box score and its opponent's."""
    own = f.estimated_possessions(totals["fga"], totals["fta"], totals["oreb"], totals["tov"])
    opponent = f.estimated_possessions(
        totals["opp_fga"], totals["opp_fta"], totals["opp_oreb"], totals["opp_tov"]
    )
    return (own + opponent) / 2


def possession_calibration(team_seasons: pd.DataFrame) -> pd.Series:
    """Per season, the factor that scales estimated possessions to counted ones.

    The box-score estimate (FGA + 0.44 x FTA - OREB + TOV, averaged over a team and its
    opponent) runs about 1.6% above the league's counted possessions, and the gap drifts
    from season to season. Dividing the league's counted total for a season by its
    estimated total gives a factor that removes the bias: with it the estimate is within
    0.2% of the count for a typical team-season. Indexed by season.
    """
    by_season = team_seasons["season"]
    counted = team_seasons["possessions"].astype("float64").groupby(by_season).sum()
    estimated = _mean_estimate(team_seasons).groupby(by_season).sum()
    return f.safe_divide(counted, estimated).rename("possession_calibration")


def with_opponent_box(team_games: pd.DataFrame) -> pd.DataFrame:
    """``team_games`` with the opponent's box score beside each team's own.

    Pairs the two rows of every game and adds an ``opp_`` column for each box-score
    statistic. Both rows of every game must be present.
    """
    other = team_games[["game_id", "team_id", *BOX_SCORE_COLUMNS]].rename(
        columns={"team_id": "opponent_team_id"}
        | dict(zip(BOX_SCORE_COLUMNS, _OPPONENT_COLUMNS, strict=True))
    )
    games = team_games.drop(columns="opp_pts").merge(
        other, on=["game_id", "opponent_team_id"], how="left", validate="one_to_one"
    )
    if games["opp_pts"].isna().any():
        lonely = sorted(games.loc[games["opp_pts"].isna(), "game_id"].unique())
        raise ValueError(f"games without the opponent's row: {lonely[:5]}")
    return games.astype({column: "int64" for column in _OPPONENT_COLUMNS})


def _game_totals(team_games: pd.DataFrame, calibration: pd.Series | None) -> pd.DataFrame:
    """Finished games in each team's playing order, with what :func:`_window_rates` sums."""
    games = with_opponent_box(team_games)
    games = games[games["won"].notna()]
    games = games.sort_values(["team_id", "game_date", "game_id"]).reset_index(drop=True)

    possessions = _mean_estimate(games)
    if calibration is not None:
        possessions = possessions * games["season"].map(calibration).astype("float64")
    won = games["won"].astype(bool)
    return games.assign(
        games_played=1,
        wins=won.astype(int),
        losses=(~won).astype(int),
        possessions=possessions,
        # Player-minutes over the five players on the floor is game time.
        game_minutes=games["minutes"] / 5,
    )


def _window_rates(totals: pd.DataFrame) -> pd.DataFrame:
    """Every metric a span of games supports, from summed game totals."""
    metrics = _rates(totals, totals["possessions"])
    metrics["off_rating"] = f.rating(totals["pts"], totals["possessions"])
    metrics["def_rating"] = f.rating(totals["opp_pts"], totals["possessions"])
    metrics["net_rating"] = metrics["off_rating"] - metrics["def_rating"]
    metrics["pace"] = f.pace(totals["possessions"], totals["game_minutes"])
    return metrics[list(WINDOW_METRIC_KEYS)]


def team_window_metrics(
    team_games: pd.DataFrame,
    calibration: pd.Series | None = None,
    *,
    last_games: int | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Team metrics over a span of games, with possessions estimated from box scores.

    ``team_games`` is narrowed to one season and season type and holds both teams' rows
    for every game. The span is each team's most recent ``last_games`` games, a date
    range, or both: the date range is applied first. ``calibration`` is
    :func:`possession_calibration`; without it possessions are the raw estimate, and a
    season it does not cover has no possessions at all.

    Indexed by ``team_id``: the dates of the first and last game of the span, then the
    metrics in :data:`WINDOW_METRIC_KEYS`. Those in :data:`ESTIMATED_IN_A_WINDOW` are
    **estimates** here. Relative ratings are absent: they need the whole league's season.
    """
    if last_games is not None and last_games < 1:
        raise ValueError("last_games must be at least 1")
    games = _game_totals(team_games, calibration)
    if start is not None:
        games = games[games["game_date"] >= start]
    if end is not None:
        games = games[games["game_date"] <= end]
    if last_games is not None:
        games = games.groupby("team_id").tail(last_games)

    grouped = games.groupby("team_id")
    # min_count: a span whose possessions are all unknown has none, not zero.
    totals = grouped[list(_TOTAL_COLUMNS)].sum(min_count=1)
    metrics = _window_rates(totals)
    metrics.insert(0, "first_game", grouped["game_date"].min())
    metrics.insert(1, "last_game", grouped["game_date"].max())
    return metrics


def rolling_team_metrics(
    team_games: pd.DataFrame,
    calibration: pd.Series | None = None,
    *,
    games: int = 10,
    full_spans: bool = False,
) -> pd.DataFrame:
    """Team metrics over each team's trailing ``games`` games, one row per game played.

    The inputs are those of :func:`team_window_metrics`. Each row describes the span
    ending with that game; early in a season the span is however many games the team
    has played so far, and ``games_played`` says how many that is. With ``full_spans``
    those early rows are left out, so that every row covers exactly ``games`` games.
    With ``games=1`` each row is a single game. Returns ``team_id``, ``game_id`` and
    ``game_date`` followed by the metrics in :data:`WINDOW_METRIC_KEYS`.
    """
    if games < 1:
        raise ValueError("games must be at least 1")
    played = _game_totals(team_games, calibration)
    trailing = (
        played.groupby("team_id")[list(_TOTAL_COLUMNS)]
        .rolling(games, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .sort_index()
    )
    metrics = _window_rates(trailing)
    counts = ["games_played", "wins", "losses"]
    metrics[counts] = metrics[counts].astype("int64")
    rolling = pd.concat([played[["team_id", "game_id", "game_date"]], metrics], axis=1)
    if full_spans:
        rolling = rolling[rolling["games_played"] == games].reset_index(drop=True)
    return rolling
