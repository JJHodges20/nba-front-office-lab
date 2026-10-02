"""Projected minutes, wins per point, and intervals from resampling seasons."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.domain.value_model import ValueSpec
from front_office.modeling.value import availability, wins_per_net_point
from front_office.modeling.value.availability import (
    SHARE_KEYS,
    TERMS,
    NotEnoughHistory,
    fit_availability,
    history,
    project,
    season_shares,
)
from front_office.modeling.value.resampling import interval, rmse_differences, season_draws


def played_of(*rows: tuple[int, int, int, float]) -> pd.DataFrame:
    """Hand-made stints: (player, start, team, share)."""
    return pd.DataFrame(rows, columns=["player_id", "start", "team_id", "share"])


def ages_of(*rows: tuple[int, int, int]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["player_id", "start", "age"]).astype({"age": "float64"})


class TestHistory:
    def test_a_players_share_is_added_up_over_teams(self) -> None:
        shares = season_shares(played_of((7, 2003, 1, 0.3), (7, 2003, 2, 0.2), (8, 2003, 1, 0.5)))
        assert shares.set_index("player_id")["share"].to_dict() == {7: 0.5, 8: 0.5}

    def test_a_share_that_is_not_on_record_counts_as_nothing(self) -> None:
        shares = season_shares(played_of((7, 2003, 1, float("nan")), (7, 2003, 2, 0.2)))
        assert shares["share"].tolist() == [0.2]

    def test_the_three_seasons_before_each_season_entered(self) -> None:
        features = ages_of((7, 2001, 25), (7, 2002, 26), (7, 2003, 27))
        played = played_of((7, 2001, 1, 0.2), (7, 2002, 1, 0.4), (7, 2003, 1, 0.6))
        known = history(features, season_shares(played)).set_index("target")
        assert known.loc[2004, list(SHARE_KEYS)].tolist() == [0.6, 0.4, 0.2]
        assert known.loc[2002, list(SHARE_KEYS)].tolist() == [0.2, 0.0, 0.0]
        assert known.loc[2006, list(SHARE_KEYS)].tolist() == [0.0, 0.0, 0.6]
        assert known.index.tolist() == [2002, 2003, 2004, 2005, 2006]

    def test_age_is_what_the_newest_season_implies(self) -> None:
        features = ages_of((7, 2001, 25), (7, 2003, 27))
        played = played_of((7, 2001, 1, 0.2), (7, 2003, 1, 0.6))
        known = history(features, season_shares(played)).set_index("target")
        assert known.loc[2004, "age"] == 28
        assert known.loc[2003, "age"] == 27  # from 2001, two seasons on
        assert known.loc[2006, "age"] == 30

    def test_a_player_who_never_played_a_minute_has_no_history(self) -> None:
        features = ages_of((7, 2003, 27), (8, 2003, 22))
        known = history(features, season_shares(played_of((7, 2003, 1, 0.4), (8, 2003, 1, 0.0))))
        assert set(known["player_id"]) == {7}


class TestProjection:
    COEFFICIENTS = dict(zip(TERMS, (0.02, 0.7, 0.1, 0.03, -0.01, 0.025), strict=True))

    def known(self, age: float | None, *shares: float) -> pd.DataFrame:
        return pd.DataFrame([{**dict(zip(SHARE_KEYS, shares, strict=True)), "age": age}])

    def test_terms_are_the_shares_and_the_years_past_each_bend(self) -> None:
        found = availability.terms(self.known(33, 0.6, 0.5, 0.4)).iloc[0]
        assert found.tolist() == [1.0, 0.6, 0.5, 0.4, 3.0, 0.0]
        young = availability.terms(self.known(21, 0.3, 0.0, 0.0)).iloc[0]
        assert (young["years_over_30"], young["years_under_25"]) == (0.0, 4.0)
        prime = availability.terms(self.known(27, 0.3, 0.0, 0.0)).iloc[0]
        assert (prime["years_over_30"], prime["years_under_25"]) == (0.0, 0.0)
        assert tuple(found.index) == TERMS

    def test_a_projection_is_the_weighted_sum(self) -> None:
        found = project(self.known(33, 0.6, 0.5, 0.4), self.COEFFICIENTS)[0]
        assert found == pytest.approx(0.02 + 0.42 + 0.05 + 0.012 - 0.03)

    def test_never_below_nothing_or_above_every_minute(self) -> None:
        old = project(self.known(45, 0.0, 0.0, 0.01), self.COEFFICIENTS)[0]
        assert old == 0.0
        heavy = project(self.known(27, 0.9, 0.9, 0.9), {**self.COEFFICIENTS, "share_1": 2.0})[0]
        assert heavy == 1.0

    def test_missing_shares_and_age_are_no_information(self) -> None:
        frame = pd.DataFrame([{"share_1": None, "share_2": None, "share_3": None, "age": None}])
        assert project(frame, self.COEFFICIENTS)[0] == pytest.approx(0.02)


class TestFit:
    def league(self, seasons: int = 9, players: int = 80, noise: float = 0.0) -> tuple:
        """Players whose share each season is a fixed rule of the seasons before."""
        generator = np.random.default_rng(1)
        # Gentle enough that no share is ever pushed to the floor or the ceiling, where
        # the rule would stop being a straight line.
        rule = dict(zip(TERMS, (0.03, 0.6, 0.15, 0.05, -0.004, 0.01), strict=True))
        rows, ages = [], []
        for player in range(players):
            first_age = int(generator.integers(19, 33))
            shares: list[float] = []
            for index in range(seasons):
                age = first_age + index
                if index == 0:
                    share = float(generator.uniform(0.05, 0.7))
                else:
                    earlier = (shares[::-1] + [0.0, 0.0, 0.0])[:3]
                    share = (
                        rule["intercept"]
                        + sum(
                            rule[key] * value
                            for key, value in zip(SHARE_KEYS, earlier, strict=True)
                        )
                        + rule["years_over_30"] * max(age - 30, 0)
                        + rule["years_under_25"] * max(25 - age, 0)
                        + noise * float(generator.normal())
                    )
                    assert noise or 0 < share < 1
                    share = float(np.clip(share, 0.001, 1))
                shares.append(share)
                rows.append((player, 2000 + index, 1, share))
                ages.append((player, 2000 + index, age))
        return ages_of(*ages), played_of(*rows), rule

    def test_a_planted_rule_is_recovered_and_predicts_exactly(self) -> None:
        features, played, rule = self.league()
        spec = ValueSpec(first_test_season="2004-05", resamples=100)
        found = fit_availability(features, played, range(2000, 2009), spec)
        for key, value in rule.items():
            assert found.coefficients[key] == pytest.approx(value, abs=1e-5), key
        assert found.rmse < 1e-6 and found.mae < 1e-6
        assert found.players == 80 * 5
        assert found.baseline_rmse > 0.01
        assert found.difference == pytest.approx(found.rmse - found.baseline_rmse, abs=2e-6)
        assert found.low <= found.difference <= found.high < 0

    def test_only_finished_seasons_are_learned_from_or_tested_on(self) -> None:
        features, played, _ = self.league()
        spec = ValueSpec(first_test_season="2004-05", resamples=50)
        found = fit_availability(features, played, range(2000, 2007), spec)
        assert found.players == 80 * 3

    def test_a_player_who_left_counts_as_no_minutes(self) -> None:
        features, played, _ = self.league(noise=0.02)
        spec = ValueSpec(first_test_season="2004-05", resamples=50)
        before = fit_availability(features, played, range(2000, 2009), spec)
        # Half the league retires after 2005: their later seasons vanish from the tables.
        gone = (played["player_id"] % 2 == 0) & (played["start"] > 2005)
        left = (features["player_id"] % 2 == 0) & (features["start"] > 2005)
        after = fit_availability(features[~left], played[~gone], range(2000, 2009), spec)
        # They are still predicted, as the players they were before they went, and what
        # happened to them is learned from: a regular is no longer sure of his minutes.
        assert after.players == before.players
        regular = pd.DataFrame([{"share_1": 0.5, "share_2": 0.5, "share_3": 0.5, "age": 27.0}])
        kept = project(regular, before.coefficients)[0]
        assert project(regular, after.coefficients)[0] < kept - 0.005
        assert after.baseline_rmse > before.baseline_rmse

    def test_with_no_season_to_test_on_it_says_so(self) -> None:
        features, played, _ = self.league(seasons=3)
        spec = ValueSpec(first_test_season="2010-11", resamples=50)
        with pytest.raises(NotEnoughHistory, match="no season from 2010-11"):
            fit_availability(features, played, range(2000, 2003), spec)


class TestWinsPerNetPoint:
    def teams(self, *rows: tuple[str, float, int, int]) -> pd.DataFrame:
        frame = pd.DataFrame(rows, columns=["season", "net_rating", "wins", "losses"])
        frame["games_played"] = frame["wins"] + frame["losses"]
        return frame

    def test_the_slope_through_an_even_record(self) -> None:
        teams = self.teams(
            ("2003-04", 4.0, 51, 31), ("2003-04", -4.0, 31, 51), ("2003-04", 2.0, 47, 35)
        )
        found = wins_per_net_point(teams, window=0)
        assert found.to_dict() == {"2003-04": pytest.approx((4 * 10 + 4 * 10 + 2 * 6) / 36)}

    def test_a_short_season_is_put_on_the_scale_of_82_games(self) -> None:
        full = self.teams(("2003-04", 4.0, 51, 31), ("2003-04", -4.0, 31, 51))
        short = self.teams(("2003-04", 4.0, 31, 19), ("2003-04", -4.0, 19, 31))
        assert wins_per_net_point(full, window=0)["2003-04"] == pytest.approx(2.5)
        assert wins_per_net_point(short, window=0)["2003-04"] == pytest.approx(82 * 0.12 / 4)

    def test_neighbouring_seasons_are_pooled_inside_the_window(self) -> None:
        teams = self.teams(
            ("2001-02", 4.0, 49, 33), ("2002-03", 4.0, 51, 31), ("2003-04", 4.0, 53, 29),
            ("2006-07", 4.0, 61, 21),
        )  # fmt: skip
        alone = wins_per_net_point(teams, window=0)
        assert alone.round(6).to_dict() == {
            "2001-02": 2.0, "2002-03": 2.5, "2003-04": 3.0, "2006-07": 5.0,
        }  # fmt: skip
        pooled = wins_per_net_point(teams, window=1)
        assert pooled["2002-03"] == pytest.approx(2.5)
        assert pooled["2001-02"] == pytest.approx(2.25)
        assert pooled["2006-07"] == pytest.approx(5.0)  # nothing within a season of it
        assert list(pooled.index) == sorted(pooled.index)

    def test_a_season_with_no_games_has_no_figure(self) -> None:
        teams = self.teams(("2003-04", 4.0, 51, 31), ("2004-05", 0.0, 0, 0))
        assert list(wins_per_net_point(teams, window=2).index) == ["2003-04"]
        nothing = wins_per_net_point(self.teams(("2004-05", 0.0, 0, 0)), window=2)
        assert nothing.empty

    def test_a_league_of_average_teams_has_no_slope(self) -> None:
        teams = self.teams(("2003-04", 0.0, 41, 41), ("2003-04", 0.0, 41, 41))
        assert wins_per_net_point(teams, window=0).empty

    def test_on_the_invented_league_it_finds_the_rule_wins_were_drawn_by(
        self, exact_tables
    ) -> None:
        found = wins_per_net_point(exact_tables["team_seasons"], window=2)
        assert len(found) == 9
        assert found.between(2.3, 2.7).all()  # wins are 41 + 2.5 x net, rounded


class TestResampling:
    def test_draws_are_whole_seasons_and_the_same_every_time(self) -> None:
        spec = ValueSpec(resamples=500, seed=4)
        seasons = np.arange(2000, 2012)
        draws = season_draws(seasons, spec)
        assert draws.shape == (500, 12)
        assert draws.min() == 0 and draws.max() == 11
        assert (season_draws(seasons, spec) == draws).all()
        assert (season_draws(seasons, ValueSpec(resamples=500, seed=5)) != draws).any()

    def test_an_interval_is_the_middle_of_the_draws(self) -> None:
        values = np.arange(1001, dtype="float64")
        assert interval(values, ValueSpec(confidence=0.95)) == pytest.approx((25.0, 975.0))
        assert interval(values, ValueSpec(confidence=0.8)) == pytest.approx((100.0, 900.0))

    def test_two_methods_with_the_same_errors_never_differ(self) -> None:
        errors = np.random.default_rng(0).normal(size=60)
        season_of = np.repeat(np.arange(6), 10)
        found = rmse_differences(errors, errors, season_of, ValueSpec(resamples=200))
        assert found.shape == (200,) and (found == 0).all()

    def test_a_difference_is_the_first_methods_error_less_the_seconds(self) -> None:
        season_of = np.repeat(np.arange(5), 4)
        first, second = np.full(20, 3.0), np.full(20, 1.0)
        found = rmse_differences(first, second, season_of, ValueSpec(resamples=100))
        assert np.allclose(found, 2.0)
        assert np.allclose(
            rmse_differences(second, first, season_of, ValueSpec(resamples=100)), -2.0
        )

    def test_seasons_are_drawn_whole(self) -> None:
        # One season is where the first method fails. A draw holds it some whole number
        # of times, so the difference takes only as many values as that count can.
        season_of = np.repeat(np.arange(4), 5)
        first = np.where(season_of == 0, 4.0, 0.0)
        second = np.zeros(20)
        found = rmse_differences(first, second, season_of, ValueSpec(resamples=400))
        expected = {round(float(np.sqrt(16 * count / 4)), 9) for count in range(5)}
        assert {round(float(value), 9) for value in found} <= expected
        assert len({round(float(value), 9) for value in found}) >= 4

    def test_uneven_seasons_weigh_by_how_many_observations_they_hold(self) -> None:
        season_of = np.array([0, 0, 0, 1])
        first = np.array([1.0, 1.0, 1.0, 5.0])
        found = rmse_differences(first, np.zeros(4), season_of, ValueSpec(resamples=300))
        both = np.sqrt((3 * 1 + 25) / 4)
        assert {round(float(value), 9) for value in found} == {1.0, 5.0, round(float(both), 9)}
