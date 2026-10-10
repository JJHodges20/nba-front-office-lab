"""The ``optimize_roster`` tool (A5): rosters as proposals, what was asked for and nothing
else, and nothing saved. ``priced`` is the fixture build with an invented 2026-27 salary for
every projected player (``priced_template``); figures are compared with the services' own."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from front_office.assistant import tools as t
from front_office.assistant.executor import MAX_CHARACTERS, Executor
from front_office.assistant.proposal_tools import NOT_A_PLAN, SAVED_BY_THE_USER
from front_office.assistant.routing import Call
from front_office.assistant.toolbox import LAB_HANDLERS
from front_office.config import load_settings
from front_office.domain.assistant import EvidenceKind, ResultStatus
from front_office.services import Lab, OptimizerService

OK, EMPTY, UNAVAILABLE, ERROR = (
    ResultStatus.OK,
    ResultStatus.EMPTY,
    ResultStatus.UNAVAILABLE,
    ResultStatus.ERROR,
)
R01 = {"budget_mode": "custom", "budget_millions": 150, "options": 3}
R03 = {"budget_mode": "luxury_tax", "role_minimums": [{"role": "rim_protector", "count": 2}]}


@pytest.fixture(scope="module")
def priced(priced_template: Path) -> Iterator[Lab]:
    with Lab(load_settings(priced_template)) as opened:
        yield opened


def run(lab: Lab, **arguments):  # type: ignore[no-untyped-def]
    return LAB_HANDLERS["optimize_roster"](lab, t.OptimizeRoster(**arguments))


@pytest.fixture(scope="module")
def r01(priced: Lab):  # type: ignore[no-untyped-def]
    return run(priced, **R01)


class TestOptions:
    def test_rosters_under_an_owners_budget_go_out_as_proposals(self, priced: Lab, r01) -> None:  # type: ignore[no-untyped-def]
        assert r01.status is OK and r01.title == "Roster options for 2026-27"
        assert [p.label for p in r01.proposals] == ["Option A", "Option B", "Option C"]
        pool = len(priced.optimizer.pool())
        assert r01.text.startswith(
            "3 roster options for 2026-27, each under the owner's budget of $150,000,000. "
            f"They are picked from the {pool} players who have both a 2026-27 salary and a "
            "forecast, and each option differs from the others by at least 3 players. "
            "What was asked for: 14 to 15 players."
        )
        for proposal in r01.proposals:
            assert proposal.budget == 150_000_000 and proposal.payroll <= proposal.budget
            row = (
                f"| {proposal.label} | ${proposal.payroll:,} | ${proposal.room:,} | "
                f"{proposal.rating:+.1f} | {len(proposal.players)} |"
            )
            assert row in r01.text
        first = r01.proposals[0]
        assert f"typically been off by about {first.error:.2f} points" in r01.text
        assert NOT_A_PLAN in r01.text and SAVED_BY_THE_USER in r01.text
        assert len(r01.text) <= MAX_CHARACTERS, "the model reads every option whole"

    def test_every_salary_named_is_in_the_text(self, r01) -> None:  # type: ignore[no-untyped-def]
        for proposal in r01.proposals:
            for player in proposal.players:
                assert f"{player.player_name} (${player.salary:,})" in r01.text

    def test_the_others_are_described_against_option_a(self, r01) -> None:  # type: ignore[no-untyped-def]
        table = r01.table.set_index("Option")
        assert table.at["Option A", "Against Option A"] == "—"
        second = r01.proposals[1]
        assert table.at["Option B", "Against Option A"] == (
            f"in: {', '.join(second.added)}; out: {', '.join(second.removed)}"
        )

    def test_the_page_gets_a_chart_and_the_evidence(self, priced: Lab, r01) -> None:  # type: ignore[no-untyped-def]
        (chart,) = r01.charts
        assert chart.kind == "bars" and list(chart.frame["option"]) == [
            p.label for p in r01.proposals
        ]
        kinds = {item.kind for item in r01.evidence}
        assert kinds == {EvidenceKind.CONTRACTS, EvidenceKind.LAB, EvidenceKind.MODEL}
        assert set(r01.kinds) == {"derived", "modeled", "assumption"}, "the optimizer page's"

    def test_roles_asked_for_are_kept(self, priced: Lab) -> None:
        found = run(priced, **R03)
        assert found.status is OK and "at least 2 rim protectors" in found.text
        assert "each under the luxury tax line of $" in found.text
        pool = priced.optimizer.pool()
        for proposal in found.proposals:
            assert pool.loc[list(proposal.player_ids), "fills_rim_protector"].sum() >= 2

    def test_locked_and_left_out_players(self, priced: Lab, r01) -> None:  # type: ignore[no-untyped-def]
        pool = priced.optimizer.pool()
        chosen = set(r01.proposals[0].player_ids)
        outside = next(int(i) for i in pool.index if int(i) not in chosen)
        inside = r01.proposals[0].player_ids[0]
        found = run(priced, **R01, lock_player_ids=[outside], exclude_player_ids=[inside])
        assert found.status is OK
        for proposal in found.proposals:
            assert outside in proposal.player_ids and inside not in proposal.player_ids
        named = pool.at[outside, "player_name"]
        assert f"must include {named}" in found.text

    def test_fewer_options_than_asked_are_said(self, priced: Lab, r01, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        solve = OptimizerService.solve

        def two_only(self, request):  # type: ignore[no-untyped-def]
            report = solve(self, request)
            outcome = replace(report.outcome, solutions=report.outcome.solutions[:2])
            return replace(report, outcome=outcome, plans=report.plans[:2])

        monkeypatch.setattr(OptimizerService, "solve", two_only)
        found = run(priced, **R01)
        assert len(found.proposals) == 2
        assert "3 options were asked for; only 2 meet the requirements" in found.text

    def test_a_run_that_ran_out_of_time_says_so(self, priced: Lab, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        solve = OptimizerService.solve

        def timed_out(self, request):  # type: ignore[no-untyped-def]
            report = solve(self, request)
            return replace(report, outcome=replace(report.outcome, status="time_limit"))

        monkeypatch.setattr(OptimizerService, "solve", timed_out)
        found = run(priced, **R01)
        assert found.status is OK
        assert any("ran out of time" in warning for warning in found.warnings)

    def test_nothing_is_saved(self, priced: Lab, r01) -> None:  # type: ignore[no-untyped-def]
        assert priced.rosters.list().empty


class TestNothingFound:
    def test_too_small_a_budget_says_why(self, priced: Lab) -> None:
        found = run(priced, budget_mode="custom", budget_millions=20)
        assert found.status is EMPTY and not found.proposals
        assert found.text.startswith(
            "No roster for 2026-27 meets these requirements under the owner's budget of "
            "$20,000,000. The 14 cheapest available players already cost $"
        )
        assert {item.kind for item in found.evidence} >= {EvidenceKind.CONTRACTS}

    def test_the_contracts_database_prices_too_few_players(self, contract_lab: Lab) -> None:
        """R01 and R03 ran here until A5: nine priced players make no roster."""
        found = run(contract_lab, **R01)
        assert found.status is EMPTY
        assert "Only 9 players are available and a roster needs at least 14" in found.text

    def test_without_a_contract_file_it_cannot_run(self, lab: Lab) -> None:
        found = run(lab, **R01)
        assert found.status is UNAVAILABLE
        assert found.text == f"The optimizer cannot run: {lab.optimizer.status().reason}"

    def test_an_unknown_role_lists_the_roles(self, priced: Lab) -> None:
        found = run(
            priced, budget_mode="salary_cap", role_minimums=[{"role": "rim_wizard", "count": 1}]
        )
        assert found.status is ERROR and found.text.startswith("No role called rim_wizard.")
        assert "rim_protector (Rim Protector)" in found.text


class TestThroughTheExecutor:
    def test_a_locked_player_the_lab_does_not_hold_is_refused(self, priced: Lab) -> None:
        result = Executor(priced).run(
            Call("optimize_roster", {"budget_mode": "salary_cap", "lock_player_ids": [99]}, None)
        )
        assert result.status is ERROR and "no player with id 99" in result.text
        assert not result.proposals

    def test_the_proposals_reach_the_result(self, priced: Lab, r01) -> None:  # type: ignore[no-untyped-def]
        result = Executor(priced).run(Call("optimize_roster", R01, None))
        assert result.usable and result.text == r01.text
        assert [p.fingerprint for p in result.proposals] == [p.fingerprint for p in r01.proposals]
