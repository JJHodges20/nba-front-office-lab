"""Benchmark research for the workbench: what past teams at each stage looked like.

This module assembles: it reads the team-season history, narrows it to an era, calls
analytics, and puts names on the result. It contains no formulas.

Everything it returns describes completed seasons. It is not a forecast, and it says
nothing about a season still being played.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from front_office.analytics import benchmarks as analytics
from front_office.analytics import teams as team_analytics
from front_office.analytics.benchmarks import EVERY_TEAM, STAGE_KEYS, STAGES, Stage
from front_office.config.eras import load_eras
from front_office.domain.eras import Era, EraSet
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.services.lab import Lab


@dataclass(frozen=True, slots=True)
class Measure:
    """Something stage rates can be broken down by, and how wide a band of it is."""

    key: str
    width: float | None
    """Width of a band by default; ``None`` when every value is its own band (a seed)."""
    widths: tuple[float, ...] = ()
    """Other widths worth offering."""


MEASURES: tuple[Measure, ...] = (
    Measure("wins_per_82", 5, (2, 5, 10)),
    Measure("net_rating", 2, (1, 2, 4)),
    Measure("point_diff_per_game", 2, (1, 2, 4)),
    Measure("rel_off_rating", 2, (1, 2, 4)),
    Measure("rel_def_rating", 2, (1, 2, 4)),
    Measure("conference_rank", None),
)
"""What "how often" can be asked by. A band width is a way of grouping, not a threshold."""

PROFILE_KEYS: tuple[str, ...] = (
    "wins_per_82",
    "net_rating",
    "off_rating",
    "def_rating",
    "efg_pct",
    "tov_pct",
    "oreb_pct",
    "ft_rate",
    "opp_efg_pct",
    "opp_tov_pct",
    "dreb_pct",
    "opp_ft_rate",
    "fg3a_rate",
    "pace",
)
"""Metrics a stage's teams are profiled on, by league rank within their own season."""

VALUE_KEYS: tuple[str, ...] = (
    "wins_per_82",
    "conference_rank",
    "net_rating",
    "rel_off_rating",
    "rel_def_rating",
    "point_diff_per_game",
)
"""Measures that mean the same in every era, profiled by their own value."""

NOT_COMPARED: tuple[str, ...] = ("games_played", "wins", "losses", *team_analytics.SEASON_ONLY)
SEPARATION_KEYS: tuple[str, ...] = tuple(
    key for key in team_analytics.TEAM_METRICS.keys if key not in NOT_COMPARED
)
"""Every team metric but the bare counts and the league-relative ratings, which order
the teams of a season exactly as the ratings themselves do. A seed is left out too: it
is the result of the record, and the bracket is drawn from it."""

RANK_CUTOFFS: tuple[int, ...] = (1, 3, 5, 10)
TWO_WAY_CUTOFFS: tuple[int, ...] = (5, 10)
DATASET_COLUMNS: tuple[str, ...] = (
    "season",
    "team_id",
    "team_name",
    "team_abbreviation",
    "conference",
    "conference_rank",
    "wins",
    "losses",
    "wins_per_82",
    "net_rating",
    "net_rating_rank",
    "off_rating",
    "off_rating_rank",
    "def_rating",
    "def_rating_rank",
    "rel_off_rating",
    "rel_def_rating",
    "point_diff_per_game",
    "pace",
    "league_teams",
    "postseason_result",
    *STAGE_KEYS,
)


@dataclass(frozen=True, slots=True)
class EraView:
    """An era as it falls on the seasons there is data for."""

    era: Era
    seasons: tuple[str, ...]
    """The completed seasons it covers, oldest first."""
    teams: int
    """Team-seasons in it."""
    reached: dict[str, int]
    """How many team-seasons reached each stage, by stage key."""

    @property
    def span(self) -> str:
        if not self.seasons:
            return "no completed seasons"
        if len(self.seasons) == 1:
            return self.seasons[0]
        return f"{self.seasons[0]} to {self.seasons[-1]}"


