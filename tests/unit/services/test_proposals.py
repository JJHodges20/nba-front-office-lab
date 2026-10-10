"""Roster proposals: the optimizer's rosters offered for review, and the approved save (A5).

``priced_template`` is the fixture store with an invented 2026-27 salary for every player the
value model projects, so the optimizer can build whole rosters on it. Tests that save take a
private copy.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from front_office.config import load_settings
from front_office.domain.optimizer import BudgetMode, OptimizerRequest
from front_office.domain.proposals import FINGERPRINT_NOTE, RosterProposal
from front_office.domain.tables.rosters import STARTING_SLOTS
from front_office.pipelines.build import build_database
from front_office.services import Lab, OptimizerReport

M = 1_000_000


@pytest.fixture(scope="module")
def shared(priced_template: Path) -> Iterator[Lab]:
    """The priced lab. Read from it; never write to it."""
    with Lab(load_settings(priced_template)) as opened:
        yield opened


@pytest.fixture
def scratch(priced_template: Path, tmp_path: Path) -> Iterator[Lab]:
    target = tmp_path / "lab"
    shutil.copytree(priced_template, target)
    with Lab(load_settings(target)) as opened:
        yield opened


def owners_budget(lab: Lab, **changes: object) -> OptimizerRequest:
    """R01's request: three rosters under an owner's budget of $150M, nothing else asked."""
    asked = {
        "budget_mode": BudgetMode.CUSTOM,
        "budget": 150 * M,
        "solutions": 3,
        "roles": {},
        "bigs": 0,
        **changes,
    }
    return lab.optimizer.defaults().model_copy(update=asked)


@pytest.fixture(scope="module")
def report(shared: Lab) -> OptimizerReport:
    return shared.optimizer.solve(owners_budget(shared))


@pytest.fixture(scope="module")
def proposals(shared: Lab, report: OptimizerReport) -> tuple[RosterProposal, ...]:
    return shared.proposals.from_report(report)


class TestFromReport:
    def test_each_roster_found_is_a_proposal_in_order(
        self, proposals: tuple[RosterProposal, ...], report: OptimizerReport
    ) -> None:
        assert [p.label for p in proposals] == ["Option A", "Option B", "Option C"]
        for proposal, plan in zip(proposals, report.plans, strict=True):
            assert proposal.player_ids == tuple(int(i) for i in plan.players.index)
            assert (proposal.payroll, proposal.room) == (plan.solution.payroll, plan.room)
            assert proposal.rating == plan.solution.rating
            assert (proposal.added, proposal.removed) == (plan.added, plan.removed)
            assert proposal.error == report.error
            assert (proposal.budget, proposal.budget_label) == (150 * M, "Owner's budget")
            assert (proposal.payroll_season, proposal.stats_season) == ("2026-27", "2025-26")
        assert not proposals[0].added and not proposals[0].removed

    def test_salaries_are_the_contract_files(
        self, shared: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        salaries = shared.contracts.salaries("2026-27")["salary"]
        for proposal in proposals:
            assert all(p.salary == int(salaries.at[p.player_id]) for p in proposal.players)
            assert sum(p.salary for p in proposal.players) == proposal.payroll

    def test_five_start_in_different_slots_and_the_rest_are_on_the_bench(
        self, proposals: tuple[RosterProposal, ...]
    ) -> None:
        for proposal in proposals:
            slots = [player.slot for player in proposal.players]
            starting = [slot for slot in slots if slot in STARTING_SLOTS]
            assert sorted(starting) == sorted(STARTING_SLOTS)
            assert slots.count("BENCH") == len(slots) - 5
            # The five with the largest projected share start.
            by_share = sorted(proposal.players, key=lambda p: -p.projected_share)
            assert {p.slot for p in by_share[:5]} == set(STARTING_SLOTS)

    def test_the_basis_is_what_the_lab_holds_now(
        self, shared: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        basis = proposals[0].basis
        status = shared.status()
        assert basis.build_id == status.build_id
        assert basis.value_model == shared.value.status().applied_revision == "r2"
        assert basis.contract_as_of == status.contract_as_of
        assert str(basis.contract_as_of) == "2026-10-01"

    def test_nothing_found_is_no_proposal(self, shared: Lab) -> None:
        report = shared.optimizer.solve(owners_budget(shared, budget=20 * M))
        assert not report.found and shared.proposals.from_report(report) == ()


class TestRequirements:
    def test_what_was_asked_for_is_said_in_words(self, shared: Lab) -> None:
        pool = shared.optimizer.pool()
        locked, left_out = (int(i) for i in pool.index[:2])
        request = owners_budget(
            shared,
            budget_mode=BudgetMode.LUXURY_TAX,
            budget=None,
            roles={"rim_protector": 2, "connector": 1},
            bigs=3,
            locked=(locked,),
            excluded=(left_out,),
        )
        said = shared.proposals.requirements(request, pool)
        assert said[0] == f"{request.players_range} players"
        assert "at least 2 rim protectors" in said and "at least 1 connector" in said
        assert "at least 3 big men" in said
        assert f"must include {pool.at[locked, 'player_name']}" in said
        assert f"leaves out {pool.at[left_out, 'player_name']}" in said


class TestFingerprint:
    def test_the_same_roster_from_the_same_data_has_the_same_fingerprint(
        self, shared: Lab, report: OptimizerReport, proposals: tuple[RosterProposal, ...]
    ) -> None:
        again = shared.proposals.from_report(report)
        assert [p.fingerprint for p in again] == [p.fingerprint for p in proposals]
        assert len({p.fingerprint for p in proposals}) == len(proposals)
        assert all(len(p.fingerprint) == 12 for p in proposals)

    def test_any_difference_changes_it(self, proposals: tuple[RosterProposal, ...]) -> None:
        first = proposals[0]
        other_build = first.model_copy(
            update={"basis": first.basis.model_copy(update={"build_id": 99})}
        )
        assert other_build.fingerprint != first.fingerprint

    def test_the_note_names_where_it_came_from_and_the_fingerprint(
        self, proposals: tuple[RosterProposal, ...]
    ) -> None:
        note = proposals[1].note
        assert note.startswith(FINGERPRINT_NOTE) and "Option B" in note
        assert note.endswith(f"({proposals[1].fingerprint}).")


def with_salary(proposal: RosterProposal, salary: int) -> RosterProposal:
    """The proposal as if the contract file had given its first player another salary."""
    first, *rest = proposal.players
    return proposal.model_copy(
        update={"players": (first.model_copy(update={"salary": salary}), *rest)}
    )


class TestCheck:
    def test_nothing_has_changed(self, shared: Lab, proposals: tuple[RosterProposal, ...]) -> None:
        assert shared.proposals.check(proposals[0]) == ()

    def test_what_changed_is_said_in_plain_sentences(
        self, shared: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        first = proposals[0]
        older = first.basis.model_copy(
            update={"build_id": 1, "value_model": "r1", "contract_as_of": None}
        )
        said = shared.proposals.check(first.model_copy(update={"basis": older}))
        assert said == (
            "The lab's data has been rebuilt since this proposal was made (build 1 then, 2 now).",
            "The player value model has changed since this proposal was made (r1 then, r2 now).",
            "A different contract file has been imported since this proposal.",
        )

    def test_a_salary_that_moved_is_named(
        self, shared: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        moved = with_salary(proposals[0], 1)
        name = moved.players[0].player_name
        assert shared.proposals.check(moved) == (
            f"The contract file no longer gives the same salary for {name}.",
        )


class TestSave:
    def test_an_approved_proposal_is_saved_once(
        self, scratch: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        proposal = proposals[1]
        saved = scratch.proposals.save(proposal, "From the assistant")
        assert saved.created and saved.saved and saved.refused == ()
        assert saved.name == "From the assistant"
        roster = scratch.rosters.get(saved.roster_id)
        assert proposal.fingerprint in roster["notes"]
        assert (roster["stats_season"], roster["payroll_season"]) == ("2025-26", "2026-27")
        members = scratch.rosters.players(saved.roster_id).set_index("player_id")
        assert {int(i): s for i, s in members["slot"].items()} == {
            p.player_id: p.slot for p in proposal.players
        }
        summary = scratch.builder.summary(saved.roster_id)
        assert summary.payroll_total == proposal.payroll, "the Team Builder prices it the same"

        again = scratch.proposals.save(proposal, "Pressed twice")
        assert not again.created and again.saved
        assert (again.roster_id, again.name) == (saved.roster_id, "From the assistant")
        assert len(scratch.rosters.list()) == 1

    def test_another_option_is_another_roster(
        self, scratch: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        one = scratch.proposals.save(proposals[0], "A")
        two = scratch.proposals.save(proposals[2], "C")
        assert one.created and two.created and one.roster_id != two.roster_id

    def test_a_changed_salary_is_refused_and_nothing_is_saved(
        self, scratch: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        saved = scratch.proposals.save(with_salary(proposals[0], 1), "Stale")
        assert not saved.saved and not saved.created
        assert saved.refused and "no longer gives the same salary" in saved.refused[0]
        assert scratch.rosters.list().empty

    def test_a_rebuild_since_the_proposal_is_refused(
        self, scratch: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        assert build_database(scratch.settings).loaded
        saved = scratch.proposals.save(proposals[0], "After the rebuild")
        assert not saved.saved
        assert saved.refused[0].startswith("The lab's data has been rebuilt")
        assert scratch.rosters.list().empty

    def test_a_name_the_lab_refuses_is_said(
        self, scratch: Lab, proposals: tuple[RosterProposal, ...]
    ) -> None:
        saved = scratch.proposals.save(proposals[0], "   ")
        assert not saved.saved and saved.refused
        assert scratch.rosters.list().empty
