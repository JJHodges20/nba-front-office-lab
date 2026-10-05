"""The Scenario Simulator page: what it shows must be what the simulator service returns.

``plain_home`` is the fixture store with the files the lab ships; ``simulator_home`` the
invented league with the parameters measured on it; ``scratch_home`` a copy of the
fixture store with contracts that a test may add a roster to.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from front_office.config import load_settings, simulator_model_path
from front_office.domain.scenario import Scenario, SubjectKind
from front_office.services import Lab, probability_key
from tests.helpers import BOS, BROWN, PRITCHARD, TATUM, WHITE
from tests.ui.conftest import drawn, figures, texts
from wb import formats, state
from wb.views.simulator import AVAILABILITY, REMOVE, SAVE, SUBJECT, TABS, TEAM

TITLE = probability_key("won_championship")


def service(home: Path) -> Lab:
    return Lab(load_settings(home))


def table_having(opened: AppTest, *columns: str):  # type: ignore[no-untyped-def]
    return next(
        frame.value for frame in opened.dataframe if set(columns) <= set(frame.value.columns)
    )


def default_report(home: Path, team: int):  # type: ignore[no-untyped-def]
    """What the service says for the team with nothing changed, as the page asks it."""
    with service(home) as lab:
        simulations = lab.simulator.model().spec.simulations
        return lab.simulator.run(
            Scenario(subject=SubjectKind.TEAM, key=team, simulations=simulations)
        )


class TestThePage:
    def test_it_says_what_it_is_and_draws_the_first_team(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "simulator")
        said = texts(opened)
        assert [title.value for title in opened.title] == ["Scenario Simulator"]
        assert "What a change to a roster would do to its season" in said
        assert "Modeled" in said and "Your assumption" in said
        assert [tab.label for tab in opened.tabs] == list(TABS)
        assert "Nothing is changed yet" in said and "Out of date" not in said
        assert "Projected wins" in figures(opened)

    def test_without_parameters_it_says_how_to_measure_them(
        self, page, plain_home: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "home"
        shutil.copytree(plain_home, target)
        simulator_model_path(target / "configs").unlink()
        opened = page(target, "simulator")
        said = texts(opened)
        assert "**The simulator cannot run yet**" in said
        assert "fol simulate fit --write" in said and not opened.tabs

    def test_the_sidebar_team_is_the_subject_and_the_figures_are_the_services(
        self, page, plain_home: Path
    ) -> None:
        opened = page(plain_home, "simulator", **{state.TEAM: BOS})
        report = default_report(plain_home, BOS)
        shown = figures(opened)
        after = report.after
        assert shown["Projected net rating"] == (f"{after.rating:+.1f}", f"was {after.rating:+.1f}")
        assert shown["Projected wins"][0] == f"{after.wins:.0f}"
        assert shown["Winning the title"][0] == formats.share(after.chance("won_championship"))
        assert shown["Payroll"][0] == formats.MISSING
        assert f"**Boston Celtics** as it stands for {report.season}" in texts(opened)
        table = table_having(opened, "Figure", "Before", "After", "Change")
        assert table["Figure"].tolist() == report.comparison["label"].tolist()
        assert (table["Change"] == "+0.0").sum() >= 3
        charts = drawn(opened)
        assert {"sim_stages", "sim_wins"} <= set(charts)
        dots = charts["sim_stages"].data
        assert [trace.name for trace in dots] == ["Before", "After"]
        assert list(dots[1].x) == pytest.approx(after.stages["probability"].tolist())

    def test_removing_a_player_shows_before_and_after(self, page, plain_home: Path) -> None:
        report = default_report(plain_home, BOS)
        best = int(report.players.index[0])
        name = str(report.players.at[best, "player_name"])
        opened = page(plain_home, "simulator", **{state.TEAM: BOS, REMOVE: [best]})
        said = texts(opened)
        assert f"removed {name}" in said and "Nothing is changed yet" not in said
        with service(plain_home) as lab:
            changed = lab.simulator.run(
                Scenario(
                    subject=SubjectKind.TEAM,
                    key=BOS,
                    removed=(best,),
                    simulations=lab.simulator.model().spec.simulations,
                )
            )
        shown = figures(opened)
        assert shown["Projected net rating"] == (
            f"{changed.after.rating:+.1f}",
            f"was {changed.before.rating:+.1f}",
        )
        assert changed.after.rating < changed.before.rating
        assert f"Removed: {name}." in said

    def test_an_emptied_roster_says_so_instead_of_an_empty_table(
        self, page, plain_home: Path
    ) -> None:
        report = default_report(plain_home, BOS)
        everyone = [int(p) for p in report.players.index]
        opened = page(plain_home, "simulator", **{state.TEAM: BOS, REMOVE: everyone})
        assert not opened.exception
        said = texts(opened)
        assert "Nobody is left on the roster" in said
        assert "Shares add up to 0.00 of the five on the floor" in said

    def test_a_preset_is_named_in_the_caption(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "simulator", **{state.TEAM: BOS, AVAILABILITY: "healthy"})
        assert "games missed: healthy season" in texts(opened)

    def test_the_players_table_carries_the_projections(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "simulator", **{state.TEAM: BOS})
        report = default_report(plain_home, BOS)
        said = texts(opened)
        assert "Everything you type is your assumption" in said
        assert f"Shares add up to {report.after.shares:.2f} of the five on the floor" in said
        assert "Typical rotation players miss" in said


class TestTheSeasonAhead:
    def test_every_team_is_drawn(self, page, simulator_home: Path) -> None:
        opened = page(simulator_home, "simulator")
        with service(simulator_home) as lab:
            league = lab.simulator.league()
        table = table_having(opened, "team_name", "wins", TITLE)
        assert table["team_name"].tolist() == league["team_name"].tolist()
        assert table["wins"].tolist() == pytest.approx(league["wins"].tolist())
        dots = drawn(opened)["sim_league"].data[-1]
        assert list(dots.x) == pytest.approx(league["wins"].tolist())
        assert "is drawn at" in texts(opened)


class TestTheEvidence:
    def test_the_figures_are_the_parameters(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "simulator")
        with service(plain_home) as lab:
            model = lab.simulator.model()
        shown = figures(opened)
        assert shown["Wins per point"] == (
            f"{model.wins_per_point:.2f}",
            f"for {model.wins_season}",
        )
        assert shown["A season's own noise"][0] == f"{model.season_noise:.2f}"
        coverage = table_having(opened, "Interval", "Held the wins that happened")
        assert coverage["Interval"].tolist() == [f"{c.level:.0%}" for c in model.test.coverage]
        bands = table_having(opened, "Projection reliability", "Typical size")
        assert len(bands) == len(model.development)
        assert "The field is not in it" in texts(opened)


class TestABuiltRoster:
    @pytest.fixture
    def roster(self, scratch_home: Path) -> int:
        with service(scratch_home) as lab:
            roster_id = lab.builder.create("Scenario roster")
            for player in (TATUM, BROWN, PRITCHARD):
                lab.builder.add_player(roster_id, player)
            lab.builder.add_player(roster_id, WHITE, assumed_salary=28_000_000)
        return roster_id

    def test_the_roster_is_priced_and_can_be_saved(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "simulator", **{SUBJECT: "roster"})
        shown = figures(opened)
        assert shown["Payroll"][0] == formats.money_compact(
            40_000_000 + 30_000_000 + 7_000_000 + 28_000_000
        )
        assert "**Scenario roster** as it stands" in texts(opened)
        opened.button(key=SAVE).click().run()
        assert not opened.exception and "Saved as roster" in " ".join(
            element.value for element in opened.success
        )
        with service(scratch_home) as lab:
            rosters = lab.builder.rosters()
            saved = int(rosters["roster_id"].max())
            summary = lab.builder.summary(saved)
        assert (
            len(rosters) == 2
            and rosters.set_index("roster_id").at[saved, "name"] == "Scenario roster scenario"
        )
        assert set(summary.players.index) == {TATUM, BROWN, PRITCHARD, WHITE}
        assert summary.players.at[WHITE, "salary"] == 28_000_000

    def test_the_team_selector_changes_the_subject(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "simulator", **{TEAM: 1610612752})
        assert "**New York Knicks** as it stands" in texts(opened)