@dataclass(frozen=True, slots=True)
class StageSummary:
    """The teams of an era that reached a stage, in a few figures."""

    stage: Stage
    teams: int
    """Team-seasons that reached the stage."""
    field: int
    """Team-seasons in the era."""
    seasons: int
    fewest_wins: float
    """The lowest wins per 82 games of any team that reached it. Missing if none did."""
    fewest_wins_by: str
    """Who that was, briefly - ``2022-23 LAL`` - or how many teams share it."""
    median_wins: float
    median_net_rating: float
    median_net_rank: float
    """Median league rank in net rating, in each team's own season."""
    top_five_net: int
    """How many ranked in the league's top five in net rating."""
    top_ten_both_ends: int
    """How many ranked in the top ten in offensive and in defensive rating."""
    worst_seed: float
    """The lowest conference seed any of them had."""


@dataclass(frozen=True, slots=True)
class Floor:
    """Where the teams that reached a stage begin, in bands of a measure."""

    band: str
    """The lowest band that holds a team which reached the stage."""
    teams_below: int
    """Teams in the bands beneath it; none of them reached the stage."""
    ceiling: float
    """The upper end of the interval for "none of that many": the long-run rate those
    bands are still consistent with. Missing when there is no band beneath."""


def floor(rates: pd.DataFrame, stage: str) -> Floor | None:
    """The lowest band of :meth:`BenchmarkService.rates` from which a team reached ``stage``.

    ``None`` when no team in the era reached it.
    """
    mine = rates[rates["stage"] == stage]
    reached = mine[mine["reached"] > 0]
    if reached.empty:
        return None
    lowest = reached["lower"].min()
    below = int(mine.loc[mine["lower"] < lowest, "teams"].sum())
    _, high = analytics.wilson_interval(pd.Series([0]), pd.Series([below]))
    return Floor(band=str(reached.iloc[0]["band"]), teams_below=below, ceiling=float(high.iloc[0]))


