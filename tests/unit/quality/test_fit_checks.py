"""Checks on the team fit profiles: each passes on a profiled league and fails when broken."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.config import load_archetypes
from front_office.domain.fit import ROTATION_SIZE
from front_office.domain.tables.fit import TEAM_FIT_PROFILES
from front_office.domain.value_model import ValueSpec
from front_office.pipelines.check import CHECKED_TABLES
from front_office.quality import Severity, all_checks, run_checks
from front_office.quality.checks import MINUTES_COVERED_TOLERANCE, USAGE_TOLERANCE
from tests.conftest import REPO_ROOT
from tests.synthetic_lab import league_frames
from tests.value_reference import planted_league, planted_model

SPEC = ValueSpec(first_test_season="2004-05", resamples=50)
USAGE = "team_fit_profiles.usage_adds_up"
MINUTES = "team_fit_profiles.minutes_cover_the_season"


@pytest.fixture(scope="module")
def profiled() -> dict[str, pd.DataFrame]:
    roles = load_archetypes(REPO_ROOT / "configs")
    frames = league_frames(planted_league(SPEC, seasons=6), planted_model(SPEC), roles)
    # The invented league's usage rates are made up; set every team's sum to the real
    # thing so that the check has something true to hold.
    frames["team_fit_profiles"]["usage_sum"] = 0.97
    return frames


@pytest.fixture
def tables(profiled: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {name: frame.copy() for name, frame in profiled.items()}


def results(tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    return {result.check: result for result in run_checks(tables, all_checks(CHECKED_TABLES))}


def test_a_profiled_league_passes_and_both_checks_look_at_every_team(tables) -> None:
    found = results(tables)
    teams = len(tables["team_seasons"])
    assert (found[USAGE].passed, found[USAGE].examined) == (True, teams)
    assert (found[MINUTES].passed, found[MINUTES].examined) == (True, teams)
    for name in (USAGE, MINUTES):
        assert found[name].severity is Severity.WARNING
        assert found[name].description.endswith(".")


def test_without_profiles_there_is_nothing_to_check(tables) -> None:
    tables["team_fit_profiles"] = TEAM_FIT_PROFILES.empty_frame()
    found = results(tables)
    assert found[USAGE].passed and found[USAGE].examined == 0
    assert found[MINUTES].passed and found[MINUTES].examined == 0


class TestUsage:
    def test_a_sum_far_from_five_players_worth_is_caught(self, tables) -> None:
        fit = tables["team_fit_profiles"]
        fit.loc[fit.index[3], "usage_sum"] = 1 + USAGE_TOLERANCE + 0.01
        fit.loc[fit.index[5], "usage_sum"] = 1 - USAGE_TOLERANCE - 0.01
        result = results(tables)[USAGE]
        assert result.failures == 2 and "usage_sum=" in result.examples[0]

    def test_a_partial_roster_is_not_asked_to_add_up(self, tables) -> None:
        fit = tables["team_fit_profiles"]
        fit.loc[fit.index[0], ["usage_sum", "minutes_covered"]] = [0.4, 0.3]
        result = results(tables)[USAGE]
        assert result.passed and result.examined == len(fit) - 1

    def test_a_sum_that_is_missing_is_not_examined(self, tables) -> None:
        fit = tables["team_fit_profiles"]
        fit.loc[fit.index[0], "usage_sum"] = float("nan")
        assert results(tables)[USAGE].examined == len(fit) - 1


class TestMinutes:
    def test_a_team_short_of_its_minutes_is_caught(self, tables) -> None:
        fit = tables["team_fit_profiles"]
        fit.loc[fit.index[2], "minutes_covered"] = 1 - MINUTES_COVERED_TOLERANCE - 0.05
        result = results(tables)[MINUTES]
        assert result.failures == 1 and "minutes_covered=" in result.examples[0]

    def test_a_team_known_only_through_a_few_players_is_not_judged(self, tables) -> None:
        fit = tables["team_fit_profiles"]
        fit.loc[fit.index[2], ["players", "minutes_covered"]] = [ROTATION_SIZE - 1, 0.1]
        result = results(tables)[MINUTES]
        assert result.passed and result.examined == len(fit) - 1

    def test_an_unfinished_season_is_not_judged(self, tables) -> None:
        teams = tables["team_seasons"]
        last = teams["season"].max()
        teams.loc[teams["season"] == last, "won_championship"] = None
        fit = tables["team_fit_profiles"]
        fit.loc[fit["season"] == last, "minutes_covered"] = 0.5
        result = results(tables)[MINUTES]
        assert result.passed
        assert result.examined == len(fit[fit["season"] != last])
