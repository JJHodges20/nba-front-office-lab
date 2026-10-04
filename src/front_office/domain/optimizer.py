"""The roster optimizer: what the user asks for, and what comes back.

Version 5 of the roadmap: a payroll budget and roster requirements go in, and several
strong, distinct rosters come out - several, because the weights behind any one "best"
roster are assumptions. Everything the optimizer maximises is the value model's
projection of the players, each taken alone, and everything it respects is written here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

ON_COURT = 5
"""Players on the court: a season has five players' worth of minutes to give."""
MAX_SOLUTIONS = 10
MAX_PLAYERS = 21
"""The offseason roster limit: nothing larger is a roster."""


class BudgetMode(StrEnum):
    """What the payroll may not exceed."""

    SALARY_CAP = "salary_cap"
    LUXURY_TAX = "luxury_tax"
    FIRST_APRON = "first_apron"
    SECOND_APRON = "second_apron"
    CUSTOM = "custom"

    @property
    def title(self) -> str:
        return {
            "salary_cap": "Salary cap",
            "luxury_tax": "Luxury tax line",
            "first_apron": "First apron",
            "second_apron": "Second apron",
            "custom": "Owner's budget",
        }[self.value]


class OptimizerRequest(BaseModel):
    """Everything a run is asked to respect. Frozen, so a run can be cached on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payroll_season: str
    """The season the salaries and the cap lines come from: the one being built for."""
    stats_season: str
    """The season the players' roles and groups are read from: the latest played."""
    budget_mode: BudgetMode = BudgetMode.SALARY_CAP
    budget: PositiveInt | None = None
    """The owner's budget in dollars, when the mode is custom."""
    enforce_minimum_salary: bool = False
    """Whether the payroll must also reach the season's minimum team salary."""
    min_players: int = Field(default=14, ge=5, le=MAX_PLAYERS)
    max_players: int = Field(default=15, ge=5, le=MAX_PLAYERS)
    roles: dict[str, int] = Field(default_factory=dict)
    """Archetype key to the least number of players who must fill it."""
    guards: int = Field(default=0, ge=0)
    wings: int = Field(default=0, ge=0)
    bigs: int = Field(default=0, ge=0)
    min_rating: float | None = None
    """The least projected net rating, relative to the league, a roster must reach."""
    max_salary: PositiveInt | None = None
    """No player paid more than this, unless locked in."""
    min_age: int | None = Field(default=None, ge=16)
    max_age: int | None = Field(default=None, le=50)
    locked: tuple[int, ...] = ()
    """Players every roster must hold."""
    excluded: tuple[int, ...] = ()
    """Players no roster may hold."""
    solutions: int = Field(default=5, ge=1, le=MAX_SOLUTIONS)
    distinct_by: int = Field(default=3, ge=1, le=MAX_PLAYERS)
    """How many players any two rosters must differ by."""
    minutes_slack: float = Field(default=0.1, ge=0, le=1)
    """How far the players' projected minutes may exceed a season's: everyone then plays
    a little less than projected, and the rating is scaled down to say so."""
    time_limit: float = Field(default=20.0, gt=0)
    """Seconds the solver may spend on one roster."""

    @model_validator(mode="after")
    def _consistent(self) -> OptimizerRequest:
        if self.max_players < self.min_players:
            raise ValueError("max_players must be at least min_players")
        if self.budget_mode is BudgetMode.CUSTOM and self.budget is None:
            raise ValueError("a custom budget needs an amount")
        if self.min_age is not None and self.max_age is not None and self.max_age < self.min_age:
            raise ValueError("max_age must be at least min_age")
        for key, count in self.roles.items():
            if count < 0:
                raise ValueError(f"the count for {key} cannot be negative")
        if set(self.locked) & set(self.excluded):
            raise ValueError("a player cannot be both locked in and excluded")
        if len(self.locked) > self.max_players:
            raise ValueError("more players are locked in than the roster may hold")
        return self

    @property
    def players_range(self) -> str:
        if self.min_players == self.max_players:
            return str(self.min_players)
        return f"{self.min_players} to {self.max_players}"


@dataclass(frozen=True, slots=True)
class RosterSolution:
    """One roster the optimizer found."""

    number: int
    player_ids: tuple[int, ...]
    payroll: int
    rating: float
    """Projected net rating relative to the league with the players' minutes scaled to a
    season where they add up to more than one."""
    rating_unscaled: float
    """The same before scaling: what the solver maximised."""
    shares: float
    """What the players' projected shares of a team's minutes add up to; five is a season."""
    roles: dict[str, int]
    guards: int
    wings: int
    bigs: int

    @property
    def players(self) -> int:
        return len(self.player_ids)

    @property
    def minutes_covered(self) -> float:
        return self.shares / ON_COURT


@dataclass(frozen=True, slots=True)
class OptimizerOutcome:
    """What a run produced: the rosters, or the reasons there are none."""

    status: str
    """``optimal``, ``time_limit`` (a roster was found, not proven best), ``infeasible``
    or ``no_pool``."""
    solutions: tuple[RosterSolution, ...]
    relaxed_rating: bool = False
    """Whether the least rating asked for could not be met and was dropped."""
    reasons: tuple[str, ...] = ()
    """Why nothing, or less, could be found; plain sentences."""

    @property
    def found(self) -> bool:
        return bool(self.solutions)
