"""Comparing players: who qualifies, where each stands, and how two stack up.

A rate means little on a tiny sample, so comparisons are made within a *qualified*
population: players who cleared a minimum of games and minutes. The thresholds are the
analyst's choice, not a property of the data, and callers should show them as such.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from front_office.analytics.players import box_metrics
from front_office.domain.metrics import MetricCatalog
from front_office.domain.tables._fields import BOX_SCORE_COLUMNS

POSITION_GROUPS = {"G": "Guard", "F": "Forward", "C": "Center"}


@dataclass(frozen=True, slots=True)
class Qualification:
    """The minimum sample a player needs to be ranked against others."""

    min_games: int = 0
    min_minutes: float = 0.0

    def __post_init__(self) -> None:
        if self.min_games < 0 or self.min_minutes < 0:
            raise ValueError("qualification thresholds cannot be negative")

    def mask(self, frame: pd.DataFrame) -> pd.Series:
        """True for each row of ``frame`` (with ``games_played`` and ``minutes``) that qualifies."""
        return (frame["games_played"] >= self.min_games) & (frame["minutes"] >= self.min_minutes)

    def describe(self) -> str:
        if not self.min_games and not self.min_minutes:
            return "all players"
        parts = []
        if self.min_games:
            parts.append(f"{self.min_games}+ games")
        if self.min_minutes:
            parts.append(f"{self.min_minutes:,.0f}+ minutes")
        return "players with " + " and ".join(parts)


def position_group(position: str | None) -> str | None:
    """Guard, Forward or Center, from a listed position such as ``G-F``.

    A player listed at two positions is grouped by the first.
    """
    if not isinstance(position, str) or not position:
        return None
    return POSITION_GROUPS.get(position[0].upper())


def percentiles(
    frame: pd.DataFrame,
    catalog: MetricCatalog,
    keys: Sequence[str] | None = None,
    *,
    qualified: pd.Series | None = None,
    group: pd.Series | None = None,
) -> pd.DataFrame:
    """Percentile rank of each row on each metric, oriented so that higher is better.

    A percentile here is the share of the comparison group a player is ahead of, with
    ties counted as half: 50 is the middle of the group. For a metric where lower is
    better - turnovers, fouls, defensive rating - the scale is flipped, so a high
    percentile always means "good". For a metric with no better direction it simply
    means "higher".

    ``qualified`` marks the rows that form the comparison group; rows outside it get no
    percentile. ``group`` (for example position group) compares each row only with rows
    sharing its group. Missing values get no percentile and do not count as peers.
    """
    chosen = (
        list(keys) if keys is not None else [key for key in catalog.keys if key in frame.columns]
    )
    result = pd.DataFrame(index=frame.index)
    eligible = pd.Series(True, index=frame.index) if qualified is None else qualified.astype(bool)
    for key in chosen:
        values = frame[key].astype("float64").where(eligible)
        if catalog[key].higher_is_better is False:
            values = -values
        grouped = values.groupby(group) if group is not None else values
        rank = grouped.rank(method="average")
        size = grouped.transform("count") if group is not None else values.count()
        result[key] = (rank - 0.5) / size * 100
    return result


def ranks(
    frame: pd.DataFrame,
    catalog: MetricCatalog,
    key: str,
    *,
    qualified: pd.Series | None = None,
    group: pd.Series | None = None,
) -> pd.Series:
    """Position of each qualified row on one metric, 1 being best; ties share a rank.

    For a metric with no better direction, 1 is the highest value. ``group`` (for
    example season) ranks each row only among the rows sharing its group.
    """
    eligible = pd.Series(True, index=frame.index) if qualified is None else qualified.astype(bool)
    values = frame[key].astype("float64").where(eligible)
    ascending = catalog[key].higher_is_better is False
    grouped = values.groupby(group) if group is not None else values
    return grouped.rank(method="min", ascending=ascending).astype("Int64")


def comparison(
    frame: pd.DataFrame,
    percentile_frame: pd.DataFrame,
    rows: Sequence[object],
    keys: Sequence[str],
) -> pd.DataFrame:
    """A side-by-side of several rows: one line per metric per row.

    ``frame`` and ``percentile_frame`` share an index (for example ``player_id``).
    Returns ``metric``, the index value, ``value`` and ``percentile`` in tidy form, in
    the order the metrics and rows were given.
    """
    missing = [row for row in rows if row not in frame.index]
    if missing:
        raise KeyError(f"not in the comparison population: {missing}")
    name = frame.index.name or "row"
    lines = [
        {
            "metric": key,
            name: row,
            "value": frame.at[row, key],
            "percentile": percentile_frame.at[row, key],
        }
        for key in keys
        for row in rows
    ]
    return pd.DataFrame(lines, columns=["metric", name, "value", "percentile"])


def pooled_metrics(totals: pd.DataFrame) -> pd.Series:
    """Box metrics of a whole group treated as one player: the group's true average.

    Averaging players' percentages would weight a ten-shot season the same as a
    thousand-shot one. Pooling the totals first gives the rate the group actually shot.
    ``totals`` needs ``games_played``, ``minutes``, ``plus_minus`` and the box-score
    columns; per-game metrics come out as per player-game.
    """
    columns = ["games_played", "minutes", "plus_minus", *BOX_SCORE_COLUMNS]
    pooled = totals[columns].astype("float64").sum().to_frame().T
    return box_metrics(pooled).iloc[0]
