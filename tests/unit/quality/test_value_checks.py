"""Checks on the modeled player values: each passes on a scored league and fails when broken."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.domain.tables.value import PLAYER_VALUE_SCORES
from front_office.domain.value_model import ValueSpec
from front_office.pipelines.check import CHECKED_TABLES
from front_office.quality import Severity, all_checks, run_checks
from tests.synthetic_lab import league_frames
from tests.value_reference import planted_league, planted_model

SPEC = ValueSpec(first_test_season="2004-05", resamples=50)
PARTS = "player_value_scores.impact_parts_add_up"
VALUED = "player_value_scores.every_season_is_valued"
CENTRED = "player_value_scores.average_minute_has_no_impact"


@pytest.fixture(scope="module")
def scored() -> dict[str, pd.DataFrame]:
    return league_frames(planted_league(SPEC, seasons=6), planted_model(SPEC))


@pytest.fixture
def tables(scored: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {name: frame.copy() for name, frame in scored.items()}


def results(tables: dict[str, pd.DataFrame]) -> dict[str, object]:
    return {result.check: result for result in run_checks(tables, all_checks(CHECKED_TABLES))}


def test_a_scored_league_passes_and_every_check_looks_at_something(tables) -> None:
    found = results(tables)
    played = len(tables["player_seasons"])
    assert (found[PARTS].passed, found[PARTS].examined) == (True, played)
    assert (found[VALUED].passed, found[VALUED].examined) == (True, played)
    assert (found[CENTRED].passed, found[CENTRED].examined) == (True, 6)
    for name in (PARTS, VALUED, CENTRED):
        assert found[name].severity is Severity.ERROR
        assert found[name].description.endswith(".")


def test_without_a_model_there_is_nothing_to_check(tables) -> None:
    tables["player_value_scores"] = PLAYER_VALUE_SCORES.empty_frame()
    found = results(tables)
    for name in (PARTS, VALUED, CENTRED):
        assert found[name].passed and found[name].examined == 0


def test_the_value_checks_need_the_value_table(tables) -> None:
    league_only = [
        contract for contract in CHECKED_TABLES if contract.name != "player_value_scores"
    ]
    names = {f"{check.table}.{check.name}" for check in all_checks(league_only)}
    assert not {PARTS, VALUED, CENTRED} & names


class TestParts:
    @pytest.mark.parametrize("column", ["impact_from_efficiency", "impact_from_baseline"])
    def test_a_part_that_moved_is_caught(self, tables, column: str) -> None:
        scores = tables["player_value_scores"]
        row = scores.index[scores["impact"].notna()][3]
        scores.loc[row, column] += 0.01
        result = results(tables)[PARTS]
        assert result.failures == 1
        assert "from_parts=" in result.examples[0] and "offense_plus_defense=" in result.examples[0]

    def test_sides_that_do_not_add_up_are_caught(self, tables) -> None:
        scores = tables["player_value_scores"]
        row = scores.index[scores["impact"].notna()][0]
        scores.loc[row, "impact_defense"] -= 0.5
        assert results(tables)[PARTS].failures == 1

    def test_rounding_noise_is_not_a_failure(self, tables) -> None:
        scores = tables["player_value_scores"]
        scores["impact_from_creation"] += 1e-9
        assert results(tables)[PARTS].passed

    def test_projection_only_rows_have_no_parts_to_add(self, tables) -> None:
        scores = tables["player_value_scores"]
        ahead = scores[scores["impact"].isna()]
        assert len(ahead) > 50
        assert results(tables)[PARTS].examined == len(scores) - len(ahead)


class TestEverySeasonValued:
    def test_a_season_without_a_row_is_reported_by_name(self, tables) -> None:
        scores = tables["player_value_scores"]
        played = scores[scores["impact"].notna()]
        tables["player_value_scores"] = scores.drop(index=played.index[:2])
        result = results(tables)[VALUED]
        assert result.failures == 2
        assert "player_name=Player" in result.examples[0]

    def test_a_row_without_an_impact_does_not_count(self, tables) -> None:
        scores = tables["player_value_scores"]
        row = scores.index[scores["impact"].notna()][0]
        scores.loc[row, "impact"] = float("nan")
        assert results(tables)[VALUED].failures == 1

    def test_playoff_lines_are_not_expected_to_be_valued(self, tables) -> None:
        seasons = tables["player_seasons"]
        playoffs = seasons.head(15).assign(season_type="playoffs")
        tables["player_seasons"] = pd.concat([seasons, playoffs], ignore_index=True)
        result = results(tables)[VALUED]
        assert result.passed and result.examined == len(seasons)


class TestCentred:
    def test_a_season_whose_average_minute_is_not_zero_is_caught(self, tables) -> None:
        scores = tables["player_value_scores"]
        shifted = scores["season"] == "2003-04"
        scores.loc[shifted, "impact"] += 0.1
        result = results(tables)[CENTRED]
        assert result.failures == 1
        assert "season=2003-04" in result.examples[0]
        assert "minutes_weighted_impact=0.1" in result.examples[0]

    def test_it_is_the_minutes_weighted_average_that_must_be_zero(self, tables) -> None:
        # Add to one player what is taken from another with the same minutes: the plain
        # average is unchanged, and so is the weighted one. With unequal minutes it moves.
        scores = tables["player_value_scores"]
        minutes = tables["player_seasons"].set_index(["player_id", "season"])["minutes"]
        season = scores[(scores["season"] == "2002-03") & scores["impact"].notna()]
        played = minutes.reindex(pd.MultiIndex.from_frame(season[["player_id", "season"]]))
        heavy, light = played.to_numpy().argmax(), played.to_numpy().argmin()
        scores.loc[season.index[heavy], "impact"] += 1.0
        scores.loc[season.index[light], "impact"] -= 1.0
        assert results(tables)[CENTRED].failures == 1
