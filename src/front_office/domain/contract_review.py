"""A contract file checked against the one in use, before anything is imported (A7).

The contract-update review of decision 0018: a candidate file - a newer copy of the dataset
in use, or another source's - is read and matched exactly as an import would read it, and
compared with the file in use, season by season and team by team. What could be wrong is
said in plain sentences: a source never imported before, whose terms the user has not
checked; figures older than those in use; names the league's index does not hold; seasons
without cap rules. Nothing is stored: the import stays the user's own command, once they
have checked the source (``fol contracts import``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class ContractChange:
    """One player's salary from one team for one season, in use and in the candidate."""

    player_id: int
    player: str
    team: str | None
    """The team's abbreviation; ``None`` where the file gives no team."""
    season: str
    in_use: int | None
    """The salary in the file in use; ``None`` where it lists none."""
    candidate: int | None
    """The salary in the candidate; ``None`` where it lists none."""
    detail: str | None = None
    """What else changed: an option or a guarantee."""

    @property
    def kind(self) -> str:
        if self.in_use is None:
            return "new"
        if self.candidate is None:
            return "gone"
        return "changed"

    @property
    def difference(self) -> int:
        """The candidate's salary less the one in use; a missing one counts as nothing."""
        return (self.candidate or 0) - (self.in_use or 0)


@dataclass(frozen=True, slots=True)
class InUse:
    """The contract file the lab's figures come from now."""

    file_name: str
    source_label: str
    as_of: date
    imported_at: datetime


@dataclass(frozen=True, slots=True)
class ContractPreview:
    file_name: str
    source_label: str
    as_of: date
    rows_read: int
    players: int
    seasons: tuple[str, ...]
    in_use: InUse | None
    changes: tuple[ContractChange, ...]
    """Largest change first."""
    unchanged: int
    """Player-team-seasons with the same salary, option and guarantee in both."""
    unmatched: tuple[str, ...]
    """Rows an import would leave out, each with its line and why."""
    flags: tuple[str, ...]
    """What to check before importing, in plain sentences."""
    command: str
    """The import, to run once the source is checked."""

    def count(self, kind: str) -> int:
        return sum(change.kind == kind for change in self.changes)
