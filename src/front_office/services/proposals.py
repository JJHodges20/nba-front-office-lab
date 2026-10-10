"""Roster proposals: the optimizer's rosters offered for review, and the approved save.

Decision 0018 (A5). The assistant's ``optimize_roster`` tool turns each roster the
optimizer finds into a :class:`RosterProposal` the page shows; this service builds them,
and saves one when the user presses the button under it. Before saving it checks that
nothing the proposal rests on has changed - the data build, the value model, the contract
file and the players' salaries - and that no earlier click saved it already, which the
fingerprint in a saved roster's notes tells. The roster and its players are written in one
transaction.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from front_office.domain.optimizer import OptimizerRequest
from front_office.domain.proposals import (
    ProposalBasis,
    ProposedPlayer,
    RosterProposal,
)
from front_office.services.lab import Lab
from front_office.services.optimizer import OptimizerReport
from front_office.storage import StorageError

LABELS = "ABCDEFGHIJ"


@dataclass(frozen=True, slots=True)
class ProposalSaved:
    """What pressing the button did."""

    roster_id: int | None
    name: str | None
    created: bool
    """``False`` when an earlier click had saved it, or when it was refused."""
    refused: tuple[str, ...] = ()
    """Why it was not saved, in plain sentences."""

    @property
    def saved(self) -> bool:
        return self.roster_id is not None


class ProposalService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    def basis(self) -> ProposalBasis:
        """What a proposal made now rests on."""
        status = self._lab.status()
        return ProposalBasis(
            build_id=status.build_id,
            value_model=self._lab.value.status().applied_revision,
            contract_as_of=status.contract_as_of,
        )

    def from_report(self, report: OptimizerReport) -> tuple[RosterProposal, ...]:
        """Each roster the optimizer found, as a proposal: ``Option A`` first."""
        if not report.found:
            return ()
        optimizer = self._lab.optimizer
        pool = optimizer.pool()
        basis = self.basis()
        request = report.request
        requirements = self.requirements(request, pool)
        proposals = []
        for position, plan in enumerate(report.plans):
            slots = dict(optimizer.slots(plan.solution.player_ids, pool))
            players = tuple(
                ProposedPlayer(
                    player_id=int(player_id),
                    player_name=str(row["player_name"]),
                    team=row["team"] if isinstance(row["team"], str) else None,
                    position=row["position"] if isinstance(row["position"], str) else None,
                    slot=slots[int(player_id)],
                    salary=int(row["salary"]),
                    projected_impact=float(row["projected_impact"]),
                    projected_share=float(row["projected_share"]),
                    projected_wins=float(row["projected_wins"]),
                )
                for player_id, row in plan.players.iterrows()
            )
            proposals.append(
                RosterProposal(
                    label=f"Option {LABELS[position]}",
                    payroll_season=request.payroll_season,
                    stats_season=request.stats_season,
                    budget_mode=request.budget_mode.value,
                    budget_label=request.budget_mode.title,
                    budget=report.budget,
                    requirements=requirements,
                    players=players,
                    payroll=plan.solution.payroll,
                    room=plan.room,
                    added=plan.added,
                    removed=plan.removed,
                    rating=plan.solution.rating,
                    error=report.error,
                    basis=basis,
                )
            )
        return tuple(proposals)

    def requirements(self, request: OptimizerRequest, pool: pd.DataFrame) -> tuple[str, ...]:
        """What a request asks of a roster, in plain words."""
        names = {item.key: item.name.lower() for item in self._lab.fit.archetypes()}
        known = pool["player_name"] if "player_name" in pool else pd.Series(dtype="object")
        said = [f"{request.players_range} players"]
        said += [
            f"at least {count} {names.get(key, key.replace('_', ' '))}"
            + ("s" if count != 1 else "")
            for key, count in request.roles.items()
            if count
        ]
        for group, count in (
            ("guards", request.guards),
            ("wings", request.wings),
            ("big men", request.bigs),
        ):
            if count:
                said.append(f"at least {count} {group}")
        if request.locked:
            said.append("must include " + ", ".join(_named(known, request.locked)))
        if request.excluded:
            said.append("leaves out " + ", ".join(_named(known, request.excluded)))
        return tuple(said)

    def check(self, proposal: RosterProposal) -> tuple[str, ...]:
        """What has changed since the proposal was made, in plain sentences; nothing when
        it can still be saved as shown."""
        now = self.basis()
        then = proposal.basis
        changed = []
        if now.build_id != then.build_id:
            changed.append(
                f"The lab's data has been rebuilt since this proposal was made (build "
                f"{then.build_id} then, {now.build_id} now)."
            )
        if now.value_model != then.value_model:
            changed.append(
                f"The player value model has changed since this proposal was made "
                f"({then.value_model} then, {now.value_model} now)."
            )
        if now.contract_as_of != then.contract_as_of:
            changed.append("A different contract file has been imported since this proposal.")
        if self._lab.contracts.available:
            salaries = self._lab.contracts.salaries(proposal.payroll_season)["salary"]
        else:
            salaries = pd.Series(dtype="int64")
        moved = [
            player.player_name
            for player in proposal.players
            if player.player_id not in salaries.index
            or int(salaries.at[player.player_id]) != player.salary
        ]
        if moved:
            changed.append(
                "The contract file no longer gives the same salary for " + ", ".join(moved) + "."
            )
        return tuple(changed)

    def saved_as(self, proposal: RosterProposal) -> pd.Series | None:
        """The roster an earlier click saved this proposal as, if any: its notes carry the
        proposal's fingerprint."""
        rosters = self._lab.rosters.list()
        if rosters.empty:
            return None
        mark = f"({proposal.fingerprint})"
        found = rosters[rosters["notes"].fillna("").str.contains(mark, regex=False)]
        return None if found.empty else found.iloc[0]

    def save(self, proposal: RosterProposal, name: str) -> ProposalSaved:
        """Save the proposal as a Team Builder roster, in one transaction - unless an
        earlier click saved it already, or something it rests on has changed."""
        earlier = self.saved_as(proposal)
        if earlier is not None:
            return ProposalSaved(int(earlier["roster_id"]), str(earlier["name"]), created=False)
        changed = self.check(proposal)
        if changed:
            return ProposalSaved(None, None, created=False, refused=changed)
        try:
            roster_id = self._lab.rosters.create_with_players(
                name,
                stats_season=proposal.stats_season,
                payroll_season=proposal.payroll_season,
                players=[(player.player_id, player.slot) for player in proposal.players],
                notes=proposal.note,
            )
        except StorageError as error:
            return ProposalSaved(None, None, created=False, refused=(str(error),))
        saved = self._lab.rosters.get(roster_id)
        return ProposalSaved(roster_id, str(saved["name"]), created=True)


def _named(known: pd.Series, players: tuple[int, ...]) -> list[str]:
    return [str(known.get(int(player), f"player {player}")) for player in players]
