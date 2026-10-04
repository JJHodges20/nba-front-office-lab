"""Roster fit for the workbench: a roster described in the roadmap's areas of fit, placed
among the season's real teams, with the evidence on whether any of it matters beyond the
sum of the parts.

A real team or a roster the user built is profiled with the very code a build used for
every team-season, and set beside those rows. The evidence is a file gathered on
request (``fol fit test --write``); this module reads it and applies nothing the
evidence does not support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.config.archetypes import load_archetypes
from front_office.config.models import load_fit_evidence
from front_office.domain.archetypes import ArchetypeSet
from front_office.domain.fit import MEASURES, ROTATION_SIZE, STARTERS, measure
from front_office.domain.fit_model import FitEvidence
from front_office.domain.metrics import MetricCatalog
from front_office.domain.seasons import SeasonType
from front_office.modeling.archetypes import percentile
from front_office.modeling.fit import (
    FIT_METRICS,
    adjustment,
    fills_column,
    player_profiles,
    rotation_profile,
)
from front_office.modeling.fit.profile import PROFILED
from front_office.modeling.value.features import stints
from front_office.services.lab import Lab

TABLE = "team_fit_profiles"
REGULAR = SeasonType.REGULAR.value
TEAM = "team"
ROSTER = "roster"
ON_COURT = 5
TOP_THIRD, BOTTOM_THIRD = 100 * 2 / 3, 100 / 3

MEMBER_COLUMNS = (
    "player_name",
    "team",
    "position",
    "age",
    "minutes",
    "share",
    "in_rotation",
    "on_bench",
    "role",
    "roles",
    "impact",
    "wins_added",
)
PLACED_COLUMNS = (
    "key",
    "area",
    "name",
    "value",
    "median",
    "percentile",
    "rank",
    "teams",
    "higher_is_better",
)
COVERAGE_COLUMNS = (
    "archetype",
    "name",
    "count",
    "filled_by",
    "best_player",
    "best_score",
    "bench_count",
)
CHAMPIONS_COLUMNS = (
    "key",
    "area",
    "name",
    "champions",
    "median_percentile",
    "top_third",
    "bottom_third",
)
SEPARATOR = ", "


@dataclass(frozen=True, slots=True)
class FitStatus:
    revision: int | None
    """Revision of the evidence on file; ``None`` when none has been gathered."""
    gathered_at: datetime | None
    value_model_version: str | None
    """The value model whose test the evidence was measured against."""
    applied_value_version: str | None
    """The value model the database was built with."""
    archetype_version: str | None
    applied_archetype_version: str | None
    team_seasons: int
    usable: bool
    """Whether the evidence supports a correction to the sum of the parts."""
    seasons: tuple[str, ...]
    """Seasons with team profiles, newest first."""

    @property
    def is_gathered(self) -> bool:
        return self.revision is not None

    @property
    def is_current(self) -> bool:
        """Whether the evidence was gathered against what the database now holds."""
        return (
            self.is_gathered
            and self.value_model_version == self.applied_value_version
            and self.archetype_version == self.applied_archetype_version
        )


@dataclass(frozen=True, slots=True)
class SumOfParts:
    impact: float
    """The players' impacts added up for the minutes given: an expected net rating."""
    projected: float
    """The same with each player's projection going into the season."""
    error: float | None
    """What the value model's prediction of a team missed by, out of sample (RMSE)."""
    minutes_covered: float
    unprofiled_share: float
    correction: float | None
    """What the fit evidence would add; ``None`` when it supports nothing."""


@dataclass(frozen=True, slots=True)
class FitReport:
    kind: str
    """``team`` or ``roster``."""
    key: int
    name: str
    season: str
    """The season the players' statistics and minutes come from."""
    members: pd.DataFrame
    """Indexed by ``player_id``, most minutes first: :data:`MEMBER_COLUMNS`."""
    profile: pd.Series
    """One value per fit measure."""
    placed: pd.DataFrame
    """Each measure beside the season's real teams: :data:`PLACED_COLUMNS`."""
    coverage: pd.DataFrame
    """Each archetype: who in the rotation fills it: :data:`COVERAGE_COLUMNS`."""
    parts: SumOfParts
    unprofiled: tuple[str, ...]
    """Members with minutes but no statistics to profile."""
    absent: tuple[str, ...]
    """Roster members with no minutes in the season, who are not in the profile at all."""

    @property
    def is_empty(self) -> bool:
        return self.members.empty


