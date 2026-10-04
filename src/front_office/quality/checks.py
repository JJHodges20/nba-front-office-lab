"""Cross-table data-quality checks.

A data contract proves each table is well-formed on its own. These checks prove the
tables agree with each other: that a season's record matches its games, that a box score
adds up, that a playoff bracket is a bracket. Each check counts what it examined and
what failed, and shows a few examples; none of them changes any data.

Severity says what a failure means:

* ``error`` - the data contradicts itself and should not be trusted until explained.
* ``warning`` - two sources disagree by more than their usual small amount, or a known
  kind of source glitch is present. Worth a look, not a reason to stop.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from front_office.domain.schema import TableContract
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS
from front_office.domain.tables.value import PART_COLUMNS

Tables = Mapping[str, pd.DataFrame]

MAX_EXAMPLES = 5

# Season totals and summed game logs are published separately and receive stat
# corrections separately. Across thirty seasons they never differ by more than 1.2%.
TOTALS_TOLERANCE = 0.02
# Published ratings are rounded to one decimal place.
RATING_TOLERANCE = 0.1
# Game-log minutes are whole minutes; a season total is exact.
MINUTES_ROUNDING_PER_GAME = 0.51
# A team's minutes in a game are exact; each player's are rounded to the whole minute.
MINUTES_ROUNDING_PER_PLAYER = 0.5
# The league corrects a player's season totals and box scores separately. Across thirty
# seasons the two never differ by more than one game or four points; more than this is
# a fault in the lab until it is explained.
PLAYER_GAMES_TOLERANCE = 1
PLAYER_POINTS_TOLERANCE = 5
# Three team box scores in thirty seasons disagree with their players' lines, by at most
# seven points: one player listed with the opponent, one with four points too many.
TEAM_POINTS_TOLERANCE = 10
# The largest contracts start at 35% of the cap and grow 8% a year; the smallest
# (two-way, ten-day) are a few tenths of a percent. Outside this band, suspect a typo.
MAX_PLAUSIBLE_CAP_SHARE = 0.45
MIN_PLAUSIBLE_CAP_SHARE = 0.0002
# A team carries 14-15 standard contracts in season and up to 21 players in the offseason.
MIN_PLAUSIBLE_ROSTER = 10
MAX_PLAUSIBLE_ROSTER = 21
# Modeled values are sums of floating-point terms; further apart than this is a fault.
VALUE_TOLERANCE = 1e-6

ROUND_SIZES = {1: 8, 2: 4, 3: 2, 4: 1}


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class CheckResult:
    check: str
    table: str
    description: str
    severity: Severity
    examined: int
    failures: int
    examples: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.failures == 0


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    table: str
    description: str
    severity: Severity
    run: Callable[[Tables], tuple[int, pd.DataFrame]]
    """Returns how many items were examined and a frame with one row per failure."""

    def evaluate(self, tables: Tables) -> CheckResult:
        examined, failing = self.run(tables)
        examples = tuple(
            ", ".join(f"{column}={_show(value)}" for column, value in row.items())
            for row in failing.head(MAX_EXAMPLES).to_dict("records")
        )
        return CheckResult(
            f"{self.table}.{self.name}",
            self.table,
            self.description,
            self.severity,
            examined,
            len(failing),
            examples,
        )


def _show(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, float | np.floating):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _failing(
    frame: pd.DataFrame, mask: pd.Series, columns: Sequence[str], **extra: pd.Series
) -> pd.DataFrame:
    """The rows of ``frame`` selected by ``mask``, with extra columns alongside.

    ``extra`` series share ``frame``'s index. They are attached by position: assigning
    an index-aligned series to an empty selection would otherwise make pandas invent a
    row for every label in the series.
    """
    chosen = mask.fillna(True).to_numpy(dtype=bool)
    failing = frame.loc[chosen, list(columns)].copy()
    for name, series in extra.items():
        failing[name] = series.to_numpy()[chosen]
    return failing.reset_index() if frame.index.names != [None] else failing


def run_checks(tables: Tables, checks: Sequence[Check] | None = None) -> list[CheckResult]:
    """Evaluate every check against the given tables."""
    return [check.evaluate(tables) for check in (checks if checks is not None else CHECKS)]


def reference_checks(contracts: Sequence[TableContract]) -> list[Check]:
    """One check per declared foreign key: every value must exist in the table it points at.

    A key that points at a table outside ``contracts`` is not checked here.
    """
    present = {contract.name for contract in contracts}
    checks = []
    for contract in contracts:
        for column in contract.fields:
            if column.references is None:
                continue
            target_table, target_column = column.references.split(".")
            if target_table not in present:
                continue

            def run(
                tables: Tables,
                table: str = contract.name,
                column: str = column.name,
                target_table: str = target_table,
                target_column: str = target_column,
            ) -> tuple[int, pd.DataFrame]:
                values = tables[table][column].dropna()
                known = set(tables[target_table][target_column])
                unknown = values[~values.isin(known)]
                counts = unknown.value_counts().rename_axis(column).reset_index(name="rows")
                return len(values), counts.sort_values(column)

            checks.append(
                Check(
                    f"{column.name}_exists",
                    contract.name,
                    f"Every {column.name} exists in {target_table}.",
                    Severity.ERROR,
                    run,
                )
            )
    return checks


# --- team games ---------------------------------------------------------------------


def _games_are_paired(tables: Tables) -> tuple[int, pd.DataFrame]:
    games = tables["team_games"]
    other = games[
        [
            "game_id",
            "team_id",
            "opponent_team_id",
            "pts",
            "opp_pts",
            "is_home",
            "is_neutral_site",
            "won",
        ]
    ]
    pairs = other.merge(
        other,
        left_on=["game_id", "opponent_team_id"],
        right_on=["game_id", "team_id"],
        how="left",
        suffixes=("", "_other"),
    )
    # A row whose opponent has no row of its own gets nulls from the merge; it is
    # unpaired, and the remaining comparisons must not trip over those nulls.
    unpaired = pairs["team_id_other"].isna().to_numpy()
    home = pairs["is_home"].to_numpy(dtype=bool)
    other_home = pairs["is_home_other"].astype("boolean").fillna(False).to_numpy(dtype=bool)
    neutral = pairs["is_neutral_site"].to_numpy(dtype=bool)
    won = pairs["won"].astype("boolean")
    other_won = pairs["won_other"].astype("boolean")
    same_result = (won == other_won).fillna(False).to_numpy(dtype=bool)
    mirrored = (pairs["opponent_team_id_other"] == pairs["team_id"]) & (
        pairs["opp_pts"] == pairs["pts_other"]
    )
    broken = (
        unpaired
        | ~mirrored.fillna(False).to_numpy(dtype=bool)
        | (home & other_home)
        # Exactly one team is at home, unless the site is neutral and neither is.
        | (neutral != (~home & ~other_home))
        | same_result
    )
    sizes = games.groupby("game_id")["team_id"].transform("size")
    broken = broken | (sizes != 2).to_numpy()
    return len(games), games.loc[broken, ["game_id", "team_id", "opponent_team_id"]]


def _box_scores_are_possible(tables: Tables) -> tuple[int, pd.DataFrame]:
    games = tables["team_games"]
    impossible = (
        (games["reb"] != games["oreb"] + games["dreb"])
        | (games["fgm"] > games["fga"])
        | (games["fg3m"] > games["fg3a"])
        | (games["ftm"] > games["fta"])
        | (games["fg3m"] > games["fgm"])
        | (games["fg3a"] > games["fga"])
    )
    return len(games), games.loc[impossible, ["game_id", "team_id"]]


def _points_add_up(tables: Tables) -> tuple[int, pd.DataFrame]:
    games = tables["team_games"]
    scored = 2 * games["fgm"] + games["fg3m"] + games["ftm"]
    wrong = games["pts"] != scored
    return len(games), _failing(games, wrong, ["game_id", "team_id", "pts"], from_shots=scored)


def _results_match_scores(tables: Tables) -> tuple[int, pd.DataFrame]:
    games = tables["team_games"]
    decided = games[games["won"].notna()]
    wrong = decided["won"].astype(bool) != (decided["pts"] > decided["opp_pts"])
    tied = decided["pts"] == decided["opp_pts"]
    return len(decided), decided.loc[wrong | tied, ["game_id", "team_id", "pts", "opp_pts", "won"]]


def _minutes_fit_game_length(tables: Tables) -> tuple[int, pd.DataFrame]:
    games = tables["team_games"]
    played = games[games["won"].notna()]
    # 240 player-minutes in regulation and 25 more for each overtime period.
    odd = (played["minutes"] < 240) | ((played["minutes"] - 240) % 25 != 0)
    return len(played), played.loc[odd, ["game_id", "team_id", "minutes"]]


# --- team seasons -------------------------------------------------------------------


def _regular_season_sums(tables: Tables) -> pd.DataFrame:
    games = tables["team_games"]
    regular = games[games["season_type"] == "regular"]
    return regular.groupby(["season", "team_id"]).agg(
        games=("game_id", "size"),
        wins=("won", lambda won: int(won.fillna(False).astype(bool).sum())),
        decided=("won", lambda won: int(won.notna().sum())),
        opp_pts=("opp_pts", "sum"),
        **{column: (column, "sum") for column in BOX_SCORE_COLUMNS},
    )


def _records_match_games(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["team_seasons"].set_index(["season", "team_id"])
    sums = _regular_season_sums(tables).reindex(seasons.index)
    wrong = (
        (seasons["wins"] + seasons["losses"] != seasons["games_played"])
        | (seasons["games_played"] != sums["decided"])
        | (seasons["wins"] != sums["wins"])
    )
    failing = _failing(
        seasons,
        wrong,
        ["games_played", "wins", "losses"],
        games_in_logs=sums["decided"],
        wins_in_logs=sums["wins"],
    )
    return len(seasons), failing


def _totals_close_to_games(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["team_seasons"].set_index(["season", "team_id"])
    sums = _regular_season_sums(tables).reindex(seasons.index)
    rows = []
    for column in (*BOX_SCORE_COLUMNS, "opp_pts"):
        published = seasons[column].astype("float64")
        summed = sums[column].astype("float64")
        gap = (published - summed).abs()
        too_far = gap > np.maximum(TOTALS_TOLERANCE * published, 3)
        for (season, team_id), difference in gap[too_far.fillna(True)].items():
            rows.append(
                {
                    "season": season,
                    "team_id": team_id,
                    "stat": column,
                    "published": published[(season, team_id)],
                    "summed_from_games": summed[(season, team_id)],
                    "gap": difference,
                }
            )
    columns = ["season", "team_id", "stat", "published", "summed_from_games", "gap"]
    return len(seasons), pd.DataFrame(rows, columns=columns)


def _league_is_balanced(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["team_seasons"]
    totals = seasons.groupby("season").agg(
        wins=("wins", "sum"),
        losses=("losses", "sum"),
        pts=("pts", "sum"),
        opp_pts=("opp_pts", "sum"),
    )
    unbalanced = (totals["wins"] != totals["losses"]) | (totals["pts"] != totals["opp_pts"])
    return len(totals), totals[unbalanced].reset_index()


def _ratings_are_consistent(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["team_seasons"]
    from_totals = 100 * seasons["pts"] / seasons["possessions"]
    off_gap = (from_totals - seasons["off_rating"]).abs()
    net_gap = (seasons["off_rating"] - seasons["def_rating"] - seasons["net_rating"]).abs()
    wrong = (off_gap > RATING_TOLERANCE) | (net_gap > RATING_TOLERANCE + 0.01)
    failing = _failing(
        seasons,
        wrong,
        ["season", "team_id", "off_rating", "def_rating", "net_rating"],
        points_per_100_possessions=from_totals.round(2),
    )
    return len(seasons), failing


def _outcomes_form_a_postseason(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["team_seasons"]
    finished = seasons[seasons["won_championship"].notna()]
    summary = finished.groupby("season").agg(
        champions=("won_championship", "sum"),
        finalists=("made_finals", "sum"),
        conference_finalists=("made_conference_finals", "sum"),
        playoff_teams=("made_playoffs", "sum"),
    )
    wrong = (
        (summary["champions"] != 1)
        | (summary["finalists"] != 2)
        | (summary["conference_finalists"] != 4)
        | (summary["playoff_teams"] != 16)
    )
    return len(summary), summary[wrong].astype(int).reset_index()


def _conference_ranks_are_distinct(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["team_seasons"]
    placed = seasons[seasons["conference"].notna() & seasons["conference_rank"].notna()]
    examined = 0
    rows = []
    for (season, conference), teams in placed.groupby(["season", "conference"], sort=True):
        examined += 1
        ranks = sorted(teams["conference_rank"].astype(int))
        if ranks != list(range(1, len(ranks) + 1)):
            shared = sorted({rank for rank in ranks if ranks.count(rank) > 1})
            rows.append(
                {
                    "season": season,
                    "conference": conference,
                    "teams": len(ranks),
                    "shared_places": " and ".join(str(rank) for rank in shared) or "none",
                    "last_place": ranks[-1],
                }
            )
    columns = ["season", "conference", "teams", "shared_places", "last_place"]
    return examined, pd.DataFrame(rows, columns=columns)


# --- playoffs -----------------------------------------------------------------------


def _brackets_are_complete(tables: Tables) -> tuple[int, pd.DataFrame]:
    series = tables["playoff_results"]
    finished = series.groupby("season").filter(
        lambda season: bool(((season["round"] == 4) & season["is_complete"]).any())
    )
    counts = finished.groupby(["season", "round"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=list(ROUND_SIZES), fill_value=0)
    wrong = (counts != pd.Series(ROUND_SIZES)).any(axis=1)
    open_series = finished[~finished["is_complete"]].groupby("season").size()
    wrong = wrong | counts.index.isin(open_series.index)
    return len(counts), counts[wrong].rename(columns=lambda r: f"round_{r}").reset_index()


def _winners_advance(tables: Tables) -> tuple[int, pd.DataFrame]:
    series = tables["playoff_results"]
    rows = []
    examined = 0
    for season, season_series in series.groupby("season"):
        for playoff_round in (2, 3, 4):
            entrants = season_series[season_series["round"] == playoff_round]
            winners = set(
                season_series.loc[season_series["round"] == playoff_round - 1, "winner_team_id"]
                .dropna()
                .astype(int)
            )
            for row in entrants.itertuples():
                examined += 1
                for team_id in (row.team_a_id, row.team_b_id):
                    if int(team_id) not in winners:
                        rows.append({"season": season, "round": playoff_round, "team_id": team_id})
    return examined, pd.DataFrame(rows, columns=["season", "round", "team_id"])


# --- players ------------------------------------------------------------------------


def _player_log_sums(tables: Tables) -> pd.DataFrame:
    return (
        tables["player_game_logs"]
        .groupby(["player_id", "season", "season_type"])
        .agg(games=("game_id", "size"), pts=("pts", "sum"), minutes=("minutes", "sum"))
    )


def _seasons_with_logs(tables: Tables) -> pd.DataFrame:
    """Player-season rows for the seasons and season types that have game logs."""
    logs = tables["player_game_logs"]
    covered = logs[["season", "season_type"]].drop_duplicates()
    return tables["player_seasons"].merge(covered, on=["season", "season_type"])


def _player_totals_against_logs(tables: Tables, *, exact: bool) -> tuple[int, pd.DataFrame]:
    seasons = _seasons_with_logs(tables).set_index(["player_id", "season", "season_type"])
    sums = _player_log_sums(tables).reindex(seasons.index)
    games_gap = (seasons["games_played"] - sums["games"]).abs()
    points_gap = (seasons["pts"] - sums["pts"]).abs()
    if exact:
        wrong = (games_gap != 0) | (points_gap != 0)
    else:
        allowed = np.maximum(TOTALS_TOLERANCE * seasons["pts"], PLAYER_POINTS_TOLERANCE)
        wrong = (games_gap > PLAYER_GAMES_TOLERANCE) | (points_gap > allowed)
    failing = _failing(
        seasons,
        # A player with no log at all has nothing to compare: that is a contradiction.
        wrong | sums["games"].isna(),
        ["player_name", "games_played", "pts"],
        games_in_logs=sums["games"],
        pts_in_logs=sums["pts"],
    )
    return len(seasons), failing


def _player_games_match_logs(tables: Tables) -> tuple[int, pd.DataFrame]:
    return _player_totals_against_logs(tables, exact=True)


def _player_games_close_to_logs(tables: Tables) -> tuple[int, pd.DataFrame]:
    return _player_totals_against_logs(tables, exact=False)


def _player_minutes_close_to_logs(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = _seasons_with_logs(tables).set_index(["player_id", "season", "season_type"])
    sums = _player_log_sums(tables).reindex(seasons.index)
    gap = (seasons["minutes"] - sums["minutes"]).abs()
    wrong = gap > MINUTES_ROUNDING_PER_GAME * seasons["games_played"]
    failing = _failing(
        seasons,
        wrong.fillna(False),
        ["player_name", "games_played", "minutes"],
        minutes_in_logs=sums["minutes"],
    )
    return len(seasons), failing


def _team_games_with_player_sums(tables: Tables) -> pd.DataFrame:
    """Each team game that has player rows, with what those rows add up to."""
    by_team = (
        tables["player_game_logs"]
        .groupby(["game_id", "team_id"])
        .agg(player_pts=("pts", "sum"), player_minutes=("minutes", "sum"), players=("pts", "size"))
    )
    games = tables["team_games"].set_index(["game_id", "team_id"])[["pts", "minutes"]]
    return games.join(by_team, how="inner")


def _player_points_sum_to_team_points(tables: Tables) -> tuple[int, pd.DataFrame]:
    joined = _team_games_with_player_sums(tables)
    wrong = joined["pts"] != joined["player_pts"]
    return len(joined), joined.loc[wrong, ["pts", "player_pts"]].reset_index()


def _player_points_close_to_team_points(tables: Tables) -> tuple[int, pd.DataFrame]:
    joined = _team_games_with_player_sums(tables)
    wrong = (joined["pts"] - joined["player_pts"]).abs() > TEAM_POINTS_TOLERANCE
    return len(joined), joined.loc[wrong, ["pts", "player_pts"]].reset_index()


def _player_minutes_sum_to_team_minutes(tables: Tables) -> tuple[int, pd.DataFrame]:
    joined = _team_games_with_player_sums(tables)
    gap = (joined["minutes"] - joined["player_minutes"]).abs()
    wrong = gap > MINUTES_ROUNDING_PER_PLAYER * joined["players"]
    return len(joined), joined.loc[wrong, ["minutes", "player_minutes", "players"]].reset_index()


def _logged_games_have_players(tables: Tables) -> tuple[int, pd.DataFrame]:
    logs = tables["player_game_logs"]
    covered = logs[["season", "season_type"]].drop_duplicates()
    games = tables["team_games"].merge(covered, on=["season", "season_type"])
    present = set(zip(logs["game_id"], logs["team_id"], strict=True))
    missing = [key not in present for key in zip(games["game_id"], games["team_id"], strict=True)]
    return len(games), games.loc[missing, ["game_id", "team_id", "season", "season_type"]]


def _starts_within_games(tables: Tables) -> tuple[int, pd.DataFrame]:
    seasons = tables["player_seasons"]
    known = seasons[seasons["games_started"].notna()]
    wrong = known["games_started"] > known["games_played"]
    columns = ["player_id", "season", "season_type", "player_name", "games_played", "games_started"]
    return len(known), known.loc[wrong, columns]


# --- contracts ----------------------------------------------------------------------


def _contract_totals_match_years(tables: Tables) -> tuple[int, pd.DataFrame]:
    contracts = tables["contracts"].set_index("contract_id")
    years = (
        tables["contract_years"]
        .groupby("contract_id")
        .agg(
            total=("salary", "sum"),
            seasons=("season", "size"),
            first=("season", "min"),
            last=("season", "max"),
        )
        .reindex(contracts.index)
    )
    wrong = (
        (contracts["total_salary"] != years["total"])
        | (contracts["seasons"] != years["seasons"])
        | (contracts["first_season"] != years["first"])
        | (contracts["last_season"] != years["last"])
    )
    failing = _failing(
        contracts,
        wrong,
        ["player_name", "total_salary", "seasons"],
        total_in_years=years["total"],
        seasons_in_years=years["seasons"],
    )
    return len(contracts), failing


def _cap_shares_are_consistent(tables: Tables) -> tuple[int, pd.DataFrame]:
    years = tables["contract_years"]
    caps = tables["salary_cap_rules"].set_index("season")["salary_cap"]
    cap = years["season"].map(caps).astype("float64")
    expected = years["salary"] / cap
    has_cap = cap.notna()
    stated = years["salary_cap_pct"]
    wrong = (has_cap & ~((stated - expected).abs() < 1e-9)) | (~has_cap & stated.notna())
    failing = _failing(
        years, wrong, ["contract_id", "season", "salary", "salary_cap_pct"], expected=expected
    )
    return len(years), failing


def _one_active_contract_per_player_season(tables: Tables) -> tuple[int, pd.DataFrame]:
    statuses = tables["contracts"][["contract_id", "status"]]
    years = tables["contract_years"].merge(statuses, on="contract_id")
    active = years[years["status"] == "active"]
    counts = active.groupby(["player_id", "season"]).size().rename("active_contracts")
    return len(counts), counts[counts > 1].reset_index()


def _salaries_are_plausible(tables: Tables) -> tuple[int, pd.DataFrame]:
    years = tables["contract_years"]
    known = years[years["salary_cap_pct"].notna()]
    odd = (known["salary_cap_pct"] > MAX_PLAUSIBLE_CAP_SHARE) | (
        known["salary_cap_pct"] < MIN_PLAUSIBLE_CAP_SHARE
    )
    return len(known), known.loc[odd, ["contract_id", "season", "salary", "salary_cap_pct"]]


def _teams_have_plausible_rosters(tables: Tables) -> tuple[int, pd.DataFrame]:
    years = tables["contract_years"]
    if years.empty:
        return 0, pd.DataFrame(columns=["team_id", "season", "standard_contracts"])
    contracts = tables["contracts"][["contract_id", "status", "contract_type"]]
    first_season = years["season"].min()
    current = years[years["season"] == first_season].merge(contracts, on="contract_id")
    standard = current[(current["status"] == "active") & (current["contract_type"] == "standard")]
    counts = standard.groupby("team_id").size()
    per_team = tables["teams"][["team_id"]].assign(
        season=first_season,
        standard_contracts=lambda frame: frame["team_id"].map(counts).fillna(0).astype(int),
    )
    odd = (per_team["standard_contracts"] < MIN_PLAUSIBLE_ROSTER) | (
        per_team["standard_contracts"] > MAX_PLAUSIBLE_ROSTER
    )
    return len(per_team), per_team[odd]


# --- player value -------------------------------------------------------------------


def _regular_player_seasons(tables: Tables) -> pd.DataFrame:
    seasons = tables["player_seasons"]
    return seasons[seasons["season_type"] == "regular"]


def _impact_parts_add_up(tables: Tables) -> tuple[int, pd.DataFrame]:
    scores = tables["player_value_scores"]
    rated = scores[scores["impact"].notna()]
    from_parts = rated[list(PART_COLUMNS)].sum(axis=1)
    from_sides = rated["impact_offense"] + rated["impact_defense"]
    wrong = ((from_parts - rated["impact"]).abs() > VALUE_TOLERANCE) | (
        (from_sides - rated["impact"]).abs() > VALUE_TOLERANCE
    )
    failing = _failing(
        rated,
        wrong,
        ["player_id", "season", "impact"],
        from_parts=from_parts,
        offense_plus_defense=from_sides,
    )
    return len(rated), failing


def _every_season_is_valued(tables: Tables) -> tuple[int, pd.DataFrame]:
    scores = tables["player_value_scores"]
    columns = ["player_id", "season", "player_name"]
    if scores.empty:
        # No fitted model: nothing is valued, and the build says so in a note.
        return 0, pd.DataFrame(columns=columns)
    seasons = _regular_player_seasons(tables)
    rated = scores[scores["impact"].notna()]
    valued = set(zip(rated["player_id"], rated["season"], strict=True))
    missing = [
        key not in valued for key in zip(seasons["player_id"], seasons["season"], strict=True)
    ]
    return len(seasons), seasons.loc[missing, columns]


def _average_minute_has_no_impact(tables: Tables) -> tuple[int, pd.DataFrame]:
    scores = tables["player_value_scores"]
    rated = scores[scores["impact"].notna()]
    minutes = _regular_player_seasons(tables)[["player_id", "season", "minutes"]]
    joined = rated.merge(minutes, on=["player_id", "season"])
    weighted = (joined["impact"] * joined["minutes"]).groupby(joined["season"]).sum()
    total = joined["minutes"].groupby(joined["season"]).sum()
    mean = (weighted / total.where(total > 0)).rename("minutes_weighted_impact")
    off = mean.abs() > VALUE_TOLERANCE
    return len(mean), mean[off].rename_axis("season").reset_index()


def _one_primary_archetype(tables: Tables) -> tuple[int, pd.DataFrame]:
    roles = tables["player_archetypes"]
    keys = ["player_id", "season"]
    primary = roles["is_primary"].astype(bool)
    counts = primary.groupby([roles[key] for key in keys]).sum().rename("primary_roles")
    filled = roles["fills"].astype(bool).groupby([roles[key] for key in keys]).sum()
    # A player who fills a role has exactly one primary role; one who fills none has none.
    wrong = counts != (filled > 0).astype(int)
    unfilled = roles[primary & ~roles["fills"].astype(bool)]
    failing = counts[wrong].reset_index()
    if not unfilled.empty:
        extra = unfilled[keys].assign(primary_roles=1).drop_duplicates()
        failing = pd.concat([failing, extra], ignore_index=True).drop_duplicates(keys)
    return len(counts), failing


E, W = Severity.ERROR, Severity.WARNING

_CROSS_TABLE_CHECKS: tuple[Check, ...] = (
    Check(
        "games_are_paired",
        "team_games",
        "Each game has two rows that name each other as opponent, mirror each other's "
        "score, and disagree on home/away and on who won.",
        E,
        _games_are_paired,
    ),
    Check(
        "box_scores_are_possible",
        "team_games",
        "Rebounds are offensive plus defensive, and no shot type has more makes than attempts.",
        E,
        _box_scores_are_possible,
    ),
    Check(
        "points_add_up",
        "team_games",
        "Points equal two per field goal, one more per three-pointer, one per free throw.",
        W,
        _points_add_up,
    ),
    Check(
        "results_match_scores",
        "team_games",
        "The team recorded as the winner scored more points; no game is tied.",
        E,
        _results_match_scores,
    ),
    Check(
        "minutes_fit_game_length",
        "team_games",
        "Team minutes are 240, plus 25 for each overtime period.",
        W,
        _minutes_fit_game_length,
    ),
    Check(
        "records_match_games",
        "team_seasons",
        "Each team's games, wins and losses equal its regular-season game results.",
        E,
        _records_match_games,
    ),
    Check(
        "totals_close_to_games",
        "team_seasons",
        f"Published season totals are within {TOTALS_TOLERANCE:.0%} of the sum of the "
        "team's game box scores.",
        W,
        _totals_close_to_games,
    ),
    Check(
        "league_is_balanced",
        "team_seasons",
        "Across a season, wins equal losses and points scored equal points allowed.",
        E,
        _league_is_balanced,
    ),
    Check(
        "ratings_are_consistent",
        "team_seasons",
        "Published offensive rating matches points per 100 possessions, and net rating "
        "is offensive minus defensive.",
        W,
        _ratings_are_consistent,
    ),
    Check(
        "outcomes_form_a_postseason",
        "team_seasons",
        "A finished season has one champion, two finalists, four conference finalists "
        "and sixteen playoff teams.",
        E,
        _outcomes_form_a_postseason,
    ),
    Check(
        "conference_ranks_are_distinct",
        "team_seasons",
        "In each conference and season the standings give every team a place of its own, "
        "from first to last. Through 2000-01 the league's standings leave teams with the "
        "same record on the same place, so a place there is not always a playoff seed.",
        W,
        _conference_ranks_are_distinct,
    ),
    Check(
        "brackets_are_complete",
        "playoff_results",
        "A finished postseason has 8, 4, 2 and 1 series by round, all decided.",
        E,
        _brackets_are_complete,
    ),
    Check(
        "winners_advance",
        "playoff_results",
        "Every team in a later round won its series in the round before.",
        E,
        _winners_advance,
    ),
    Check(
        "games_and_points_match_logs",
        "player_seasons",
        "Each player's games played and points equal the player's game log. The league "
        "corrects the two separately, so a few dozen player-seasons differ by a basket "
        "or a game.",
        W,
        _player_games_match_logs,
    ),
    Check(
        "games_and_points_close_to_logs",
        "player_seasons",
        f"Each player's games played are within {PLAYER_GAMES_TOLERANCE} of the game log, "
        f"and points within {PLAYER_POINTS_TOLERANCE} or {TOTALS_TOLERANCE:.0%}.",
        E,
        _player_games_close_to_logs,
    ),
    Check(
        "minutes_close_to_logs",
        "player_seasons",
        "Season minutes match the game log to within the log's rounding to whole minutes.",
        W,
        _player_minutes_close_to_logs,
    ),
    Check(
        "starts_within_games",
        "player_seasons",
        "No player started more games than were played.",
        E,
        _starts_within_games,
    ),
    Check(
        "points_sum_to_team_points",
        "player_game_logs",
        "In every game, a team's players' points sum to the team's points. Two box "
        "scores of the 1990s do not: a player listed with the opponent, and a line with "
        "four points too many.",
        W,
        _player_points_sum_to_team_points,
    ),
    Check(
        "points_close_to_team_points",
        "player_game_logs",
        f"In every game, a team's players' points are within {TEAM_POINTS_TOLERANCE} of "
        "the team's points.",
        E,
        _player_points_close_to_team_points,
    ),
    Check(
        "minutes_sum_to_team_minutes",
        "player_game_logs",
        "In every game, a team's players' minutes sum to the team's minutes, to within "
        "the rounding of each player's minutes. Some box scores of 2005-06 and 2006-07, "
        "and of the 1990s, do not.",
        W,
        _player_minutes_sum_to_team_minutes,
    ),
    Check(
        "logged_games_have_players",
        "player_game_logs",
        "Every team game in a season with player logs has player rows.",
        E,
        _logged_games_have_players,
    ),
    Check(
        "totals_match_years",
        "contracts",
        "Each contract's total, length and first and last seasons agree with its seasons.",
        E,
        _contract_totals_match_years,
    ),
    Check(
        "one_active_contract_per_player_season",
        "contract_years",
        "No player is under two active contracts in the same season.",
        E,
        _one_active_contract_per_player_season,
    ),
    Check(
        "cap_shares_are_consistent",
        "contract_years",
        "Cap share equals salary divided by that season's configured cap, and is null "
        "when no cap is configured.",
        E,
        _cap_shares_are_consistent,
    ),
    Check(
        "salaries_are_plausible",
        "contract_years",
        f"Salaries fall between {MIN_PLAUSIBLE_CAP_SHARE:.2%} and {MAX_PLAUSIBLE_CAP_SHARE:.0%} "
        "of the cap; anything else is probably a typing slip.",
        W,
        _salaries_are_plausible,
    ),
    Check(
        "teams_have_plausible_rosters",
        "contract_years",
        f"In the first season of the contract file every team has between "
        f"{MIN_PLAUSIBLE_ROSTER} and {MAX_PLAUSIBLE_ROSTER} standard contracts; fewer "
        "means the file is incomplete.",
        W,
        _teams_have_plausible_rosters,
    ),
    Check(
        "impact_parts_add_up",
        "player_value_scores",
        "A season's impact is the sum of its parts, and of its offense and defense.",
        E,
        _impact_parts_add_up,
    ),
    Check(
        "every_season_is_valued",
        "player_value_scores",
        "Every player's regular season has an impact, once a value model has been fitted.",
        E,
        _every_season_is_valued,
    ),
    Check(
        "one_primary_archetype",
        "player_archetypes",
        "A player who fills any role in a season has exactly one primary role, and it is "
        "one of the roles filled.",
        E,
        _one_primary_archetype,
    ),
    Check(
        "average_minute_has_no_impact",
        "player_value_scores",
        "In every season the minutes-weighted average impact is zero: impact is measured "
        "against the league's average minute.",
        E,
        _average_minute_has_no_impact,
    ),
)


def all_checks(contracts: Sequence[TableContract]) -> list[Check]:
    """Reference checks for the given contracts followed by the cross-table checks."""
    present = {contract.name for contract in contracts}
    cross_table = [check for check in _CROSS_TABLE_CHECKS if check.table in present]
    return [*reference_checks(contracts), *cross_table]


CHECKS: tuple[Check, ...] = _CROSS_TABLE_CHECKS
