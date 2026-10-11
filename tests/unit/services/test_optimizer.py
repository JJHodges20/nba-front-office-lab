"""The optimizer service: the pool, the budget, the rosters found, and saving one.

``optimizer_home`` is the invented league with every projected player under an invented
contract for the season ahead (no cap rules for that season, so budgets are the owner's);
``contract_lab`` the fixture store with nine priced players and 2026-27's cap rules;
``lab`` the fixture store without contracts.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from front_office.config import load_settings
from front_office.domain.cap_rules import PayrollLine
from front_office.domain.lineup import ROTATION
from front_office.domain.optimizer import BudgetMode, OptimizerRequest
from front_office.domain.tables.rosters import STARTING_SLOTS
from front_office.modeling.optimizer import SALARY_TIE_BREAK
from front_office.services import Lab, OptimizerError, OptimizerReport
from front_office.services.optimizer import (
    EXAMPLE_BIGS,
    EXAMPLE_ROLES,
    GROUP_COLUMNS,
    PLAN_COLUMNS,
)
from tests.conftest import invented_salary

M = 1_000_000


@pytest.fixture(scope="module")
def optimizer_lab(optimizer_home: Path) -> Iterator[Lab]:
    with Lab(load_settings(optimizer_home)) as opened:
        yield opened


FEASIBLE_ROLES = {"floor_spacer": 2, "secondary_creator": 1}
"""Roles the invented league can supply; it has about one primary creator a season."""


def feasible(request: OptimizerRequest) -> OptimizerRequest:
    return request.model_copy(update={"roles": FEASIBLE_ROLES})


@pytest.fixture(scope="module")
def default_report(optimizer_lab: Lab) -> OptimizerReport:
    return optimizer_lab.optimizer.solve(feasible(optimizer_lab.optimizer.defaults()))


class TestStatus:
    def test_the_invented_league_is_ready_without_cap_rules(self, optimizer_lab: Lab) -> None:
        status = optimizer_lab.optimizer.status()
        assert status.is_available and status.reason is None
        assert (status.payroll_season, status.stats_season) == ("2009-10", "2008-09")
        assert not status.has_rules
        assert status.projected == status.priced == status.pool > 50

    def test_without_salaries_it_says_what_it_needs(self, lab: Lab) -> None:
        status = lab.optimizer.status()
        assert not status.is_available and status.priced == 0 and status.projected > 0
        assert status.reason.startswith("no salaries for 2026-27 are on file")
        with pytest.raises(OptimizerError, match="no salaries for 2026-27"):
            lab.optimizer.solve(lab.optimizer.defaults())

    def test_the_fixture_store_with_contracts(self, contract_lab: Lab) -> None:
        status = contract_lab.optimizer.status()
        assert status.is_available and status.has_rules
        assert (status.payroll_season, status.stats_season) == ("2026-27", "2025-26")
        assert status.priced == 9 and status.pool == 9


class TestThePool:
    def test_everyone_projected_with_a_salary_and_what_is_known_of_them(
        self, optimizer_lab: Lab
    ) -> None:
        pool = optimizer_lab.optimizer.pool()
        ahead = optimizer_lab.value.projections()
        assert pool.index.name == "player_id" and set(pool.index) == set(ahead.index)
        for column in (*PLAN_COLUMNS, *GROUP_COLUMNS, "fills_primary_creator", "fills_connector"):
            assert column in pool.columns, column
        assert pool["projected_wins"].is_monotonic_decreasing
        player = int(pool.index[3])
        assert pool.at[player, "salary"] == invented_salary(
            player, ahead.at[player, "projected_wins"]
        )
        assert pool.at[player, "projected_impact"] == ahead.at[player, "projected_impact"]
        roles = optimizer_lab.value.roles("2008-09")
        with_role = pool.index.intersection(roles.index)
        assert len(with_role) > 10
        assert pool.loc[with_role, "roles"].tolist() == roles.loc[with_role, "roles"].tolist()
        assert pool[list(GROUP_COLUMNS)].dtypes.eq(bool).all()
        assert pool["in_bigs"].sum() > 0 and pool["fills_floor_spacer"].sum() > 0

    def test_without_contracts_the_pool_is_empty(self, lab: Lab) -> None:
        pool = lab.optimizer.pool()
        assert pool.empty and "salary" in pool.columns


class TestDefaults:
    def test_without_cap_rules_an_owners_budget_from_the_payrolls_on_file(
        self, optimizer_lab: Lab
    ) -> None:
        request = optimizer_lab.optimizer.defaults()
        assert request.budget_mode is BudgetMode.CUSTOM
        payrolls = optimizer_lab.contracts.team_payrolls("2009-10")["team_salary"]
        assert request.budget == round(payrolls.median() / M) * M
        assert (request.min_players, request.max_players) == (13, 15)
        assert request.roles == EXAMPLE_ROLES and request.bigs == EXAMPLE_BIGS
        assert (request.payroll_season, request.stats_season) == ("2009-10", "2008-09")

    def test_with_cap_rules_the_cap_and_the_roster_limits(self, contract_lab: Lab) -> None:
        request = contract_lab.optimizer.defaults()
        assert request.budget_mode is BudgetMode.SALARY_CAP and request.budget == 164_961_000
        assert (request.min_players, request.max_players) == (14, 15)
        assert contract_lab.optimizer.budget_for(request) == 164_961_000
        lines = contract_lab.rules("2026-27").thresholds
        assert (
            contract_lab.optimizer.budget_for(
                request.model_copy(update={"budget_mode": BudgetMode.LUXURY_TAX})
            )
            == lines.luxury_tax
        )
        assert (
            contract_lab.optimizer.budget_for(
                request.model_copy(update={"budget_mode": BudgetMode.CUSTOM, "budget": 7 * M})
            )
            == 7 * M
        )

    def test_a_cap_line_without_cap_rules_is_refused(self, optimizer_lab: Lab) -> None:
        request = optimizer_lab.optimizer.defaults().model_copy(
            update={"budget_mode": BudgetMode.FIRST_APRON}
        )
        with pytest.raises(
            OptimizerError, match="no cap rules are configured for 2009-10, so first apron"
        ):
            optimizer_lab.optimizer.budget_for(request)
        with pytest.raises(OptimizerError, match="no cap rules"):
            optimizer_lab.optimizer.solve(request)


class TestSolving:
    def test_the_defaults_find_several_rosters_that_keep_the_rules(
        self, optimizer_lab: Lab, default_report: OptimizerReport
    ) -> None:
        report = default_report
        request = report.request
        assert report.found and report.outcome.status == "optimal"
        assert 1 < len(report.plans) <= request.solutions
        assert report.budget == request.budget and report.pool_size == len(
            optimizer_lab.optimizer.pool()
        )
        assert report.error == optimizer_lab.value.model().validation.net.rmse
        for plan in report.plans:
            solution = plan.solution
            assert (
                solution.payroll <= report.budget and plan.room == report.budget - solution.payroll
            )
            assert request.min_players <= solution.players <= request.max_players
            assert all(solution.roles[key] >= count for key, count in request.roles.items())
            assert solution.bigs >= request.bigs
            assert solution.shares <= 5 * (1 + request.minutes_slack) + 1e-9
            assert solution.minutes_covered == pytest.approx(solution.shares / 5)
            assert plan.payroll is None  # no cap rules for the season
            players = plan.players
            assert tuple(players.columns) == PLAN_COLUMNS and len(players) == solution.players
            assert players["projected_share"].is_monotonic_decreasing
            assert players["salary"].sum() == solution.payroll
        first = report.plans[0]
        assert first.added == () and first.removed == ()
        second = report.plans[1]
        assert len(second.added) >= request.distinct_by
        assert set(second.added) <= set(second.players["player_name"])
        assert set(second.removed) <= set(first.players["player_name"])
        # Best first by what the solver maximised: the parts, less a hair for the payroll.
        objective = [
            p.solution.rating_unscaled - SALARY_TIE_BREAK * p.solution.payroll for p in report.plans
        ]
        assert all(a >= b - 1e-4 for a, b in zip(objective, objective[1:], strict=False))

    def test_the_rating_is_the_sum_of_the_parts_above_replacement(
        self, optimizer_lab: Lab, default_report: OptimizerReport
    ) -> None:
        replacement = optimizer_lab.value.model().replacement_level
        plan = default_report.plans[0]
        players = plan.players
        parts = ((players["projected_impact"] - replacement) * players["projected_share"]).sum()
        assert plan.solution.rating_unscaled == pytest.approx(5 * replacement + parts)
        scale = min(1.0, 5 / players["projected_share"].sum())
        assert plan.solution.rating == pytest.approx(5 * replacement + scale * parts)

    def test_locks_exclusions_and_a_tighter_budget(
        self, optimizer_lab: Lab, default_report: OptimizerReport
    ) -> None:
        service = optimizer_lab.optimizer
        pool = service.pool()
        star = int(pool.index[0])
        cheap = int(pool.sort_values("salary").index[0])
        asked = default_report.request.model_copy(
            update={
                "locked": (cheap,),
                "excluded": (star,),
                "solutions": 2,
                "budget": default_report.budget // 2,
            }
        )
        report = service.solve(asked)
        if report.found:
            for plan in report.plans:
                assert cheap in plan.players.index and star not in plan.players.index
                assert plan.solution.payroll <= asked.budget
        else:
            assert report.outcome.reasons

    def test_the_fixture_stores_nine_under_the_cap(self, contract_lab: Lab) -> None:
        asked = contract_lab.optimizer.defaults().model_copy(
            update={
                "min_players": 5,
                "max_players": 6,
                "roles": {},
                "bigs": 0,
                "solutions": 3,
                "distinct_by": 1,
            }
        )
        report = contract_lab.optimizer.solve(asked)
        assert report.found and report.budget == 164_961_000
        plan = report.plans[0]
        assert plan.payroll is not None and plan.payroll.total == plan.solution.payroll
        assert plan.payroll.position(PayrollLine.SALARY_CAP).room == plan.room
        assert plan.players["team"].isin(["BOS", "NYK"]).any()

    def test_requirements_nobody_can_meet_come_back_with_reasons(self, contract_lab: Lab) -> None:
        asked = contract_lab.optimizer.defaults()  # fourteen players from a pool of nine
        report = contract_lab.optimizer.solve(asked)
        assert not report.found and report.outcome.status == "infeasible"
        assert (
            report.outcome.reasons[0]
            == "only 9 players are available and a roster needs at least 14."
        )

    def test_the_roadmaps_example_cannot_be_met_on_this_league(self, optimizer_lab: Lab) -> None:
        report = optimizer_lab.optimizer.solve(optimizer_lab.optimizer.defaults())
        assert not report.found and report.outcome.status == "infeasible"
        assert report.outcome.reasons[0].endswith(
            "fill the primary creator role and 2 are required."
        )

    def test_a_request_for_another_season_is_refused(self, optimizer_lab: Lab) -> None:
        asked = optimizer_lab.optimizer.defaults().model_copy(update={"payroll_season": "2026-27"})
        with pytest.raises(OptimizerError, match="rosters are built for 2009-10"):
            optimizer_lab.optimizer.solve(asked)


class TestSaving:
    @pytest.fixture
    def scratch(self, optimizer_home: Path, tmp_path: Path) -> Iterator[Lab]:
        target = tmp_path / "lab"
        shutil.copytree(optimizer_home, target)
        with Lab(load_settings(target)) as opened:
            yield opened

    def test_a_roster_is_saved_with_its_starters_in_slots(
        self, scratch: Lab, default_report: OptimizerReport
    ) -> None:
        plan = default_report.plans[0]
        roster = scratch.optimizer.save(
            plan.players.index.tolist(), "Optimised A", default_report.request
        )
        rosters = scratch.builder.rosters().set_index("roster_id")
        assert rosters.at[roster, "name"] == "Optimised A"
        assert (
            rosters.at[roster, "stats_season"] == "2008-09"
            and rosters.at[roster, "payroll_season"] == "2009-10"
        )
        members = scratch.rosters.players(roster).set_index("player_id")
        assert set(members.index) == set(plan.players.index)
        starters = members[members["slot"].isin(STARTING_SLOTS)]
        assert len(starters) == 5 and starters["slot"].is_unique
        # Placed as domain.lineup places them: starters from the rotation, each at a position
        # they are listed at where the roster allows (the user's wish at the A5 review), the
        # most projected impact first among lineups that fit (at the A6 review).
        assert (
            dict(scratch.optimizer.slots(plan.players.index.tolist())) == members["slot"].to_dict()
        )
        assert set(starters.index) <= set(plan.players.index[:ROTATION])
        summary = scratch.builder.summary(roster)
        assert summary.payroll_total == plan.solution.payroll
        assert summary.priced == len(members) and summary.assumed == 0 and summary.unpriced == 0

    def test_saving_describes_the_roster_with_the_fit_service_too(
        self, scratch: Lab, default_report: OptimizerReport
    ) -> None:
        plan = default_report.plans[1]
        roster = scratch.optimizer.save(
            plan.players.index.tolist(), "Optimised B", default_report.request
        )
        report = scratch.fit.roster(roster)
        # Members are weighed by last season's minutes; a player projected from older
        # seasons alone has none and is named as absent.
        assert report.name == "Optimised B"
        assert len(report.members) + len(report.absent) == plan.solution.players
        assert isinstance(report.parts.projected, float)
