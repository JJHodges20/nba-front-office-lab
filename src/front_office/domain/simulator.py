"""The simulator's parameters: what is specified before looking, and what a fit measures.

The simulator draws seasons for a roster from parts the lab has already tested - the
value model's projections and its error, the postseason model's season steps - and from
a few things measured here: how far a season's results stray from a team's strength,
how far wins stray from a rating, how far player projections have missed by how well
the player was known, and how many games rotation players miss. Like the other models
the file (``configs/models/simulator.json``) is written only by
``fol simulate fit --write`` and read by the services; nothing is fitted on a page.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SimulatorSpec(_Frozen):
    """How the simulator's parameters are measured and tested: the choices made before
    looking."""

    noise_seasons: PositiveInt = 10
    """How many of the most recent seasons the season noise and the wins residual are
    measured over: both have drifted with scoring and the schedule."""
    reliability_edges: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    """Where players are grouped by how well the value model knew them, for the spread
    of their projections' misses."""
    rotation_minutes: PositiveInt = 1000
    """Minutes a player must have played for their missed games to count toward the
    availability distribution: rotation players, not the end of the bench."""
    missed_quantiles: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)
    """The points of the missed-games distribution the file keeps, for drawing from it."""
    high_injury_quantile: float = Field(default=0.75, gt=0, lt=1)
    """Where the high-injury preset puts every player's expected missed games."""
    test_simulations: PositiveInt = 2000
    """Seasons drawn for each team-season of the wins test."""
    coverage_levels: tuple[float, ...] = (0.5, 0.8, 0.95)
    """The intervals whose coverage the wins test reports."""
    wins_interval: float = Field(default=0.8, gt=0.5, lt=1)
    """The interval a scenario's wins and rating are shown with."""
    simulations: PositiveInt = 10_000
    """Seasons a scenario draws unless it asks for another number."""
    seed: int = 0

    @field_validator("reliability_edges")
    @classmethod
    def _ascending_edges(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        edges = tuple(float(edge) for edge in value)
        if len(edges) < 2 or edges[0] != 0.0 or edges[-1] != 1.0:
            raise ValueError("reliability_edges must run from 0 to 1")
        if any(b <= a for a, b in zip(edges, edges[1:], strict=False)):
            raise ValueError("reliability_edges must ascend")
        return edges

    @field_validator("missed_quantiles")
    @classmethod
    def _quantiles(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        levels = tuple(float(level) for level in value)
        if len(levels) < 2 or levels[0] != 0.0 or levels[-1] != 1.0:
            raise ValueError("missed_quantiles must run from 0 to 1")
        if any(b <= a for a, b in zip(levels, levels[1:], strict=False)):
            raise ValueError("missed_quantiles must ascend")
        return levels

    @field_validator("coverage_levels")
    @classmethod
    def _levels(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        levels = tuple(float(level) for level in value)
        if any(not 0 < level < 1 for level in levels) or not levels:
            raise ValueError("coverage_levels must lie strictly between 0 and 1")
        return levels

    @model_validator(mode="after")
    def _high_injury_is_kept(self) -> SimulatorSpec:
        if self.high_injury_quantile not in self.missed_quantiles:
            raise ValueError("high_injury_quantile must be one of missed_quantiles")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]


# --- what a fit measures ------------------------------------------------------------------


class EraNoise(_Frozen):
    """How far a season's results stray from a team's strength, in one era."""

    key: str
    label: str
    first_season: str
    last_season: str
    team_seasons: int
    noise: float
    """Standard deviation of a season's net rating around the team's strength, per 100
    possessions, from the spread of its game margins."""


class DevelopmentBand(_Frozen):
    """Players the value model knew about this well: how far their projections missed."""

    lower: float
    upper: float
    """Projection reliability from ``lower`` up to ``upper``."""
    players: int
    mean_miss: float
    """Impact less projected impact, weighted by minutes played: the typical direction."""
    spread: float
    """The standard deviation of the miss, weighted the same way: the typical size."""


class Quantile(_Frozen):
    level: float
    value: float


class MissedGames(_Frozen):
    """The share of the season rotation players have missed."""

    players: int
    mean: float
    quantiles: tuple[Quantile, ...]

    def at(self, level: float) -> float:
        for item in self.quantiles:
            if item.level == level:
                return item.value
        raise KeyError(f"no quantile kept at {level}")


class Coverage(_Frozen):
    """How often an interval of simulated wins held the wins that happened."""

    level: float
    cases: int
    covered: int

    @property
    def share(self) -> float:
        return self.covered / self.cases if self.cases else 0.0


class WinsTest(_Frozen):
    """Seasons drawn for every team-season the value model predicted out of sample, set
    against the wins that happened."""

    team_seasons: int
    first_test_season: str
    last_test_season: str
    mae: float
    """Mean absolute error of the median simulated wins, in wins per 82."""
    rmse: float
    baseline_rmse: float
    """Error of giving every team an even record."""
    coverage: tuple[Coverage, ...]

    def at(self, level: float) -> Coverage:
        for item in self.coverage:
            if item.level == level:
                return item
        raise KeyError(f"no coverage kept at {level}")


class FittedOn(_Frozen):
    first_season: str
    last_season: str
    team_seasons: int
    games: int
    player_seasons: int


class SimulatorModel(_Frozen):
    """The simulator's measured parameters, with the evidence for the wins they give."""

    revision: PositiveInt
    fitted_at: datetime
    spec: SimulatorSpec
    value_model_version: str
    """The value model whose error and projections the simulator draws from."""
    postseason_model_version: str | None
    """The postseason model on file when the simulator was fitted, if any."""
    fitted_on: FittedOn
    value_error: float
    """The value model's miss on a team's net rating, out of sample (RMSE)."""
    season_noise: float
    """How far a season's net rating strays from a team's strength, over the most recent
    seasons: the part of the value model's miss that no model could remove."""
    strength_error: float
    """What is left of the value model's miss once a season's own noise is taken out: how
    far a projected rating is from a team's strength."""
    noise_by_era: tuple[EraNoise, ...]
    wins_season: str
    """The season the wins-per-point figure is for: the latest with games played."""
    wins_per_point: float
    wins_residual: float
    """Standard deviation of wins per 82 around what a season's net rating gives."""
    development: tuple[DevelopmentBand, ...]
    missed: MissedGames
    test: WinsTest

    @property
    def version(self) -> str:
        return f"s{self.revision}"

    def band(self, reliability: float) -> DevelopmentBand:
        """The band a player's projection reliability falls in."""
        for item in self.development:
            if item.lower <= reliability < item.upper or (item.upper == 1.0 and reliability == 1.0):
                return item
        raise KeyError(f"no development band holds reliability {reliability}")
