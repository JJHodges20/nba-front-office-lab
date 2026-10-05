"""The simulator service: subjects, changes, seasons drawn before and after, and saving.

``played`` is the invented league with its playoffs, a fitted value model and the
simulator's parameters measured on it; ``lab`` and ``scratch_lab`` the fixture store with
the files the lab ships (and, for the scratch copy, invented contracts).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from front_office.config import load_settings, postseason_model_path, simulator_model_path
from front_office.domain.scenario import Adjustment, Scenario, SubjectKind
from front_office.domain.stages import BRACKET_STAGE_KEYS
from front_office.modeling.postseason import probability_key
from front_office.modeling.simulator import ROSTER_COLUMNS
from front_office.services import Lab, SimulatorError
from front_office.services.simulator import (
    ADDED,
    COMPARISON_COLUMNS,
    FIT_COMMAND,
    KEPT,
    LEAGUE_COLUMNS,
    NO_PROJECTION,
    PLAYER_COLUMNS,
    POOL_COLUMNS,
    PROFILE_COLUMNS,
    REMOVED,
    TEAM_COLUMNS,
)
from tests.unit.services.conftest import ABDELNABY, BROWN, BRUNSON, PRITCHARD, TATUM, WHITE

TEAM = 101
TITLE = probability_key("won_championship")
QUICK = 1000


@pytest.fixture(scope="module")
def played(simulator_home: Path) -> Iterator[Lab]:
    with Lab(load_settings(simulator_home)) as opened:
        yield opened


def scenario(**changes: object) -> Scenario:
    return Scenario(subject=SubjectKind.TEAM, key=TEAM, simulations=QUICK, **changes)  # type: ignore[arg-type]


class TestStatus:
    def test_ready_on_the_invented_league(self, played: Lab) -> None:
        status = played.simulator.status()
        assert status.is_available and status.is_fitted and status.is_current
        assert status.reason is None and status.revision == 1
        assert (status.value_model_version, status.applied_value_version) == ("r1", "r1")
        assert status.postseason_revision == 1
        assert (status.upcoming, status.stats_season) == ("2014-15", "2013-14")
        assert not status.has_contracts and status.fitted_at is not None
        assert played.simulator.model().revision == 1

    def test_ready_on_the_fixture_store_with_the_files_the_lab_ships(self, lab: Lab) -> None:
        status = lab.simulator.status()
        assert status.is_available and status.is_current
        assert (status.upcoming, status.stats_season) == ("2026-27", "2025-26")

    def test_without_parameters_or_a_postseason_model_it_says_what_to_run(
        self, simulator_home: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "bare"
        shutil.copytree(simulator_home, bare)
        simulator_model_path(bare / "configs").unlink()
        with Lab(load_settings(bare)) as opened:
            status = opened.simulator.status()
            assert not status.is_fitted and not status.is_available
            assert FIT_COMMAND in status.reason
            with pytest.raises(SimulatorError, match="fol simulate fit --write"):
                opened.simulator.run(scenario())
            assert opened.simulator.league().empty
        alone = tmp_path / "alone"
        shutil.copytree(simulator_home, alone)
        postseason_model_path(alone / "configs").unlink()
        with Lab(load_settings(alone)) as opened:
            status = opened.simulator.status()
            assert status.is_fitted and not status.is_available
            assert "fol playoffs fit --write" in status.reason


class TestTheSubjects:
    def test_every_team_with_a_projected_player(self, played: Lab) -> None:
        teams = played.simulator.teams()
        assert tuple(teams.columns) == TEAM_COLUMNS and len(teams) == 30
        assert teams.index.name == "team_id" and teams["full_name"].is_monotonic_increasing
        pool = played.simulator.pool()
        assert teams["players"].sum() == pool["team_id"].notna().sum() < len(pool)
        assert teams.at[TEAM, "abbreviation"] == "T101"

    def test_the_pool_is_everyone_projected(self, played: Lab) -> None:
        pool = played.simulator.pool()
        assert tuple(pool.columns) == POOL_COLUMNS and pool.index.name == "player_id"
        assert len(pool) == len(played.value.projections())
        first = pool.iloc[0]
        assert first["label"].startswith(first["player_name"]) and " · " in first["label"]

    def test_a_teams_roster_as_it_stands(self, played: Lab) -> None:
        players = played.simulator.roster_players(scenario())
        assert set(PLAYER_COLUMNS) <= set(players.columns)
        assert set(ROSTER_COLUMNS) <= set(players.columns)
        assert (players["status"] == KEPT).all() and (players["team"] == "T101").all()
        assert players["projected_share"].is_monotonic_decreasing
        assert players["projected_impact"].notna().all() and (players["note"] == "").all()
        assert players[["games_missed", "development", "share"]].isna().all().all()
        assert players["salary"].isna().all() and players["salary_source"].isna().all()
        assert len(players) == played.simulator.teams().at[TEAM, "players"]

    def test_changes_add_remove_and_adjust(self, played: Lab) -> None:
        base = played.simulator.roster_players(scenario())
        pool = played.simulator.pool()
        gone = int(base.index[0])
        newcomer = int(pool.index[pool["team_id"] == 102][0])
        touched = int(base.index[1])
        changed = played.simulator.roster_players(
            scenario(
                removed=(gone,),
                added=(newcomer,),
                adjustments={touched: Adjustment(games_missed=10, development=1.5, share=0.4)},
            )
        )
        assert set(changed.index) == set(base.index) | {newcomer}
        assert changed.at[gone, "status"] == REMOVED and changed.index[-1] == gone
        assert changed.at[newcomer, "status"] == ADDED and changed.at[newcomer, "team"] == "T102"
        assert (
            changed.at[touched, "games_missed"] == 10 and changed.at[touched, "development"] == 1.5
        )
        assert changed.at[touched, "share"] == 0.4
        assert (changed.drop(index=[gone, newcomer, touched])["status"] == KEPT).all()

    def test_a_built_roster_with_what_it_assumes(self, scratch_lab: Lab) -> None:
        roster = scratch_lab.builder.create("Scenario roster")
        for player in (TATUM, BROWN, PRITCHARD):
            scratch_lab.builder.add_player(roster, player)
        scratch_lab.builder.add_player(roster, WHITE, assumed_salary=28_000_000)
        scratch_lab.builder.add_player(roster, ABDELNABY)
        players = scratch_lab.simulator.roster_players(
            Scenario(subject=SubjectKind.ROSTER, key=roster, simulations=QUICK)
        )
        assert set(players.index) == {TATUM, BROWN, PRITCHARD, WHITE, ABDELNABY}
        assert players.at[TATUM, "salary"] == 40_000_000
        assert players.at[TATUM, "salary_source"] == "contract"
        assert (
            players.at[WHITE, "salary"] == 28_000_000
            and players.at[WHITE, "salary_source"] == "assumed"
        )
        assert players.at[ABDELNABY, "note"] == NO_PROJECTION
        assert pd.isna(players.at[ABDELNABY, "projected_impact"])
        assert players.at[ABDELNABY, "player_name"] == "Alaa Abdelnaby"
        assert players.index[-1] == ABDELNABY  # no share: sorted after everyone projected

    def test_a_default_scenario_draws_what_the_specification_says(self, played: Lab) -> None:
        default = played.simulator.default_scenario(SubjectKind.TEAM, TEAM)
        assert default.simulations == played.simulator.model().spec.simulations == 2000
        assert not default.is_changed


@pytest.fixture(scope="module")
def report(played: Lab):  # type: ignore[no-untyped-def]
    return played.simulator.run(scenario())


class TestRunning:
    def test_unchanged_is_the_same_before_and_after(self, report, played: Lab) -> None:  # type: ignore[no-untyped-def]
        assert not report.is_changed and report.name == "City 101 Team 101"
        assert (report.season, report.stats_season) == ("2014-15", "2013-14")
        before, after = report.before, report.after
        assert (before.rating, before.wins, before.seasons) == (after.rating, after.wins, QUICK)
        pd.testing.assert_frame_equal(before.stages, after.stages)
        assert (report.comparison["change"].fillna(0) == 0).all()
        assert tuple(report.comparison.columns) == COMPARISON_COLUMNS
        assert report.comparison["key"].tolist()[:4] == ["payroll", "rating", "wins", "top_players"]
        assert report.comparison["key"].tolist()[4:] == [
            probability_key(k) for k in BRACKET_STAGE_KEYS
        ]
        assert before.payroll is None and before.unpriced == before.players
        assert 0 < before.wins < 82 and before.wins_low < before.wins_median < before.wins_high
        assert before.rating_low < before.rating < before.rating_high
        assert before.stages["probability"].is_monotonic_decreasing
        assert (before.stages["low"] <= before.stages["probability"]).all()
        assert before.wins_distribution["share"].sum() == pytest.approx(1.0)
        assert tuple(report.profile.columns) == PROFILE_COLUMNS and not report.profile.empty
        assert report.profile["before"].equals(report.profile["after"])
        assert (report.players["status"] == KEPT).all()

    def test_the_mean_season_is_near_the_sum_of_the_parts(self, report) -> None:  # type: ignore[no-untyped-def]
        # Typical misses by reliability shift the mean a little; the spread does not.
        assert abs(report.before.rating - report.before.expected_rating) < 3.0

    def test_removing_the_best_player_costs_wins_and_chances(self, played: Lab, report) -> None:  # type: ignore[no-untyped-def]
        players = report.players
        worth = (players["projected_impact"] + 2.0) * players["projected_share"]
        best = int(worth.idxmax())
        changed = played.simulator.run(scenario(removed=(best,)))
        assert changed.is_changed
        assert changed.after.rating < changed.before.rating
        assert changed.after.wins < changed.before.wins
        assert changed.after.chance("won_championship") < changed.before.chance("won_championship")
        assert changed.after.players == changed.before.players - 1
        assert changed.players.at[best, "status"] == REMOVED and changed.players.index[-1] == best
        rows = changed.comparison.set_index("key")
        assert rows.at["wins", "change"] < 0 and rows.at["rating", "change"] < 0
        assert changed.before.rating == report.before.rating  # the same seasons before

    def test_adding_a_strong_player_helps(self, played: Lab, report) -> None:  # type: ignore[no-untyped-def]
        pool = played.simulator.pool()
        others = pool[(pool["team_id"] != TEAM) & (pool["projected_share"] > 0.3)]
        strongest = int(others["projected_impact"].idxmax())
        changed = played.simulator.run(scenario(added=(strongest,)))
        assert changed.after.rating > changed.before.rating
        assert changed.after.shares > changed.before.shares
        assert changed.players.at[strongest, "status"] == ADDED

    def test_the_presets_move_the_season_as_they_say(self, played: Lab) -> None:
        healthy = played.simulator.run(scenario(availability="healthy"))
        hurt = played.simulator.run(scenario(availability="high_injury"))
        up = played.simulator.run(scenario(development="optimistic"))
        down = played.simulator.run(scenario(development="regression"))
        assert healthy.after.shares > healthy.before.shares > hurt.after.shares
        assert up.after.rating > up.before.rating > down.after.rating
        assert up.after.wins > down.after.wins

    def test_assumptions_for_one_player(self, played: Lab, report) -> None:  # type: ignore[no-untyped-def]
        player = int(report.players.index[0])
        share = float(report.players.at[player, "projected_share"])
        gone = played.simulator.run(scenario(adjustments={player: Adjustment(games_missed=82)}))
        # A projected share already allows for the games a player typically misses, so
        # sitting the player out for the season costs the roster about that share.
        assert gone.after.shares == pytest.approx(gone.before.shares - share, abs=0.05)
        assert gone.players.at[player, "status"] == KEPT
        better = played.simulator.run(scenario(adjustments={player: Adjustment(development=5.0)}))
        assert better.after.rating > better.before.rating
        fixed = played.simulator.run(scenario(adjustments={player: Adjustment(share=0.0)}))
        assert fixed.after.rating < fixed.before.rating

    def test_the_seasons_are_reproducible(self, played: Lab, report) -> None:  # type: ignore[no-untyped-def]
        again = played.simulator.run(scenario())
        assert again.after.rating == report.after.rating and again.after.wins == report.after.wins
        pd.testing.assert_frame_equal(again.after.stages, report.after.stages)
        other = played.simulator.run(scenario(seed=1))
        assert other.after.rating != report.after.rating

    def test_the_league_draws_every_team(self, played: Lab) -> None:
        league = played.simulator.league(simulations=500)
        assert tuple(league.columns) == LEAGUE_COLUMNS and len(league) == 30
        assert league.index.name == "team_id" and league["rating"].is_monotonic_decreasing
        assert league["wins"].between(0, 82).all()
        assert (league["wins_low"] <= league["wins"]).all() and (
            league["wins"] <= league["wins_high"]
        ).all()
        assert league[TITLE].between(0, 1).all()
        assert league["players"].equals(played.simulator.teams()["players"].reindex(league.index))
        assert (league["projected"] == league["players"]).all()


class TestOnTheFixtureStore:
    def test_a_real_team_with_the_files_the_lab_ships(self, lab: Lab) -> None:
        teams = lab.simulator.teams()
        assert 1610612738 in teams.index and 1610612752 in teams.index
        report = lab.simulator.run(
            Scenario(subject=SubjectKind.TEAM, key=1610612738, simulations=QUICK)
        )
        assert report.name == "Boston Celtics" and report.season == "2026-27"
        assert report.before.projected >= 10 and report.before.payroll is None
        assert 20 < report.before.wins < 70

    def test_a_built_roster_is_priced_and_saved(self, scratch_lab: Lab) -> None:
        roster = scratch_lab.builder.create("Before")
        for player in (TATUM, BROWN, PRITCHARD):
            scratch_lab.builder.add_player(roster, player)
        scratch_lab.builder.add_player(roster, WHITE, assumed_salary=28_000_000)
        asked = Scenario(
            subject=SubjectKind.ROSTER,
            key=roster,
            removed=(PRITCHARD,),
            added=(BRUNSON,),
            adjustments={BRUNSON: Adjustment(salary=50_000_000)},
            simulations=QUICK,
        )
        report = scratch_lab.simulator.run(asked)
        assert report.name == "Before"
        assert report.before.payroll == 40_000_000 + 30_000_000 + 7_000_000 + 28_000_000
        assert report.after.payroll == 40_000_000 + 30_000_000 + 28_000_000 + 50_000_000
        assert report.before.priced == 4 and report.after.unpriced == 0
        rows = report.comparison.set_index("key")
        assert rows.at["payroll", "change"] == 50_000_000 - 7_000_000
        saved = scratch_lab.simulator.save(asked, "After")
        summary = scratch_lab.builder.summary(saved)
        assert set(summary.players.index) == {TATUM, BROWN, WHITE, BRUNSON}
        assert summary.players.at[BRUNSON, "salary"] == 50_000_000
        assert summary.players.at[BRUNSON, "salary_source"] == "assumed"
        assert summary.players.at[WHITE, "salary"] == 28_000_000
        assert summary.players.at[TATUM, "salary_source"] == "contract"
        assert (summary.players["slot"] != "BENCH").all()  # four players, five starting slots
        assert summary.roster["stats_season"] == "2025-26"
        assert summary.roster["payroll_season"] == "2026-27"

    def test_a_player_without_a_projection_is_a_replacement_player(self, scratch_lab: Lab) -> None:
        roster = scratch_lab.builder.create("Thin")
        scratch_lab.builder.add_player(roster, TATUM)
        scratch_lab.builder.add_player(roster, ABDELNABY)
        report = scratch_lab.simulator.run(
            Scenario(subject=SubjectKind.ROSTER, key=roster, simulations=QUICK)
        )
        assert report.before.players == 2 and report.before.projected == 1
        assert report.before.unprojected == ("Alaa Abdelnaby",)
        assert np.isfinite(report.before.rating)
