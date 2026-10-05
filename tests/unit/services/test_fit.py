"""The fit service: a team or a built roster profiled the way every team was in the build,
placed among the season's teams, with the evidence read off the file.

``value_lab`` is the invented league; ``lab`` the fixture store (two real teams of one
season); ``fitted_home`` a league with a fitted model and no evidence on file.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from front_office.config import fit_evidence_path, load_settings
from front_office.domain.fit import MEASURE_KEYS, ROTATION_SIZE, STARTERS
from front_office.modeling.fit import FIT_METRICS
from front_office.services import FitReport, Lab
from front_office.services.fit import (
    CHAMPIONS_COLUMNS,
    COVERAGE_COLUMNS,
    MEMBER_COLUMNS,
    PLACED_COLUMNS,
)
from tests.unit.services.conftest import ABDELNABY, BOS, BROWN, PRITCHARD, TATUM, WHITE

SEASON = "2006-07"
TEAM = 103


@pytest.fixture(scope="module")
def team_report(value_lab: Lab) -> FitReport:
    return value_lab.fit.team(TEAM, SEASON)


class TestStatus:
    def test_the_evidence_on_file_and_what_the_database_holds(self, lab: Lab) -> None:
        status = lab.fit.status()
        assert status.is_gathered and status.revision == 2
        assert (status.value_model_version, status.applied_value_version) == ("r2", "r2")
        assert (status.archetype_version, status.applied_archetype_version) == ("v1", "v1")
        assert status.is_current and status.team_seasons > 100
        # The evidence the lab ships supports no correction.
        assert not status.usable
        assert status.seasons == ("2025-26",)
        assert lab.fit.evidence().revision == 2 and lab.fit.metrics is FIT_METRICS

    def test_without_evidence_the_profiles_are_description_only(self, fitted_home: Path) -> None:
        with Lab(load_settings(fitted_home)) as opened:
            status = opened.fit.status()
            assert opened.fit.evidence() is None
        assert not status.is_gathered and not status.is_current and not status.usable
        assert status.revision is None and status.team_seasons == 0
        assert len(status.seasons) == 9 and status.seasons[0] == "2008-09"

    def test_evidence_from_another_model_is_not_current(self, value_home: Path, tmp_path) -> None:
        target = tmp_path / "copy"
        shutil.copytree(value_home, target)
        path = fit_evidence_path(target / "configs")
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"value_model_version": "r2"', '"value_model_version": "r9"'
            ),
            encoding="utf-8",
        )
        with Lab(load_settings(target)) as opened:
            status = opened.fit.status()
        assert status.is_gathered and status.value_model_version == "r9"
        assert status.applied_value_version == "r1" and not status.is_current


class TestATeam:
    def test_who_it_is_and_who_plays(self, team_report: FitReport, value_lab: Lab) -> None:
        report = team_report
        assert (report.kind, report.key, report.season) == ("team", TEAM, SEASON)
        assert report.name == value_lab.team_labels().at[TEAM, "full_name"]
        members = report.members
        assert tuple(members.columns) == MEMBER_COLUMNS and members.index.name == "player_id"
        assert members["minutes"].is_monotonic_decreasing and (members["minutes"] > 0).all()
        assert members["share"].sum() == pytest.approx(1.0)
        assert members["in_rotation"].tolist() == [True] * ROTATION_SIZE + [False] * (
            len(members) - ROTATION_SIZE
        )
        assert members["on_bench"].tolist()[:ROTATION_SIZE] == [False] * STARTERS + [True] * (
            ROTATION_SIZE - STARTERS
        )
        assert set(members["team"]) == {value_lab.team_labels().at[TEAM, "abbreviation"]}
        assert not report.is_empty and report.absent == () and report.unprofiled == ()

    def test_the_members_carry_their_roles_and_their_value(
        self, team_report: FitReport, value_lab: Lab
    ) -> None:
        members = team_report.members
        roles = value_lab.value.roles(SEASON)
        season = value_lab.value.season(SEASON)
        for player in members.index[:5]:
            assert members.at[player, "impact"] == season.at[player, "impact"]
            assert members.at[player, "wins_added"] == season.at[player, "wins_added"]
            if player in roles.index:
                assert members.at[player, "roles"] == roles.at[player, "roles"]
            else:
                assert pd.isna(members.at[player, "roles"])

    def test_the_profile_is_the_row_the_build_stored_for_the_team(
        self, team_report: FitReport, value_lab: Lab
    ) -> None:
        stored = value_lab.read("team_fit_profiles", {"season": SEASON, "team_id": TEAM}).iloc[0]
        for key in MEASURE_KEYS:
            assert team_report.profile[key] == pytest.approx(stored[key], nan_ok=True, abs=1e-9), (
                key
            )

    def test_placed_among_the_seasons_teams(self, team_report: FitReport, value_lab: Lab) -> None:
        placed = team_report.placed
        assert tuple(placed.columns) == PLACED_COLUMNS and placed["key"].tolist() == list(
            MEASURE_KEYS
        )
        teams = value_lab.read("team_fit_profiles", {"season": SEASON})
        row = placed.set_index("key").loc["impact_sum"]
        values = teams["impact_sum"]
        mine = team_report.profile["impact_sum"]
        assert row["value"] == mine and row["teams"] == len(teams) == 10
        assert row["median"] == values.median()
        assert row["percentile"] == pytest.approx(100 * ((values < mine).sum() + 0.5) / len(values))
        assert row["rank"] == (values > mine).sum() + 1
        assert row["higher_is_better"] is True or row["higher_is_better"] == True  # noqa: E712
        assert placed.set_index("key").at["usage_sum", "higher_is_better"] is None or pd.isna(
            placed.set_index("key").at["usage_sum", "higher_is_better"]
        )

    def test_coverage_counts_the_rotation_and_names_the_best(
        self, team_report: FitReport, value_lab: Lab
    ) -> None:
        coverage = team_report.coverage
        assert tuple(coverage.columns) == COVERAGE_COLUMNS
        assert coverage["archetype"].tolist() == list(value_lab.fit.archetypes().keys)
        by_role = coverage.set_index("archetype")
        profile = team_report.profile
        assert by_role.at["primary_creator", "count"] == profile["primary_creators"]
        assert by_role.at["floor_spacer", "count"] == profile["spacers"]
        assert by_role.at["rim_protector", "count"] == profile["rim_protectors"]
        assert (coverage["bench_count"] <= coverage["count"]).all()
        rotation = team_report.members[team_report.members["in_rotation"]]
        for row in coverage.itertuples():
            names = [name for name in row.filled_by.split(", ") if name]
            assert len(names) == row.count
            assert set(names) <= set(rotation["player_name"])
            if row.count:
                assert row.best_player in set(rotation["player_name"])
                assert row.best_score >= 67
        scores = value_lab.read(
            "player_archetypes", {"season": SEASON, "archetype": "floor_spacer"}
        )
        best = scores[scores["player_id"].isin(rotation.index)].nlargest(1, "score").iloc[0]
        assert by_role.at["floor_spacer", "best_score"] == best["score"]
        assert (
            by_role.at["floor_spacer", "best_player"]
            == rotation.at[best["player_id"], "player_name"]
        )

    def test_the_sum_of_parts_and_no_correction(
        self, team_report: FitReport, value_lab: Lab
    ) -> None:
        parts = team_report.parts
        assert parts.impact == team_report.profile["impact_sum"]
        assert parts.projected == team_report.profile["projected_sum"]
        assert parts.error == value_lab.value.model().validation.net.rmse
        assert parts.minutes_covered == pytest.approx(1.0, abs=1e-3)
        assert parts.unprofiled_share < 0.01
        assert parts.correction is None

    def test_a_team_with_nobody_on_record_is_empty(self, value_lab: Lab, lab: Lab) -> None:
        nobody = value_lab.fit.team(999, SEASON)
        assert nobody.is_empty and nobody.name == "Team 999"
        assert nobody.profile.drop("minutes_covered").isna().all()
        assert nobody.coverage["count"].eq(0).all() and nobody.placed["percentile"].isna().all()
        early = lab.fit.team(BOS, "1996-97")
        assert early.is_empty and early.name == "Boston Celtics"

    def test_on_the_fixture_store(self, lab: Lab) -> None:
        report = lab.fit.team(BOS, "2025-26")
        assert report.name == "Boston Celtics" and len(report.members) > 15
        assert "Jayson Tatum" in set(report.members["player_name"])
        coverage = report.coverage.set_index("archetype")
        # Tatum fills the primary creator role but played too little to be in the rotation.
        outside = report.members[~report.members["in_rotation"]]
        assert "Jayson Tatum" in set(outside["player_name"])
        assert coverage.at["primary_creator", "count"] == 1
        assert coverage.at["primary_creator", "filled_by"] == "Jaylen Brown"
        assert "Jayson Tatum" not in coverage["filled_by"].str.cat(sep=", ")
        assert report.placed["teams"].max() > 2  # placed among every team's row, fragments too
        assert report.parts.correction is None


class TestARoster:
    @pytest.fixture
    def roster(self, scratch_lab: Lab) -> int:
        roster = scratch_lab.builder.create("Fit roster")
        for player in (TATUM, BROWN, PRITCHARD, WHITE):
            scratch_lab.builder.add_player(roster, player)
        scratch_lab.builder.add_player(roster, ABDELNABY)  # retired: no minutes this season
        return roster

    def test_its_players_for_the_minutes_they_played_last_season(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        report = scratch_lab.fit.roster(roster)
        assert (report.kind, report.key, report.name, report.season) == (
            "roster",
            roster,
            "Fit roster",
            "2025-26",
        )
        assert set(report.members.index) == {TATUM, BROWN, PRITCHARD, WHITE}
        assert report.absent == ("Alaa Abdelnaby",) and report.unprofiled == ()
        lines = scratch_lab.read("player_seasons", {"season": "2025-26", "season_type": "regular"})
        minutes = lines.set_index("player_id")["minutes"]
        for player in report.members.index:
            assert report.members.at[player, "minutes"] == minutes[player]
        assert set(report.members["team"]) == {"BOS"}
        assert report.members["in_rotation"].all()

    def test_the_profile_is_of_these_four_and_placed_among_the_league(
        self, scratch_lab: Lab, roster: int
    ) -> None:
        report = scratch_lab.fit.roster(roster)
        profile = report.profile
        members = report.members
        impact = (members["impact"] * members["minutes"]).sum() / members["minutes"].sum()
        assert profile["impact_sum"] == pytest.approx(5 * impact)
        teams = scratch_lab.read("team_seasons", {"season": "2025-26"})["minutes"].mean()
        assert profile["minutes_covered"] == pytest.approx(members["minutes"].sum() / (5 * teams))
        assert 0 < profile["minutes_covered"] < 1
        assert (
            report.placed["teams"].max()
            == scratch_lab.read("team_fit_profiles", {"season": "2025-26"}).shape[0]
        )
        assert (
            "Jayson Tatum"
            in report.coverage.set_index("archetype").at["primary_creator", "filled_by"]
        )
        assert profile["primary_creators"] >= 1 and np.isnan(profile["bench_impact"])

    def test_a_roster_with_nobody_who_played_is_empty(self, scratch_lab: Lab) -> None:
        roster = scratch_lab.builder.create("Retired")
        scratch_lab.builder.add_player(roster, ABDELNABY)
        report = scratch_lab.fit.roster(roster)
        assert report.is_empty and report.absent == ("Alaa Abdelnaby",)


class TestChampions:
    def test_each_champion_placed_among_its_own_season(self, value_lab: Lab) -> None:
        champions = value_lab.fit.champions()
        assert tuple(champions.columns) == CHAMPIONS_COLUMNS
        assert champions["key"].tolist() == list(MEASURE_KEYS)
        teams = value_lab.read("team_seasons")
        crowned = int(teams["won_championship"].fillna(False).astype(bool).sum())
        assert crowned > 0 and (champions["champions"] == crowned).all()
        assert champions["median_percentile"].between(0, 100).all()
        assert (champions["top_third"] + champions["bottom_third"] <= crowned).all()
        # Worked by hand for one measure: each champion's standing among its season's teams.
        fit = value_lab.read("team_fit_profiles").merge(
            teams[["season", "team_id", "won_championship"]]
        )
        standings = []
        for _season, rows in fit.groupby("season"):
            champion = rows[rows["won_championship"].fillna(False).astype(bool)]
            if champion.empty:
                continue
            value = float(champion["impact_sum"].iloc[0])
            below = (rows["impact_sum"] < value).sum()
            equal = (rows["impact_sum"] == value).sum()
            standings.append(100 * (below + 0.5 * equal) / len(rows))
        expected = float(np.median(standings))
        assert champions.set_index("key").at["impact_sum", "median_percentile"] == pytest.approx(
            expected
        )

    def test_on_the_fixture_store(self, lab: Lab) -> None:
        champions = lab.fit.champions()
        assert champions["champions"].max() <= 1
