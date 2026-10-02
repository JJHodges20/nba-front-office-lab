"""Pooling earlier seasons, and the terms an estimate is built from."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.value_model import ValueSpec
from front_office.modeling.value.design import (
    LEVEL_DESCRIPTIONS,
    LEVEL_KEYS,
    LEVEL_LABELS,
    SHARE_TOLERANCE,
    TERM_KEYS,
    is_complete,
    player_terms,
    team_design,
)
from front_office.modeling.value.features import FEATURE_KEYS, season_features, stints
from front_office.modeling.value.pooling import POOLED_COLUMNS, entering, reliability
from tests.league import SyntheticLeague
from tests.value_reference import entering as entering_by_hand
from tests.value_reference import team_terms


@pytest.fixture(scope="module")
def played(exact_tables) -> pd.DataFrame:
    return stints(
        exact_tables["player_seasons"],
        exact_tables["player_game_logs"],
        exact_tables["team_seasons"],
    )


@pytest.fixture(scope="module")
def features(exact_tables, played) -> pd.DataFrame:
    return season_features(exact_tables["player_seasons"], exact_tables["team_seasons"], played)


@pytest.fixture(scope="module")
def pooled(features, spec) -> pd.DataFrame:
    return entering(features, spec, FEATURE_KEYS)


def seasons_of(*rows: tuple[int, int, float, float, float]) -> pd.DataFrame:
    """Hand-made seasons: (player, start, minutes with something counted, value, age)."""
    return pd.DataFrame(
        [
            {
                "player_id": player,
                "start": start,
                "evidence_minutes": minutes,
                "x": value,
                "mpg_centred": value / 2,
                "age": age,
            }
            for player, start, minutes, value, age in rows
        ]
    )


class TestReliability:
    def test_half_at_the_ballast_and_never_quite_one(self) -> None:
        spec = ValueSpec(ballast_minutes=750)
        found = reliability(pd.Series([0.0, 750.0, 2250.0, 1e9]), spec)
        assert found.tolist()[:3] == [0.0, 0.5, 0.75]
        assert 0.999 < found.iloc[3] < 1

    def test_a_heavier_ballast_trusts_the_same_minutes_less(self) -> None:
        minutes = pd.Series([1000.0])
        light = reliability(minutes, ValueSpec(ballast_minutes=500))[0]
        heavy = reliability(minutes, ValueSpec(ballast_minutes=1500))[0]
        assert heavy < light


class TestEntering:
    def test_seasons_are_averaged_by_minutes_discounted_by_age_of_the_season(self) -> None:
        spec = ValueSpec(season_weights=(1.0, 0.5, 0.25), ballast_minutes=750)
        found = entering(
            seasons_of(
                (7, 2003, 1000, 4.0, 27), (7, 2002, 2000, 1.0, 26), (7, 2001, 800, -2.0, 25)
            ),
            spec,
            ["x"],
        ).set_index("target")
        row = found.loc[2004]
        weight = 1000 + 0.5 * 2000 + 0.25 * 800
        assert row["weight"] == weight == 2200
        assert row["x"] == pytest.approx((1000 * 4 + 1000 * 1 + 200 * -2) / 2200)
        assert row["mpg_centred"] == pytest.approx((1000 * 2 + 1000 * 0.5 + 200 * -1) / 2200)
        assert row["reliability"] == pytest.approx(2200 / 2950)
        assert (row["seasons"], row["age"]) == (3, 28)
        assert tuple(found.columns) == ("player_id", "x", *POOLED_COLUMNS)

    def test_a_season_reaches_only_as_far_forward_as_there_are_weights(self) -> None:
        spec = ValueSpec(season_weights=(1.0, 0.5))
        found = entering(seasons_of((7, 2003, 1000, 4.0, 27)), spec, ["x"])
        assert found["target"].tolist() == [2004, 2005]
        assert found["weight"].tolist() == [1000, 500]
        # The same season, older: the same value, trusted less, the player a year on.
        assert found["x"].tolist() == [4.0, 4.0]
        assert found["age"].tolist() == [28, 29]

    def test_a_missed_season_leaves_the_older_ones_at_their_own_weights(self) -> None:
        spec = ValueSpec(season_weights=(1.0, 0.5, 0.25))
        found = entering(
            seasons_of((7, 2001, 2000, 1.0, 25), (7, 2003, 1000, 4.0, 27)), spec, ["x"]
        ).set_index("target")
        # Entering 2003 only 2001 is behind the player, two seasons back.
        assert (found.loc[2003, "weight"], found.loc[2003, "seasons"]) == (1000, 1)
        assert found.loc[2003, "age"] == 27
        assert found.loc[2004, "weight"] == 1000 + 0.25 * 2000
        assert found.loc[2004, "x"] == pytest.approx((1000 * 4 + 500 * 1) / 1500)

    def test_age_comes_from_the_newest_season_whatever_order_the_rows_are_in(self) -> None:
        rows = seasons_of((7, 2002, 2000, 1.0, 30), (7, 2003, 1000, 4.0, 26))
        for frame in (rows, rows.iloc[::-1]):
            found = entering(frame, ValueSpec(), ["x"]).set_index("target")
            assert found.loc[2004, "age"] == 27

    def test_a_season_with_nothing_counted_is_no_evidence(self) -> None:
        found = entering(
            seasons_of((7, 2003, 0.0, 9.0, 27), (8, 2003, 500, 2.0, 22)), ValueSpec(), ["x"]
        )
        assert set(found["player_id"]) == {8}

    def test_players_are_pooled_apart(self) -> None:
        found = entering(
            seasons_of((7, 2003, 1000, 4.0, 27), (8, 2003, 500, -2.0, 22)), ValueSpec(), ["x"]
        )
        first = found[found["target"] == 2004].set_index("player_id")
        assert first["x"].to_dict() == {7: 4.0, 8: -2.0}

    def test_the_league_pools_as_the_definitions_say(
        self, pooled: pd.DataFrame, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        by_key = pooled.set_index(["target", "player_id"])
        for year in exact_league.years[1:]:
            expected = entering_by_hand(exact_league, year, spec)
            assert set(by_key.loc[year].index) == set(expected)
            for player, known in expected.items():
                row = by_key.loc[(year, player)]
                for name, value in known.features.items():
                    assert row[name] == pytest.approx(value, abs=1e-9), (year, player, name)
                assert row["reliability"] == pytest.approx(known.reliability(spec))
                assert row["mpg_centred"] == pytest.approx(known.mpg_centred, abs=1e-9)
                assert (row["age"], row["seasons"]) == (known.age, known.seasons)


class TestPlayerTerms:
    def known(self, **values: object) -> pd.DataFrame:
        row = {"x": 2.0, "mpg_centred": -6.0, "reliability": 0.8, "age": 31.0, **values}
        return pd.DataFrame([row])

    def test_features_are_trusted_and_the_rest_is_assumed(self) -> None:
        spec = ValueSpec(age_centre=27)
        terms = player_terms(self.known(), spec, ["x"]).iloc[0]
        assert terms["x"] == pytest.approx(0.8 * 2.0)
        assert terms["prior_level"] == pytest.approx(0.2)
        assert terms["prior_minutes"] == pytest.approx(0.2 * -6.0)
        assert (terms["age"], terms["new_player"]) == (4.0, 0.0)
        assert list(terms.index) == ["x", *LEVEL_KEYS]

    def test_a_player_never_seen_is_a_new_player_and_nothing_else(self) -> None:
        unknown = self.known(x=None, mpg_centred=None, reliability=None, age=None)
        terms = player_terms(unknown, ValueSpec(), ["x"]).iloc[0]
        assert terms["new_player"] == 1.0
        assert (terms.drop("new_player") == 0).all()

    def test_full_reliability_leaves_nothing_assumed(self) -> None:
        terms = player_terms(self.known(reliability=1.0), ValueSpec(), ["x"]).iloc[0]
        assert (terms["prior_level"], terms["prior_minutes"]) == (0.0, 0.0)
        assert terms["x"] == 2.0

    def test_no_reliability_is_all_assumption_but_still_a_known_player(self) -> None:
        terms = player_terms(self.known(reliability=0.0), ValueSpec(), ["x"]).iloc[0]
        assert (terms["x"], terms["prior_level"], terms["prior_minutes"]) == (0.0, 1.0, -6.0)
        assert terms["new_player"] == 0.0

    def test_an_unknown_age_is_taken_as_the_centre(self) -> None:
        terms = player_terms(self.known(age=None), ValueSpec(), ["x"]).iloc[0]
        assert terms["age"] == 0.0

    def test_levels_can_be_left_out(self) -> None:
        terms = player_terms(self.known(), ValueSpec(), ["x"], ["new_player"])
        assert list(terms.columns) == ["x", "new_player"]

    def test_every_level_is_named_and_explained(self) -> None:
        assert set(LEVEL_LABELS) == set(LEVEL_DESCRIPTIONS) == set(LEVEL_KEYS)
        assert TERM_KEYS == (*FEATURE_KEYS, *LEVEL_KEYS)


class TestTeamDesign:
    def test_each_teams_row_is_its_players_terms_summed_by_share(
        self, played, pooled, exact_league: SyntheticLeague, spec: ValueSpec
    ) -> None:
        design = team_design(played, pooled, spec)
        assert list(design.columns) == [*TERM_KEYS, "share"]
        for year in (exact_league.years[1], exact_league.years[5]):
            expected = team_terms(exact_league, year, spec)
            for team, row in expected.items():
                found = design.loc[(f"{year}-{(year + 1) % 100:02d}", team)]
                for name, value in row.items():
                    assert found[name] == pytest.approx(value, abs=1e-9), (year, team, name)

    def test_the_first_season_is_all_new_players(self, played, pooled, spec) -> None:
        first = team_design(played, pooled, spec).xs("2000-01", level="season")
        assert np.allclose(first["new_player"], first["share"])
        assert (first[list(FEATURE_KEYS)] == 0).all().all()

    def test_a_team_is_complete_when_its_shares_reach_five(self, played, pooled, spec) -> None:
        design = team_design(played, pooled, spec)
        assert is_complete(design).all()
        short = design.assign(share=5 - SHARE_TOLERANCE - 0.01)
        assert not is_complete(short).any()
        assert is_complete(design.assign(share=5 + SHARE_TOLERANCE - 0.001)).all()

    def test_a_stint_without_a_share_adds_nothing(self, played, pooled, spec) -> None:
        holed = played.copy()
        holed.loc[holed["team_id"] == 101, "share"] = np.nan
        design = team_design(holed, pooled, spec)
        assert (design.xs(101, level="team_id") == 0).all().all()
        assert not is_complete(design).xs(101, level="team_id").any()
