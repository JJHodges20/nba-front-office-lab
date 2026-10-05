"""The Roster Optimizer page: what it shows must be what the optimizer service returns.

``plain_home`` is the fixture store without contracts (nothing to build under);
``contract_template`` the same with nine priced players and 2026-27's cap rules;
``optimizer_home`` the invented league with every projected player priced, under no cap
rules; ``scratch_home`` a copy with contracts that a test may save a roster into.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import load_settings
from front_office.domain.optimizer import OptimizerRequest
from front_office.services import Lab
from tests.helpers import TATUM
from tests.ui.conftest import figures, texts
from tests.ui.test_pages import frame_with
from wb import formats
from wb.views.optimizer import REQUEST

SIX = {"min_players": 5, "max_players": 6, "roles": {}, "bigs": 0, "solutions": 3, "distinct_by": 1}
FEASIBLE = {"roles": {"floor_spacer": 2, "secondary_creator": 1}, "solutions": 3}


def service(home: Path):  # type: ignore[no-untyped-def]
    return Lab(load_settings(home))


def asked(home: Path, **changes: object) -> OptimizerRequest:
    with service(home) as lab:
        return lab.optimizer.defaults().model_copy(update=changes)


class TestThePage:
    def test_it_says_what_it_is_and_what_it_needs(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "optimizer")
        said = texts(opened)
        assert [title.value for title in opened.title] == ["Roster Optimizer"]
        assert "Several strong rosters under a budget" in said
        assert "Modeled" in said and "Derived" in said and "Your assumption" in said
        assert "**The optimizer needs more than it has**" in said
        assert "No salaries for 2026-27 are on file" in said and "fol contracts import FILE" in said
        assert not opened.button

    def test_with_contracts_it_describes_the_pool_and_offers_the_form(
        self, page, contract_template: Path
    ) -> None:
        opened = page(contract_template, "optimizer")
        said = texts(opened)
        assert "9 players have both a projection for 2026-27 and a salary for it on file" in said
        assert "Roles and positions are the players' in 2025-26" in said
        assert opened.button[0].label == "Find rosters"
        assert "rosters under $" not in said

    def test_submitting_the_form_runs_the_request_as_set(
        self, page, contract_template: Path
    ) -> None:
        opened = page(contract_template, "optimizer")
        opened.slider(key="opt_size").set_range(5, 6)
        with service(contract_template) as lab:
            keys = lab.fit.archetypes().keys
        for key in keys:
            opened.number_input(key=f"opt_role_{key}").set_value(0)
        opened.number_input(key="opt_bigs").set_value(0)
        opened.slider(key="opt_solutions").set_value(2)
        opened.slider(key="opt_distinct").set_value(1)
        opened.multiselect(key="opt_locked").select(TATUM)
        opened.button[0].click().run()
        assert not opened.exception, [error.value for error in opened.exception]
        request = opened.session_state[REQUEST]
        assert (request.min_players, request.max_players, request.roles, request.bigs) == (
            5,
            6,
            {},
            0,
        )
        assert (request.solutions, request.distinct_by, request.budget) == (2, 1, None)
        assert request.budget_mode.value == "salary_cap" and request.locked == (TATUM,)
        players = frame_with(opened, "player_name", "salary", "projected_share")
        assert "Jayson Tatum" in players["player_name"].tolist()
        assert f"2 rosters under {formats.money_compact(164_961_000)}" in texts(opened)
        assert [tab.label for tab in opened.tabs][-2:] == ["Roster 1", "Roster 2"]


class TestTheRosters:
    @pytest.fixture
    def opened(self, page, contract_template: Path):  # type: ignore[no-untyped-def]
        return page(contract_template, "optimizer", **{REQUEST: asked(contract_template, **SIX)})

    def test_the_comparison_and_the_figures_are_the_services(
        self, opened, contract_template: Path
    ) -> None:
        request = asked(contract_template, **SIX)
        with service(contract_template) as lab:
            report = lab.optimizer.solve(request)
        said = texts(opened)
        assert f"{len(report.plans)} rosters under {formats.money_compact(report.budget)}" in said
        assert f"From {report.pool_size} players" in said and f"±{report.error:.1f}" in said
        table = frame_with(opened, "Roster", "Projected rating", "Payroll")
        assert table["Projected rating"].tolist() == pytest.approx(
            [p.solution.rating for p in report.plans]
        )
        assert table["Payroll"].tolist() == [p.solution.payroll for p in report.plans]
        # Every roster's tab is drawn at once and the figures helper keeps the last tile
        # under each label, so the tiles are the last roster's.
        last = report.plans[-1]
        shown = figures(opened)
        assert shown["Projected rating"][0] == f"{last.solution.rating:+.1f}"
        assert shown["Payroll"] == (
            formats.money_compact(last.solution.payroll),
            f"{formats.money_compact(last.room)} under the budget",
        )
        assert shown["Share of cap"][0] == formats.share(last.payroll.cap_share)
        assert shown["Minutes"] == (
            formats.share(last.solution.minutes_covered, 0),
            "of a season's, as projected",
        )
        first = report.plans[0]
        players = frame_with(opened, "player_name", "salary", "projected_share")
        assert players["player_name"].tolist() == first.players["player_name"].tolist()
        assert "Nothing here is a recommendation" in said

    def test_an_impossible_request_explains_itself(self, page, contract_template: Path) -> None:
        opened = page(contract_template, "optimizer", **{REQUEST: asked(contract_template)})
        said = texts(opened)
        assert "**No roster meets these requirements**" in said
        assert "only 9 players are available and a roster needs at least 14." in said

    def test_a_rating_nothing_reaches_is_dropped_and_noted(
        self, page, contract_template: Path
    ) -> None:
        opened = page(
            contract_template,
            "optimizer",
            **{REQUEST: asked(contract_template, **SIX, min_rating=99.0)},
        )
        said = texts(opened)
        assert "No roster reaches a projected rating of +99.0" in said
        assert "rosters under" in said

    def test_the_invented_league_builds_under_an_owners_budget(
        self, page, optimizer_home: Path
    ) -> None:
        request = asked(optimizer_home, **FEASIBLE)
        opened = page(optimizer_home, "optimizer", **{REQUEST: request})
        with service(optimizer_home) as lab:
            report = lab.optimizer.solve(request)
        said = texts(opened)
        assert (
            request.budget_mode.value == "custom"
            and f"under {formats.money_compact(request.budget)}" in said
        )
        table = frame_with(opened, "Roster", "Projected rating", "Payroll")
        assert len(table) == len(report.plans) > 1
        assert "Share of cap" not in figures(opened)  # no cap rules for the invented season
        assert "Against Roster 1: in " in said


class TestSaving:
    def test_a_roster_is_saved_into_the_team_builder(self, page, scratch_home: Path) -> None:
        request = asked(scratch_home, **SIX)
        opened = page(scratch_home, "optimizer", **{REQUEST: request})
        opened.text_input(key="opt_name_1").set_value("From the optimizer")
        opened.button(key="opt_save_1").click().run()
        assert not opened.exception, [error.value for error in opened.exception]
        assert not opened.error, [error.value for error in opened.error]
        assert [note.value for note in opened.success] == [
            "Saved as “From the optimizer”. The Team Builder has it."
        ]
        with service(scratch_home) as lab:
            rosters = lab.builder.rosters().set_index("name")
            report = lab.optimizer.solve(request)
            members = lab.rosters.players(int(rosters.at["From the optimizer", "roster_id"]))
        assert set(members["player_id"]) == set(report.plans[0].players.index)