class BenchmarkService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab
        self._eras = load_eras(lab.settings.config_dir)

    # --- what there is ------------------------------------------------------------------

    @property
    def metrics(self) -> MetricCatalog:
        return analytics.BENCHMARK_METRICS

    @property
    def stages(self) -> tuple[Stage, ...]:
        return STAGES

    @property
    def eras(self) -> EraSet:
        """The configured eras, in the order they are offered."""
        return self._eras

    def seasons(self) -> tuple[str, ...]:
        """Seasons whose postseason is complete, oldest first: what research can use."""
        return tuple(sorted(self._history()["season"].unique()))

    def era(self, key: str) -> Era:
        return self._eras[key]

    def view(self, era: Era) -> EraView:
        frame = self._frame(era)
        counts = analytics.stage_counts(frame)
        return EraView(
            era=era,
            seasons=tuple(sorted(frame["season"].unique())),
            teams=len(frame),
            reached={key: int(counts[key]) for key in STAGE_KEYS},
        )

    def summary(self, era: Era, stage: str) -> StageSummary:
        """The era's teams that reached ``stage``, in a few figures for a headline."""
        frame = self._frame(era)
        reached = analytics.stage(stage)
        columns = ["wins_per_82", "net_rating", "net_rating_rank", "conference_rank"]
        profile = analytics.stage_profiles(frame, columns)
        mine = profile[profile["group"] == stage].set_index("metric")
        members = frame[frame[stage].astype(bool)]
        wins = members["wins_per_82"].astype("float64")
        counts = analytics.rank_counts(frame, ["net_rating"], cutoffs=(5,))
        both = analytics.rank_counts(frame, ["off_rating", "def_rating"], cutoffs=(10,))
        return StageSummary(
            stage=reached,
            teams=len(members),
            field=len(frame),
            seasons=int(frame["season"].nunique()),
            fewest_wins=float(mine.at["wins_per_82", "lowest"]),
            fewest_wins_by=""
            if members.empty
            else _holders(members, wins, wins.min(), name="team_abbreviation"),
            median_wins=float(mine.at["wins_per_82", "median"]),
            median_net_rating=float(mine.at["net_rating", "median"]),
            median_net_rank=float(mine.at["net_rating_rank", "median"]),
            top_five_net=int(counts.loc[counts["group"] == stage, "inside"].iloc[0]),
            top_ten_both_ends=int(both.loc[both["group"] == stage, "inside"].iloc[0]),
            worst_seed=float(mine.at["conference_rank", "highest"]),
        )

    # --- the research ------------------------------------------------------------------

    def dataset(self, era: Era) -> pd.DataFrame:
        """Every team-season of the era, newest first: the rows all the research rests on."""
        frame = self._frame(era)
        frame["postseason_result"] = team_analytics.postseason_result(frame)
        ordered = frame.sort_values(["season", "wins_per_82"], ascending=[False, False])
        return ordered[list(DATASET_COLUMNS)].reset_index(drop=True)

    def highlights(self, era: Era, x: str, y: str) -> pd.DataFrame:
        """Two metrics of every team-season of the era, with identity and stage flags."""
        frame = self._frame(era)
        frame["postseason_result"] = team_analytics.postseason_result(frame)
        identity = ["season", "team_id", "team_name", "team_abbreviation", "postseason_result"]
        columns = list(dict.fromkeys([*identity, x, y, *STAGE_KEYS]))
        return frame[columns].reset_index(drop=True)

    def rates(
        self,
        era: Era,
        measure: str,
        *,
        width: float | None = None,
        among: str | None = None,
    ) -> pd.DataFrame:
        """How often the era's teams in each band of ``measure`` reached each stage.

        One row per band per stage with the band in words (``band``), the number of
        ``teams`` in it, how many ``reached`` the stage, the ``rate`` and its interval.
        ``width`` overrides the measure's usual band width. With ``among`` - a stage -
        only the teams that reached it are counted: how often the playoff teams of a
        band went further, say, rather than how often all teams of that band did.
        """
        settings = _measure(measure)
        frame = self._frame(era)
        if among is not None:
            frame = frame[frame[analytics.stage(among).key].astype(bool)].reset_index(drop=True)
        chosen = width if width is not None else settings.width
        edges = None if chosen is None else analytics.bands(frame[measure], chosen)
        if edges is not None and len(edges) < 2:
            rates = analytics.stage_rates(frame.iloc[0:0], measure)
        else:
            rates = analytics.stage_rates(frame, measure, edges=edges)
        spec = self.metrics[measure]
        rates.insert(
            0,
            "band",
            [
                _band(spec, lower, upper)
                for lower, upper in zip(rates["lower"], rates["upper"], strict=True)
            ],
        )
        return rates

    def profiles(self, era: Era) -> pd.DataFrame:
        """Where the teams that reached each stage stood: by value and by league rank.

        One row per group per measure. ``kind`` is ``value`` for the measures that mean
        the same in every era (:data:`VALUE_KEYS`), shown in their own units, and
        ``rank`` for league rank within the season on each of :data:`PROFILE_KEYS`.
        ``lowest_team`` and ``highest_team`` name the team-season at each end, or say
        how many teams share it.
        """
        frame = self._frame(era)
        rank_columns = [f"{key}_rank" for key in PROFILE_KEYS]
        values = analytics.stage_profiles(frame, list(VALUE_KEYS)).assign(kind="value")
        ranks = analytics.stage_profiles(frame, rank_columns).assign(kind="rank")
        ranks["metric"] = ranks["metric"].str.removesuffix("_rank")
        table = pd.concat([values, ranks], ignore_index=True)
        ends = [
            self._ends(frame, group, metric, kind)
            for group, metric, kind in zip(
                table["group"], table["metric"], table["kind"], strict=True
            )
        ]
        table["lowest_team"] = [low for low, _ in ends]
        table["highest_team"] = [high for _, high in ends]
        table.insert(1, "group_label", table["group"].map(_group_labels()))
        return table

    def rank_counts(self, era: Era) -> pd.DataFrame:
        """How many teams of each group ranked near the top of the league that season.

        ``basis`` says on what: net rating, offense, defense, or ``both ends`` - inside
        the cutoff on offensive and on defensive rating at once.
        """
        frame = self._frame(era)
        parts = [
            analytics.rank_counts(frame, [key], cutoffs=RANK_CUTOFFS).assign(basis=basis)
            for key, basis in (
                ("net_rating", "Net rating"),
                ("off_rating", "Offensive rating"),
                ("def_rating", "Defensive rating"),
            )
        ]
        both = analytics.rank_counts(frame, ["off_rating", "def_rating"], cutoffs=TWO_WAY_CUTOFFS)
        parts.append(both.assign(basis="Both ends"))
        table = pd.concat(parts, ignore_index=True)
        table.insert(1, "group_label", table["group"].map(_group_labels()))
        return table

    def separation(self, era: Era, stage: str, *, among: str | None = None) -> pd.DataFrame:
        """How well each team metric alone orders the era's teams that reached ``stage``.

        They are set against every other team of their season, or - with ``among``, an
        earlier stage - only against the teams that reached that stage and went no
        further: the teams that won a round against the rest of the playoff field,
        rather than against the whole league. Highest concordance first, so the metrics
        that separate nothing sit near one half and those the stage went *against* come
        last. See :func:`front_office.analytics.benchmarks.separation` for the figure.
        """
        frame = self._frame(era)
        if among is not None:
            if STAGE_KEYS.index(among) >= STAGE_KEYS.index(analytics.stage(stage).key):
                raise ValueError(
                    f"the field must be an earlier stage than {stage!r}, not {among!r}"
                )
            frame = frame[frame[among].astype(bool)].reset_index(drop=True)
        table = analytics.separation(frame, stage, list(SEPARATION_KEYS))
        catalog = self.metrics
        table.insert(1, "label", [catalog[key].label for key in table["metric"]])
        table.insert(2, "name", [catalog[key].name for key in table["metric"]])
        table.insert(3, "category", [catalog[key].category for key in table["metric"]])
        ordered = table.sort_values("concordance", ascending=False, na_position="last")
        return ordered.reset_index(drop=True)

    # --- assembly -----------------------------------------------------------------------

    def _history(self) -> pd.DataFrame:
        metrics = team_analytics.team_season_metrics(self._lab.read("team_seasons"))
        return analytics.research_frame(metrics)

    def _frame(self, era: Era) -> pd.DataFrame:
        history = self._history()
        covered = era.seasons(sorted(history["season"].unique()))
        return history[history["season"].isin(covered)].reset_index(drop=True)

    @staticmethod
    def _ends(frame: pd.DataFrame, group: str, metric: str, kind: str) -> tuple[str, str]:
        """Who holds the lowest and the highest value in a group: a team, or how many."""
        members = frame if group == EVERY_TEAM else frame[frame[group].astype(bool)]
        column = f"{metric}_rank" if kind == "rank" else metric
        values = members[column].astype("float64").dropna()
        if values.empty:
            return "", ""
        return tuple(  # type: ignore[return-value]
            _holders(members, values, extreme) for extreme in (values.min(), values.max())
        )


