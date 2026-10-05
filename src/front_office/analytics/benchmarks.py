"""Historical benchmarks: what the teams that reached each stage of the postseason looked like.

Everything here describes seasons that are over. A rate is the share of past
team-seasons in a group that reached a stage, given with the size of the group and an
interval that says how far a share drawn from that many cases can be trusted. Nothing
is fitted, and nothing here is a forecast for a team whose season is not finished.

Three devices keep seasons from different eras comparable:

- a record is put on the scale of a full season (wins per 82 games);
- a team's standing on a metric is its rank among the teams of its own season;
- what separates teams is measured within a season, team against team, and only then
  added up across seasons.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import NormalDist

import numpy as np
import pandas as pd

from front_office.analytics import comparison as compare
from front_office.analytics import formulas as f
from front_office.analytics.teams import RECORD, TEAM_METRICS
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance
from front_office.domain.stages import STAGE_KEYS, STAGES, Stage, stage

__all__ = [
    "BENCHMARK_METRICS",
    "EVERY_TEAM",
    "FULL_SEASON_GAMES",
    "RANKED_KEYS",
    "RESEARCH_METRICS",
    "STAGES",
    "STAGE_KEYS",
    "Stage",
    "bands",
    "rank_counts",
    "research_frame",
    "separation",
    "stage",
    "stage_counts",
    "stage_profiles",
    "stage_rates",
    "wilson_interval",
]

FULL_SEASON_GAMES = 82

RESEARCH_METRICS = MetricCatalog(
    (
        MetricSpec(
            "wins_per_82",
            "W/82",
            "Wins per 82 games",
            "Winning percentage times 82: a record on the scale of a full season, so that "
            "seasons cut short by a lockout or a pandemic compare with the rest.",
            RECORD,
        ),
        MetricSpec(
            "conference_rank",
            "Seed",
            "Conference seed",
            "Final position in the conference standings, as published by the league: the "
            "seed a team took into the postseason.",
            RECORD,
            MetricFormat.COUNT,
            Provenance.MEASURED,
            higher_is_better=False,
        ),
    )
)
"""Measures that exist for research across seasons, beside the team metrics."""

BENCHMARK_METRICS = MetricCatalog((*RESEARCH_METRICS, *TEAM_METRICS))
"""Everything a team-season can be described by in benchmark research."""

RANKED_KEYS: tuple[str, ...] = ("wins_per_82", *TEAM_METRICS.keys)
"""Metrics whose league rank within the season is carried as ``<key>_rank``."""


EVERY_TEAM = "every_team"
"""The group that is not a stage: the whole field, for reference."""

QUANTILES: dict[str, float] = {
    "lowest": 0.0,
    "p10": 0.10,
    "p25": 0.25,
    "median": 0.50,
    "p75": 0.75,
    "p90": 0.90,
    "highest": 1.0,
}
"""The points of a distribution a profile reports, by column name."""

RATE_COLUMNS = ("lower", "upper", "teams", "stage", "reached", "rate", "low", "high")
PROFILE_COLUMNS = ("group", "metric", "teams", *QUANTILES)
RANK_COUNT_COLUMNS = ("group", "cutoff", "teams", "inside", "share", "low", "high")
SEPARATION_COLUMNS = (
    "metric",
    "concordance",
    "low",
    "high",
    "pairs",
    "seasons",
    "reached",
    "others",
    "reached_median_rank",
    "others_median_rank",
)


# --- the research frame -----------------------------------------------------------------


def research_frame(team_metrics: pd.DataFrame) -> pd.DataFrame:
    """One row per team-season whose postseason is decided, ready for benchmark research.

    ``team_metrics`` is :func:`front_office.analytics.teams.team_season_metrics`. Added
    to it: wins per 82 games; one boolean column per stage in :data:`STAGES`;
    ``league_teams``, the number of teams that season; and ``<key>_rank`` for every key
    in :data:`RANKED_KEYS`, the team's league rank on that metric in its own season
    (1 is best; for a metric with no better direction, 1 is the highest). A season
    whose postseason is still open is left out: nobody has reached anything yet.
    """
    decided = team_metrics[team_metrics["made_playoffs"].notna()].reset_index(drop=True)
    frame = decided.copy()
    frame["wins_per_82"] = frame["win_pct"] * FULL_SEASON_GAMES

    playoffs = frame["made_playoffs"].astype(bool)
    play_in = frame["made_play_in"].fillna(False).astype(bool)
    round_reached = frame["playoff_round_reached"].fillna(0).astype("int64")
    frame["reached_postseason"] = playoffs | play_in
    frame["made_playoffs"] = playoffs
    frame["won_a_round"] = round_reached >= 2
    frame["made_conference_finals"] = frame["made_conference_finals"].fillna(False).astype(bool)
    frame["made_finals"] = frame["made_finals"].fillna(False).astype(bool)
    frame["won_championship"] = frame["won_championship"].fillna(False).astype(bool)

    by_season = frame["season"]
    frame["league_teams"] = frame.groupby("season")["team_id"].transform("size")
    ranks = {
        f"{key}_rank": compare.ranks(frame, BENCHMARK_METRICS, key, group=by_season)
        for key in RANKED_KEYS
    }
    return pd.concat([frame, pd.DataFrame(ranks, index=frame.index)], axis=1)


def stage_counts(frame: pd.DataFrame) -> pd.Series:
    """How many team-seasons of ``frame`` reached each stage, indexed by stage key."""
    return frame[list(STAGE_KEYS)].sum().astype("int64")


# --- how sure a share is ----------------------------------------------------------------


def wilson_interval(
    successes: pd.Series, trials: pd.Series, *, confidence: float = 0.95
) -> tuple[pd.Series, pd.Series]:
    """The Wilson score interval for a share: where the long-run rate plausibly lies.

    Unlike the textbook plus-or-minus, it stays inside 0 to 1 and does not collapse to
    nothing when no case, or every case, was a success: 0 of 10 gives 0% to 28%, not
    "0%, certainly". Missing where there are no trials.
    """
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    k = successes.astype("float64")
    n = trials.astype("float64").where(trials > 0)
    share = k / n
    spread = 1 + z**2 / n
    centre = (share + z**2 / (2 * n)) / spread
    half = z * np.sqrt(share * (1 - share) / n + z**2 / (4 * n**2)) / spread
    low = (centre - half).clip(lower=0.0).where(k > 0, 0.0).where(n.notna())
    high = (centre + half).clip(upper=1.0).where(k < n, 1.0).where(n.notna())
    return low, high


# --- how often ------------------------------------------------------------------------


def bands(values: pd.Series, width: float) -> list[float]:
    """Edges of equal bands of ``width`` that cover ``values``, on multiples of ``width``.

    Empty when there are no values.
    """
    if width <= 0:
        raise ValueError("a band needs a positive width")
    present = values.astype("float64").dropna()
    if present.empty:
        return []
    first = math.floor(present.min() / width)
    last = math.floor(present.max() / width) + 1
    return [round(step * width, 9) for step in range(first, last + 1)]


def stage_rates(
    frame: pd.DataFrame,
    by: str,
    *,
    edges: Sequence[float] | None = None,
    confidence: float = 0.95,
) -> pd.DataFrame:
    """How often the teams in each band of one measure reached each stage.

    ``frame`` is :func:`research_frame`, narrowed to the seasons of interest. ``edges``
    are ascending band edges: a band holds the values from its lower edge up to, but
    not including, its upper edge. Without ``edges`` every distinct value of ``by`` is
    a band of its own (``lower`` and ``upper`` are then that value), which suits a
    seed. Returns one row per band per stage, lowest band first: ``lower``, ``upper``,
    ``teams`` in the band, ``stage``, how many ``reached`` it, the ``rate``, and the
    ``low`` and ``high`` ends of its interval. A band with no teams is left out, and so
    is a team outside every band or without a value.
    """
    values = frame[by].astype("float64")
    if edges is None:
        lower = upper = values
    else:
        ordered = [float(edge) for edge in edges]
        if len(ordered) < 2 or any(b <= a for a, b in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("band edges must be at least two ascending values")
        position = pd.Series(np.searchsorted(ordered, values, side="right") - 1, index=frame.index)
        inside = values.notna() & (position >= 0) & (position < len(ordered) - 1)
        position = position.where(inside)
        lower = position.map(dict(enumerate(ordered[:-1])))
        upper = position.map(dict(enumerate(ordered[1:])))

    flags = frame[list(STAGE_KEYS)].astype("int64")
    keyed = flags.assign(lower=lower, upper=upper).dropna(subset=["lower", "upper"])
    grouped = keyed.groupby(["lower", "upper"], sort=True)
    counts = grouped[list(STAGE_KEYS)].sum()
    teams = grouped.size().rename("teams")

    tidy = counts.reset_index().melt(
        id_vars=["lower", "upper"], var_name="stage", value_name="reached"
    )
    tidy = tidy.merge(teams.reset_index(), on=["lower", "upper"])
    tidy["rate"] = f.safe_divide(tidy["reached"], tidy["teams"])
    tidy["low"], tidy["high"] = wilson_interval(
        tidy["reached"], tidy["teams"], confidence=confidence
    )
    order = {key: number for number, key in enumerate(STAGE_KEYS)}
    tidy = tidy.assign(_order=tidy["stage"].map(order)).sort_values(["lower", "_order"])
    return tidy[list(RATE_COLUMNS)].reset_index(drop=True)


# --- what they looked like ------------------------------------------------------------


def _groups(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """The whole field, then the teams that reached each stage."""
    reached = [(key, frame[frame[key].astype(bool)]) for key in STAGE_KEYS]
    return [(EVERY_TEAM, frame), *reached]


def stage_profiles(frame: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """The spread of each column in ``keys`` among the teams that reached each stage.

    One row per group per column: ``group`` (a stage key, or :data:`EVERY_TEAM` for the
    whole field), ``metric``, how many ``teams`` had a value, and the points in
    :data:`QUANTILES`. ``lowest`` and ``highest`` are real teams; the rest are
    interpolated. Pass ``<key>_rank`` columns to profile league ranks, which compare
    across eras where raw values do not.
    """
    lines = []
    for group, members in _groups(frame):
        for key in keys:
            values = members[key].astype("float64").dropna()
            line: dict[str, object] = {"group": group, "metric": key, "teams": len(values)}
            for name, point in QUANTILES.items():
                line[name] = float(values.quantile(point)) if len(values) else f.NAN
            lines.append(line)
    return pd.DataFrame(lines, columns=list(PROFILE_COLUMNS))


def rank_counts(
    frame: pd.DataFrame,
    keys: Sequence[str],
    *,
    cutoffs: Sequence[int] = (1, 3, 5, 10),
    confidence: float = 0.95,
) -> pd.DataFrame:
    """How many teams of each group ranked inside each cutoff, that season, on every key.

    With one key this answers "how many champions led the league in net rating"; with
    two, "how many were top ten on both offense and defense". One row per group per
    cutoff: ``group``, ``cutoff``, the ``teams`` in the group, how many were ``inside``
    the cutoff on all of ``keys``, the ``share``, and its interval.
    """
    if not keys:
        raise ValueError("name at least one metric to rank by")
    ranks = frame[[f"{key}_rank" for key in keys]].astype("float64")
    lines = []
    for group, members in _groups(frame):
        mine = ranks.loc[members.index]
        for cutoff in cutoffs:
            inside = int((mine <= cutoff).all(axis=1).sum())
            lines.append({"group": group, "cutoff": cutoff, "teams": len(mine), "inside": inside})
    table = pd.DataFrame(lines, columns=["group", "cutoff", "teams", "inside"])
    table["share"] = f.safe_divide(table["inside"], table["teams"])
    table["low"], table["high"] = wilson_interval(
        table["inside"], table["teams"], confidence=confidence
    )
    return table[list(RANK_COUNT_COLUMNS)]


# --- what separates them --------------------------------------------------------------


def separation(
    frame: pd.DataFrame,
    reached: str,
    keys: Sequence[str],
    *,
    resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> pd.DataFrame:
    """How well each metric, on its own, orders the teams that reached a stage.

    ``concordance`` is the share of same-season pairs - one team that reached the
    stage, one that did not - in which the team that reached it has the better value;
    a tie counts as half. One half means the metric tells the two kinds of team apart
    no better than a coin; one means it never failed. For a metric with no better
    direction, "better" is read as higher, so a figure below one half means the stage
    went with less of it.

    Teams are only ever compared with teams of their own season, so a league that
    scores more than it did thirty years ago cannot blur the comparison. The interval
    comes from drawing whole seasons again with replacement: the teams of one season
    are not independent cases - one team's win is another's loss - but seasons nearly
    are. With few seasons it is wide, and should be.

    One row per metric, in the order of ``keys``: ``metric``, ``concordance``, its
    ``low`` and ``high``, the number of ``pairs`` and ``seasons`` behind it, how many
    teams ``reached`` the stage and how many ``others`` did not, and each group's
    median league rank on the metric (for a seed, its median seed).
    """
    if reached not in STAGE_KEYS:
        raise KeyError(f"no stage named {reached!r}")
    if resamples < 1:
        raise ValueError("resamples must be at least 1")
    tail = (1 - confidence) / 2
    random = np.random.default_rng(seed)
    seasons = sorted(frame["season"].unique())
    draws = random.integers(0, max(len(seasons), 1), size=(resamples, len(seasons)))

    lines = []
    for key in keys:
        valid = frame[frame[key].notna()]
        flag = valid[reached].astype(bool)
        goodness = valid[key].astype("float64")
        if BENCHMARK_METRICS[key].higher_is_better is False:
            goodness = -goodness
        by_season = valid["season"]
        position = goodness.groupby(by_season).rank(method="average")
        in_group = flag.groupby(by_season).sum().reindex(seasons, fill_value=0).astype("float64")
        size = flag.groupby(by_season).size().reindex(seasons, fill_value=0).astype("float64")
        rank_sum = position.where(flag, 0.0).groupby(by_season).sum().reindex(seasons, fill_value=0)
        wins = (rank_sum - in_group * (in_group + 1) / 2).to_numpy()
        pairs = (in_group * (size - in_group)).to_numpy()

        total = pairs.sum()
        concordance = wins.sum() / total if total else f.NAN
        low = high = f.NAN
        if total:
            resampled_pairs = pairs[draws].sum(axis=1)
            usable = resampled_pairs > 0
            shares = wins[draws].sum(axis=1)[usable] / resampled_pairs[usable]
            low, high = (float(value) for value in np.quantile(shares, [tail, 1 - tail]))
        # A seed is a rank already, and has no league rank of its own.
        rank_column = f"{key}_rank" if f"{key}_rank" in valid.columns else key
        league_rank = valid[rank_column].astype("float64")
        lines.append(
            {
                "metric": key,
                "concordance": float(concordance),
                "low": low,
                "high": high,
                "pairs": int(total),
                "seasons": int((pairs > 0).sum()),
                "reached": int(flag.sum()),
                "others": int((~flag).sum()),
                "reached_median_rank": float(league_rank[flag].median()),
                "others_median_rank": float(league_rank[~flag].median()),
            }
        )
    return pd.DataFrame(lines, columns=list(SEPARATION_COLUMNS))