class FitService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def metrics(self) -> MetricCatalog:
        return FIT_METRICS

    def evidence(self) -> FitEvidence | None:
        """The evidence on file, if any has been gathered."""
        return load_fit_evidence(self._lab.settings.config_dir)

    def archetypes(self) -> ArchetypeSet:
        return load_archetypes(self._lab.settings.config_dir)

    def seasons(self) -> tuple[str, ...]:
        return tuple(sorted(self._lab.warehouse.distinct(TABLE, "season"), reverse=True))

    def profiles(self, season: str) -> pd.DataFrame:
        """Every player's profile for one season, indexed by ``player_id``: the rates, the
        groups and the roles filled that the fit measures and the optimizer read."""
        return player_profiles(self._season_tables(season), self.archetypes()).set_index(
            "player_id"
        )

    def status(self) -> FitStatus:
        evidence = self.evidence()
        warehouse = self._lab.warehouse
        archetypes = warehouse.distinct(TABLE, "archetype_version")
        return FitStatus(
            revision=None if evidence is None else evidence.revision,
            gathered_at=None if evidence is None else evidence.fitted_at,
            value_model_version=None if evidence is None else evidence.value_model_version,
            applied_value_version=self._lab.value.status().applied_revision,
            archetype_version=None if evidence is None else evidence.archetype_version,
            applied_archetype_version=archetypes[0] if archetypes else None,
            team_seasons=0 if evidence is None else evidence.team_seasons,
            usable=evidence is not None and evidence.combined.is_usable,
            seasons=self.seasons(),
        )

    # --- subjects -----------------------------------------------------------------------

    def team(self, team_id: int, season: str) -> FitReport:
        """A real team: its players weighted by the minutes they played for it."""
        tables = self._season_tables(season)
        played = stints(
            tables["player_seasons"], tables["player_game_logs"], tables["team_seasons"]
        )
        mine = played[played["team_id"] == int(team_id)]
        minutes = mine.set_index("player_id")["minutes"].astype("float64")
        teams = tables["team_seasons"].set_index("team_id")["minutes"]
        to_fill = ON_COURT * float(teams.get(int(team_id), np.nan))
        name = str(self._lab.team_labels()["full_name"].get(int(team_id), f"Team {team_id}"))
        return self._report(TEAM, int(team_id), name, season, minutes, to_fill, tables, absent=())

    def roster(self, roster_id: int) -> FitReport:
        """A roster the user built: its players weighted by the minutes they played in the
        roster's statistics season."""
        roster = self._lab.rosters.get(roster_id)
        season = roster["stats_season"]
        members = self._lab.rosters.players(roster_id)["player_id"].astype("int64")
        tables = self._season_tables(season)
        lines = tables["player_seasons"].set_index("player_id")["minutes"].astype("float64")
        minutes = lines.reindex(members).fillna(0.0)
        minutes.index.name = "player_id"
        games = tables["team_seasons"]["minutes"].astype("float64")
        to_fill = ON_COURT * float(games.mean()) if len(games) else np.nan
        known = tables["players"].set_index("player_id")["full_name"]
        absent = tuple(
            str(known.get(player, f"Player {player}"))
            for player in members[minutes.to_numpy() <= 0]
        )
        return self._report(
            ROSTER,
            int(roster_id),
            str(roster["name"]),
            season,
            minutes,
            to_fill,
            tables,
            absent=absent,
        )

    def champions(self) -> pd.DataFrame:
        """Where the champions' rosters stood among their season's teams on each measure:
        :data:`CHAMPIONS_COLUMNS`, in the catalog's order.

        A median percentile near 50 says the champions looked like anyone on that
        measure; the counts say how many of them were in the top and the bottom third.
        """
        fit = self._lab.read(TABLE)
        teams = self._lab.read("team_seasons")[["season", "team_id", "won_championship"]]
        joined = fit.merge(teams, on=["season", "team_id"], how="inner")
        rows = []
        for item in MEASURES:
            standing = percentile(joined[item.key].astype("float64"), joined["season"])
            champions = standing[joined["won_championship"].fillna(False).astype(bool)].dropna()
            rows.append(
                {
                    "key": item.key,
                    "area": str(item.area),
                    "name": item.name,
                    "champions": int(len(champions)),
                    "median_percentile": float(champions.median()) if len(champions) else np.nan,
                    "top_third": int((champions >= TOP_THIRD).sum()),
                    "bottom_third": int((champions <= BOTTOM_THIRD).sum()),
                }
            )
        return pd.DataFrame(rows, columns=list(CHAMPIONS_COLUMNS))

    # --- assembly -----------------------------------------------------------------------

    def _season_tables(self, season: str) -> dict[str, pd.DataFrame]:
        read = self._lab.read
        return {
            "player_seasons": read("player_seasons", {"season": season, "season_type": REGULAR}),
            "player_game_logs": read(
                "player_game_logs", {"season": season, "season_type": REGULAR}
            ),
            "team_seasons": read("team_seasons", {"season": season}),
            "players": read("players"),
            "player_value_scores": read("player_value_scores", {"season": season}),
            "player_archetypes": read("player_archetypes", {"season": season}),
        }

    def _report(
        self,
        kind: str,
        key: int,
        name: str,
        season: str,
        minutes: pd.Series,
        to_fill: float,
        tables: dict[str, pd.DataFrame],
        *,
        absent: tuple[str, ...],
    ) -> FitReport:
        archetypes = self.archetypes()
        profiles = player_profiles(tables, archetypes).set_index("player_id")
        playing = minutes[minutes > 0].sort_values(ascending=False, kind="stable")
        members = profiles.reindex(playing.index)
        members["minutes"] = playing.to_numpy()
        profile = rotation_profile(members.reset_index(), team_minutes=to_fill)

        shown = self._members(members, kind, key, season, tables)
        unprofiled = tuple(shown.loc[members[PROFILED].isna(), "player_name"].astype(str))
        evidence = self.evidence()
        model = self._lab.value.model()
        parts = SumOfParts(
            impact=float(profile["impact_sum"]),
            projected=float(profile["projected_sum"]),
            error=None if model is None else model.validation.net.rmse,
            minutes_covered=float(profile["minutes_covered"]),
            unprofiled_share=float(profile["unprofiled_share"]),
            correction=None if evidence is None else adjustment(evidence, profile.to_dict()),
        )
        return FitReport(
            kind=kind,
            key=key,
            name=name,
            season=season,
            members=shown,
            profile=profile,
            placed=self._place(profile, season),
            coverage=self._coverage(members, shown, archetypes, tables),
            parts=parts,
            unprofiled=unprofiled,
            absent=absent,
        )

    def _members(
        self,
        members: pd.DataFrame,
        kind: str,
        key: int,
        season: str,
        tables: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        lines = tables["player_seasons"].set_index("player_id")
        known = tables["players"].set_index("player_id")
        labels = self._lab.team_labels()["abbreviation"]
        frame = pd.DataFrame(index=members.index)
        frame["player_name"] = known["full_name"].reindex(members.index)
        if kind == TEAM:
            frame["team"] = labels.get(key)
        else:
            frame["team"] = lines["team_id"].reindex(members.index).map(labels)
        frame["position"] = known["position"].reindex(members.index)
        frame["age"] = lines["age"].reindex(members.index)
        frame["minutes"] = members["minutes"]
        total = float(members["minutes"].sum())
        frame["share"] = members["minutes"] / total if total > 0 else np.nan
        order = np.arange(len(members))
        frame["in_rotation"] = order < ROTATION_SIZE
        frame["on_bench"] = (order >= STARTERS) & (order < ROTATION_SIZE)
        roles = self._lab.value.roles(season)
        frame["role"] = roles["role"].reindex(members.index)
        frame["roles"] = roles["roles"].reindex(members.index)
        frame["impact"] = members["impact"]
        frame["wins_added"] = members["wins_added"]
        return frame[list(MEMBER_COLUMNS)]

    def _place(self, profile: pd.Series, season: str) -> pd.DataFrame:
        teams = self._lab.read(TABLE, {"season": season})
        rows = []
        for item in MEASURES:
            values = (
                teams[item.key].dropna().astype("float64")
                if item.key in teams
                else pd.Series(dtype="float64")
            )
            value = float(profile[item.key])
            if values.empty or not np.isfinite(value):
                standing, rank, median = (
                    np.nan,
                    np.nan,
                    float(values.median()) if len(values) else np.nan,
                )
            else:
                below, equal = int((values < value).sum()), int((values == value).sum())
                standing = 100 * (below + 0.5 * equal) / len(values)
                rank = int((values > value).sum()) + 1
                median = float(values.median())
            rows.append(
                {
                    "key": item.key,
                    "area": str(item.area),
                    "name": item.name,
                    "value": value,
                    "median": median,
                    "percentile": standing,
                    "rank": rank,
                    "teams": int(len(values)),
                    "higher_is_better": item.higher_is_better,
                }
            )
        return pd.DataFrame(rows, columns=list(PLACED_COLUMNS))

    def _coverage(
        self,
        members: pd.DataFrame,
        shown: pd.DataFrame,
        archetypes: ArchetypeSet,
        tables: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        scores = tables["player_archetypes"]
        scores = scores[scores["player_id"].isin(members.index)]
        by_role = scores.pivot(index="player_id", columns="archetype", values="score")
        rotation = shown.index[shown["in_rotation"]]
        bench = shown.index[shown["on_bench"]]
        rows = []
        for archetype in archetypes:
            column = fills_column(archetype.key)
            fills = (
                members[column].fillna(False).astype(bool)
                if column in members
                else pd.Series(False, members.index)
            )
            filling = [player for player in rotation if fills.get(player, False)]
            candidates = (
                by_role[archetype.key].reindex(rotation).dropna()
                if archetype.key in by_role
                else pd.Series(dtype="float64")
            )
            best = int(candidates.idxmax()) if len(candidates) else None
            rows.append(
                {
                    "archetype": archetype.key,
                    "name": archetype.name,
                    "count": len(filling),
                    "filled_by": SEPARATOR.join(
                        str(shown.at[player, "player_name"]) for player in filling
                    ),
                    "best_player": None if best is None else str(shown.at[best, "player_name"]),
                    "best_score": float(candidates.max()) if len(candidates) else np.nan,
                    "bench_count": int(sum(fills.get(player, False) for player in bench)),
                }
            )
        return pd.DataFrame(rows, columns=list(COVERAGE_COLUMNS))


def measure_name(key: str) -> str:
    return measure(key).name
