"""The Roster Fit page: what it shows must be what the fit service returns.

``plain_home`` is the fixture store valued by the shipped model, with the evidence the
lab ships; ``fitted_home`` an invented league with no evidence on file; ``scratch_home``
a copy with contracts that a test may add a roster to.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from front_office.config import fit_evidence_path, load_settings
from front_office.services import Lab
from tests.helpers import BOS, BROWN, PRITCHARD, TATUM, WHITE
from tests.ui.conftest import drawn, figures, texts
from tests.ui.test_pages import frame_with
from wb import formats, state
from wb.views.fit import TABS

SEASON = "2025-26"


def service(home: Path):  # type: ignore[no-untyped-def]
    return Lab(load_settings(home))


@pytest.fixture
def boston(page, plain_home: Path):  # type: ignore[no-untyped-def]
    return page(plain_home, "fit", **{state.TEAM: BOS})


@pytest.fixture
def report(plain_home: Path):  # type: ignore[no-untyped-def]
    with service(plain_home) as lab:
        return lab.fit.team(BOS, SEASON)


class TestThePage:
    def test_it_says_what_it_is_and_asks_for_a_subject(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "fit")
        said = texts(opened)
        assert [title.value for title in opened.title] == ["Roster Fit"]
        assert "Do these players make sense together?" in said
        assert "Modeled" in said and "Derived" in said and "Measured" not in said
        assert [tab.label for tab in opened.tabs][:4] == list(TABS)
        assert "**Choose a team**" in said and "Out of date" not in said

    def test_with_a_team_chosen_it_says_who_and_how_weighted(self, boston, report) -> None:
        said = texts(boston)
        assert f"**Boston Celtics, {SEASON}**: {len(report.members)} players, each weighted" in said
        assert "**Choose a team**" not in said

    def test_a_season_without_profiles_says_so(self, page, plain_home: Path) -> None:
        opened = page(plain_home, "fit", **{state.TEAM: BOS, state.SEASON: "1996-97"})
        assert "**No profiles for 1996-97**" in texts(opened)

    def test_without_evidence_the_profile_is_description_only(
        self, page, fitted_home: Path
    ) -> None:
        opened = page(fitted_home, "fit", **{state.TEAM: 101, state.SEASON: "2008-09"})
        said = texts(opened)
        assert "No fit evidence has been gathered yet, so the profile is description only" in said
        assert "**No fit evidence has been gathered**" in said
        assert figures(opened)["Fit correction"] == ("None", "the evidence supports none")

    def test_evidence_from_another_model_is_flagged(
        self, page, plain_home: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "home"
        shutil.copytree(plain_home, target)
        path = fit_evidence_path(target / "configs")
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"value_model_version": "r2"', '"value_model_version": "r3"'
            ),
            encoding="utf-8",
        )
        said = texts(page(target, "fit", **{state.TEAM: BOS}))
        assert "The evidence on file was gathered against value model r3 and roles v1" in said


class TestCoverage:
    def test_the_roles_table_is_the_services(self, boston, report) -> None:
        table = frame_with(boston, "name", "count", "filled_by")
        assert table["name"].tolist() == report.coverage["name"].tolist()
        assert table["count"].tolist() == report.coverage["count"].tolist()
        assert table["filled_by"].tolist() == report.coverage["filled_by"].tolist()
        missing = report.coverage[report.coverage["count"] == 0]["name"].tolist()
        said = texts(boston)
        if missing:
            assert "Nobody in the rotation fills:" in said and missing[0] in said

    def test_the_members_table_is_the_services(self, boston, report) -> None:
        table = frame_with(boston, "player_name", "minutes", "in_rotation")
        assert table["player_name"].tolist() == report.members["player_name"].tolist()
        assert table["in_rotation"].tolist() == report.members["in_rotation"].tolist()
        assert table["impact"].tolist() == pytest.approx(
            report.members["impact"].tolist(), nan_ok=True
        )
        assert "Select a row to make that player the subject" in texts(boston)


class TestProfile:
    def test_the_chart_draws_each_measures_percentile(self, boston, report) -> None:
        (bars,) = drawn(boston)["fit_profile"].data
        placed = report.placed[report.placed["percentile"].notna()]
        assert list(bars.x) == pytest.approx(placed["percentile"].tolist())
        assert list(bars.y) == placed["name"].tolist()
        assert f"Each measure beside the {int(placed['teams'].max())} teams of {SEASON}" in texts(
            boston
        )

    def test_the_tables_by_area_carry_value_median_and_rank(self, boston, report) -> None:
        table = frame_with(boston, "shown", "median_shown", "standing")
        offense = report.placed[report.placed["area"] == "Offense"].set_index("key")
        assert table["name"].tolist() == offense["name"].tolist()
        first = offense.iloc[0]
        assert table["standing"].iloc[0] == formats.rank_of(int(first["rank"]), int(first["teams"]))
        assert table["direction"].tolist()[0] == "no better or worse"


class TestParts:
    def test_the_figures_are_the_services(self, boston, report) -> None:
        shown = figures(boston)
        parts = report.parts
        placed = report.placed.set_index("key")
        rank = formats.rank_of(
            int(placed.at["impact_sum", "rank"]), int(placed.at["impact_sum", "teams"])
        )
        assert shown["Impact, sum of parts"] == (f"{parts.impact:+.1f}", f"{rank} in {SEASON}")
        assert shown["The model's miss"] == (
            f"±{parts.error:.1f} (RMSE)",
            "on seasons it had not seen",
        )
        assert shown["Minutes covered"][0] == formats.share(parts.minutes_covered, 0)
        assert shown["Fit correction"] == ("None", "the evidence supports none")
        assert "no better, so nothing is added to the sum of the parts" in texts(boston)


class TestEvidence:
    def test_the_tables_are_the_evidences(self, boston, plain_home: Path) -> None:
        with service(plain_home) as lab:
            evidence = lab.fit.evidence()
            champions = lab.fit.champions()
        alone = frame_with(boston, "coefficient", "rmse", "change")
        assert alone["name"].tolist() == [item.name for item in evidence.measures]
        assert alone["rmse"].tolist() == pytest.approx([item.rmse for item in evidence.measures])
        without = frame_with(boston, "Left out", "RMSE", "Change")
        assert without["Left out"].tolist() == [item.label for item in evidence.combined.ablations]
        said = texts(boston)
        assert (
            "**The correction is applied to rosters**"
            if evidence.combined.is_usable
            else "**No correction is applied to rosters**"
        ) in said
        standing = frame_with(boston, "median_percentile", "top_third")
        assert standing["name"].tolist() == champions["name"].tolist()
        assert f"team-seasons, {evidence.first_test_season} to {evidence.last_test_season}" in said


class TestARoster:
    @pytest.fixture
    def roster(self, scratch_home: Path) -> int:
        with service(scratch_home) as lab:
            roster_id = lab.builder.create("Fit roster")
            for player in (TATUM, BROWN, PRITCHARD, WHITE):
                lab.builder.add_player(roster_id, player)
        return roster_id

    def test_a_built_roster_is_profiled_in_its_statistics_season(
        self, page, scratch_home: Path, roster: int
    ) -> None:
        opened = page(scratch_home, "fit", fit_subject="Built roster", fit_roster=roster)
        with service(scratch_home) as lab:
            report = lab.fit.roster(roster)
        said = texts(opened)
        assert (
            f"**Fit roster**: 4 players, each weighted by the minutes played in {report.season}"
            in said
        )
        table = frame_with(opened, "player_name", "minutes", "in_rotation")
        assert table["player_name"].tolist() == report.members["player_name"].tolist()
        assert figures(opened)["Minutes covered"][0] == formats.share(
            report.parts.minutes_covered, 0
        )
        assert "nothing here says how they would play together" in said
        # Four players have no bench, so the bench measures have no standing and no bar.
        (bars,) = drawn(opened)["fit_profile"].data
        with_standing = report.placed[report.placed["percentile"].notna()]
        assert len(with_standing) < len(report.placed)
        assert list(bars.y) == with_standing["name"].tolist()
        assert "Bench impact" not in list(bars.y)
