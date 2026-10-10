"""A roster proposal: a roster the optimizer found, offered for the user to review and save.

Decision 0018 (A5). The assistant never saves anything. When it runs the optimizer, each
roster found becomes a draft the page shows with everything it rests on - its players and
their salaries, the payroll against the budget, the requirements asked for, the projected
rating with the model's typical miss, and the data it was made from. Saving it is the
user's click, and the application first checks that nothing the proposal rests on has
changed. The fingerprint names the proposal: it is written into the saved roster's notes,
so that a second click finds the roster saved by the first rather than saving it twice.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

FINGERPRINT_NOTE = "Saved from AI Research proposal"
"""How a saved roster's notes begin; the fingerprint follows."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProposedPlayer(_Frozen):
    player_id: int
    player_name: str
    team: str | None = None
    position: str | None = None
    slot: str
    """Where the save would put the player: a starting position or the bench."""
    salary: int = Field(ge=0)
    """The contract file's salary for the payroll season."""
    projected_impact: float
    projected_share: float
    projected_wins: float


class ProposalBasis(_Frozen):
    """What a proposal rests on, checked again before it is saved."""

    build_id: int | None
    value_model: str | None
    """The value model revision the build applied."""
    contract_as_of: date | None
    """The date the contract file was current, as stated at import."""


class RosterProposal(_Frozen):
    """One roster the optimizer found, as the user reviews it."""

    label: str
    """``Option A``, ``Option B``...: how the answer and the page name it."""
    payroll_season: str
    stats_season: str
    budget_mode: str
    budget_label: str
    """The budget in words: "Salary cap", "Owner's budget"."""
    budget: int = Field(gt=0)
    requirements: tuple[str, ...] = ()
    """What the user asked for, in words: roles, groups, players locked in or left out."""
    players: tuple[ProposedPlayer, ...]
    payroll: int = Field(ge=0)
    room: int
    """Dollars left under the budget, as the optimizer reports it."""
    added: tuple[str, ...] = ()
    """Players this roster holds that the first option does not."""
    removed: tuple[str, ...] = ()
    """Players the first option holds that this one does not."""
    rating: float
    """Projected net rating relative to the league: the sum of the parts."""
    error: float | None
    """What the value model's forecasts of a team have typically missed by (RMSE)."""
    basis: ProposalBasis

    @property
    def fingerprint(self) -> str:
        """Twelve hex digits naming everything in the proposal: the same roster made from
        the same data has the same fingerprint, and any difference changes it."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    @property
    def note(self) -> str:
        """What the saved roster's notes say: where it came from, and its fingerprint."""
        return f"{FINGERPRINT_NOTE} {self.label} ({self.fingerprint})."

    @property
    def player_ids(self) -> tuple[int, ...]:
        return tuple(player.player_id for player in self.players)
