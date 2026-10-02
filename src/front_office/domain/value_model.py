"""The player value model: how it is specified, and what a fitted one holds.

Two files, kept apart on purpose. The *specification* (``configs/models/
player_value.yaml``) is written by people: how earlier seasons are pooled, how much a
thin sample is distrusted, where the out-of-sample test begins. The *fitted model*
(``configs/models/player_value.json``) is written by ``fol value fit``: the weights the
data chose, and the evidence for them. A build only ever applies a fitted model, so a
player's value changes when someone fits the model again - a change that shows up in
version control - and never because a stat correction arrived overnight.

Weights are estimates. Every term carries the interval the data leaves it, and the
model carries how it did against simpler ways of making the same prediction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

from front_office.domain.seasons import Season

OFFENSE, DEFENSE, NET = "offense", "defense", "net"
SIDES = (OFFENSE, DEFENSE)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ValueSpec(_Frozen):
    """The choices a person makes before the data chooses the weights."""

    season_weights: tuple[float, ...] = (1.0, 0.5, 0.25)
    """How a player's earlier seasons are pooled, newest first: weight per minute played."""
    ballast_minutes: float = Field(default=750.0, gt=0)
    """Minutes of an unknown player mixed into every estimate. A player's own numbers get
    half the say once the weighted minutes equal this."""
    age_centre: float = 27.0
    """The age at which the age term is zero."""
    first_test_season: str = "2006-07"
    """First season predicted out of sample; every earlier season is only ever training."""
    replacement_rank: PositiveInt = 10
    """Replacement level is measured on players outside their team's top this-many in
    minutes: the players a team can find without giving anything up."""
    wins_window: int = Field(default=2, ge=0)
    """Wins per point of net rating are fitted on a season and this many either side."""
    resamples: PositiveInt = 2000
    seed: int = 0
    confidence: float = Field(default=0.95, gt=0.5, lt=1)

    @field_validator("season_weights")
    @classmethod
    def _weights(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value:
            raise ValueError("season_weights needs at least one season")
        if any(weight <= 0 for weight in value):
            raise ValueError("season_weights must be positive")
        if list(value) != sorted(value, reverse=True):
            raise ValueError("season_weights must not grow: the newest season counts most")
        return value

    @field_validator("first_test_season")
    @classmethod
    def _season_label(cls, value: str) -> str:
        return Season.parse(value).label

    @property
    def fingerprint(self) -> str:
        """A short hash of the specification: two specs fit the same model iff equal."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


class Term(_Frozen):
    """One weight of the model, on each side of the ball, with its interval."""

    key: str
    offense: float
    defense: float
    offense_low: float
    offense_high: float
    defense_low: float
    defense_high: float
    net_low: float
    net_high: float

    @property
    def net(self) -> float:
        return self.offense + self.defense

    def weight(self, side: str) -> float:
        if side == NET:
            return self.net
        if side not in SIDES:
            raise KeyError(f"no such side: {side!r}")
        return self.offense if side == OFFENSE else self.defense

    def interval(self, side: str) -> tuple[float, float]:
        if side not in (*SIDES, NET):
            raise KeyError(f"no such side: {side!r}")
        return getattr(self, f"{side}_low"), getattr(self, f"{side}_high")


class Score(_Frozen):
    """How far predictions fell from what happened, in points per 100 possessions."""

    rmse: float
    mae: float
    r2: float


class Comparison(_Frozen):
    """Another way of making the same prediction, set against the model.

    ``difference`` is the model's error minus this one's for a baseline, and this one's
    minus the model's for an ablation; either way a negative baseline difference or a
    positive ablation difference means the full model predicted better. The interval
    comes from resampling whole seasons.
    """

    key: str
    label: str
    rmse: float
    mae: float
    difference: float
    low: float
    high: float

    @property
    def is_distinguishable(self) -> bool:
        """Whether the interval excludes zero."""
        return self.low > 0 or self.high < 0


class SeasonScore(_Frozen):
    season: str
    teams: int
    rmse: float


class BacktestRow(_Frozen):
    """One team-season predicted from seasons before it."""

    season: str
    team_id: int
    predicted_offense: float
    predicted_defense: float
    actual_offense: float
    actual_defense: float

    @property
    def predicted(self) -> float:
        return self.predicted_offense + self.predicted_defense

    @property
    def actual(self) -> float:
        return self.actual_offense + self.actual_defense


class SameSeason(_Frozen):
    """How a team's ratings add up against its own net rating in the same season."""

    slope: float
    correlation: float


class Validation(_Frozen):
    first_test_season: str
    last_test_season: str
    team_seasons: int
    net: Score
    offense: Score
    defense: Score
    baselines: tuple[Comparison, ...]
    ablations: tuple[Comparison, ...]
    by_season: tuple[SeasonScore, ...]
    same_season: SameSeason

    def baseline(self, key: str) -> Comparison:
        return _named(self.baselines, key)

    def ablation(self, key: str) -> Comparison:
        return _named(self.ablations, key)


class Availability(_Frozen):
    """Next season's share of team minutes, from the last three and age."""

    coefficients: dict[str, float]
    players: int
    rmse: float
    mae: float
    baseline_rmse: float
    """Error of assuming the same share as last season."""
    baseline_mae: float
    difference: float
    low: float
    high: float


class FittedOn(_Frozen):
    """The data a model was fitted on."""

    first_season: str
    last_season: str
    team_seasons: int
    player_seasons: int


class ValueModel(_Frozen):
    """A fitted player value model: weights, levels and the evidence for them."""

    revision: PositiveInt
    fitted_at: datetime
    spec: ValueSpec
    fitted_on: FittedOn
    terms: tuple[Term, ...]
    replacement_level: float
    """Impact, per 100 possessions, of a player any team can find for nothing."""
    availability: Availability
    validation: Validation
    backtest: tuple[BacktestRow, ...]

    @property
    def version(self) -> str:
        """What a row computed with this model is stamped with."""
        return f"r{self.revision}"

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(term.key for term in self.terms)

    def term(self, key: str) -> Term:
        return _named(self.terms, key)

    def weights(self, side: str) -> dict[str, float]:
        """Every term's weight on one side of the ball, or ``net`` for both together."""
        return {term.key: term.weight(side) for term in self.terms}


def _named(items: tuple, key: str):  # type: ignore[no-untyped-def]
    for item in items:
        if item.key == key:
            return item
    raise KeyError(f"nothing named {key!r}; known: {[item.key for item in items]}")
