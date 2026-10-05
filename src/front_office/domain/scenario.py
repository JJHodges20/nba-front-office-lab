"""A scenario: a roster for the season ahead, and the assumptions laid over it.

Version 7 of the roadmap: modify a roster and compare the expected effects on payroll,
team strength and postseason outlook. A scenario names its subject - a real team as it
stands for the season ahead, or a roster built in the Team Builder - the players added
and removed, and for any player the games they are expected to miss, a development
adjustment to their projected impact, the share of the team's minutes they are to play,
or a salary; and two presets that apply to everyone. Every figure in a scenario is the
user's assumption, and every screen that shows one says so.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SIMULATIONS = 50_000
MIN_SIMULATIONS = 100
FULL_SEASON_GAMES = 82
MAX_PLAYERS = 21
"""The offseason roster limit: nothing larger is a roster."""
MAX_DEVELOPMENT = 10.0
"""Points of impact a development adjustment may reach either way."""


class SubjectKind(StrEnum):
    """What a scenario starts from."""

    TEAM = "team"
    """A real team: the players whose current team it is, with their projections."""
    ROSTER = "roster"
    """A roster built in the Team Builder."""


class Availability(StrEnum):
    """How many games the players miss: a preset applied to everyone without a figure of
    their own."""

    AS_PROJECTED = "as_projected"
    HEALTHY = "healthy"
    HIGH_INJURY = "high_injury"

    @property
    def title(self) -> str:
        return {
            "as_projected": "As projected",
            "healthy": "Healthy season",
            "high_injury": "High-injury season",
        }[self.value]

    @property
    def description(self) -> str:
        return {
            "as_projected": "Each player misses games the way rotation players have: the "
            "projected share of minutes already allows for it, and each simulated season "
            "draws a player's missed games from what has happened.",
            "healthy": "Nobody misses a game: each player plays the share a full season "
            "would give them. An optimistic assumption.",
            "high_injury": "Every player misses as many games as the worst quarter of "
            "rotation players' seasons, give or take what happens. A pessimistic assumption.",
        }[self.value]


class Development(StrEnum):
    """How the players' impacts move from their projections: a preset applied to everyone
    without a figure of their own."""

    EXPECTED = "expected"
    OPTIMISTIC = "optimistic"
    REGRESSION = "regression"

    @property
    def title(self) -> str:
        return {
            "expected": "As projected",
            "optimistic": "Optimistic improvement",
            "regression": "Regression",
        }[self.value]

    @property
    def description(self) -> str:
        return {
            "expected": "Each player's impact is drawn around the value model's projection, "
            "as far off as projections of players that well known have come out.",
            "optimistic": "Each player comes out one typical miss better than projected, "
            "with the same spread. An assumption.",
            "regression": "Each player comes out one typical miss worse than projected, "
            "with the same spread. An assumption.",
        }[self.value]


class Adjustment(BaseModel):
    """What the user assumes about one player; a field left empty takes the preset or
    the projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    games_missed: float | None = Field(default=None, ge=0, le=FULL_SEASON_GAMES)
    """Games the player is expected to miss, out of a full season."""
    development: float | None = Field(default=None, ge=-MAX_DEVELOPMENT, le=MAX_DEVELOPMENT)
    """Points of impact added to the projection: how much better or worse the player is
    assumed to come out."""
    share: float | None = Field(default=None, ge=0, le=1)
    """The share of the team's minutes the player is to play, in place of the projection."""
    salary: int | None = Field(default=None, ge=0)
    """A salary assumed for the player, in place of the contract file's."""

    @property
    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (self.games_missed, self.development, self.share, self.salary)
        )


class Scenario(BaseModel):
    """A subject, the changes to it, and the presets. Frozen, so a run can be cached on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: SubjectKind
    key: int
    """The team id or the roster id."""
    added: tuple[int, ...] = ()
    """Players brought in: signings, or the players coming back in a trade."""
    removed: tuple[int, ...] = ()
    """Players let go or sent away."""
    adjustments: dict[int, Adjustment] = Field(default_factory=dict)
    """By player id: what the user assumes about a player."""
    availability: Availability = Availability.AS_PROJECTED
    development: Development = Development.EXPECTED
    simulations: int = Field(default=10_000, ge=MIN_SIMULATIONS, le=MAX_SIMULATIONS)
    seed: int = 0

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if set(self.added) & set(self.removed):
            raise ValueError("a player cannot be both added and removed")
        if len(set(self.added)) != len(self.added):
            raise ValueError("a player is added twice")
        if len(set(self.removed)) != len(self.removed):
            raise ValueError("a player is removed twice")
        touched = set(self.adjustments) & set(self.removed)
        if touched:
            raise ValueError(f"players {sorted(touched)} are removed and also adjusted")
        return self

    @property
    def is_changed(self) -> bool:
        """Whether anything differs from the subject as it stands."""
        return bool(
            self.added
            or self.removed
            or any(not item.is_empty for item in self.adjustments.values())
            or self.availability is not Availability.AS_PROJECTED
            or self.development is not Development.EXPECTED
        )

    @property
    def baseline(self) -> Scenario:
        """The same subject with nothing changed: what "before" means."""
        return Scenario(
            subject=self.subject,
            key=self.key,
            simulations=self.simulations,
            seed=self.seed,
        )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    def adjustment(self, player_id: int) -> Adjustment:
        return self.adjustments.get(int(player_id), Adjustment())