def _measure(key: str) -> Measure:
    for measure in MEASURES:
        if measure.key == key:
            return measure
    offered = ", ".join(measure.key for measure in MEASURES)
    raise KeyError(f"stage rates are not offered by {key!r} (offered: {offered})")


def _group_labels() -> dict[str, str]:
    return {EVERY_TEAM: "Every team", **{stage.key: stage.label for stage in STAGES}}


def _holders(
    members: pd.DataFrame, values: pd.Series, extreme: float, *, name: str = "team_name"
) -> str:
    """The one team-season at an extreme, or the number of them that share it."""
    holders = values.index[values == extreme]
    if len(holders) > 1:
        return f"{len(holders)} teams"
    row = members.loc[holders[0]]
    return f"{row['season']} {row[name]}"


def _band(spec: MetricSpec, lower: float, upper: float) -> str:
    """A band in words: ``45 to 50``, ``+2 to +4``, or a single value such as a seed."""
    if lower == upper:
        return spec.format_value(lower)
    if spec.format is MetricFormat.SIGNED:
        return f"{_signed(lower)} to {_signed(upper)}"
    if spec.format is MetricFormat.PERCENT:
        return f"{lower * 100:g}% to {upper * 100:g}%"
    return f"{lower:g} to {upper:g}"


def _signed(edge: float) -> str:
    return "0" if edge == 0 else f"{edge:+g}"
