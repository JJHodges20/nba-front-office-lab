"""The formulas, checked three ways: by hand, at their edges, and against the league.

The league publishes effective field goal percentage, true shooting percentage and
offensive rating alongside the totals they are computed from. Where our formula applied
to those totals reproduces the league's figure for every team and player in the fixture
data, the formula is right, not merely self-consistent.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from front_office.analytics import formulas as f
from front_office.domain.datasets import NbaStatsDataset
from front_office.domain.seasons import Season, SeasonType

D = NbaStatsDataset
REGULAR = SeasonType.REGULAR
PUBLISHED_TO_THREE_DECIMALS = 0.00051
PUBLISHED_TO_ONE_DECIMAL = 0.051


def source_frame(snapshot) -> pd.DataFrame:
    result_set = snapshot.payload["resultSets"][0]
    return pd.DataFrame(result_set["rowSet"], columns=result_set["headers"])


class TestSafeDivide:
    def test_numbers(self) -> None:
        assert f.safe_divide(1, 4) == 0.25
        assert f.safe_divide(0, 4) == 0.0

    @pytest.mark.parametrize("denominator", [0, 0.0, None, float("nan")])
    def test_a_zero_or_missing_denominator_gives_missing_not_zero_or_infinity(
        self, denominator
    ) -> None:
        assert math.isnan(f.safe_divide(5, denominator))

    def test_a_missing_numerator_gives_missing(self) -> None:
        assert math.isnan(f.safe_divide(None, 4))

    def test_series_keep_their_index(self) -> None:
        made = pd.Series([5, 0, 3], index=[10, 20, 30])
        attempted = pd.Series([10, 0, 4], index=[10, 20, 30])
        result = f.safe_divide(made, attempted)
        assert result.index.tolist() == [10, 20, 30]
        assert result.iloc[0] == 0.5 and result.iloc[2] == 0.75
        assert math.isnan(result.iloc[1])
        assert not np.isinf(result).any()

    def test_nullable_integer_series(self) -> None:
        made = pd.Series([5, None], dtype="Int64")
        attempted = pd.Series([10, 4], dtype="Int64")
        result = f.safe_divide(made, attempted)
        assert str(result.dtype) == "float64"
        assert result.iloc[0] == 0.5 and math.isnan(result.iloc[1])

    def test_series_over_a_number_and_a_number_over_a_series(self) -> None:
        totals = pd.Series([10.0, 20.0])
        assert f.safe_divide(totals, 4).tolist() == [2.5, 5.0]
        assert f.safe_divide(totals, 0).isna().all()
        halves = f.safe_divide(1, pd.Series([2.0, 0.0]))
        assert halves.iloc[0] == 0.5 and math.isnan(halves.iloc[1])


class TestByHand:
    """One worked example per formula: 8-of-16 shooting with two threes, 7-of-8 at the line."""

    FGM, FGA, FG3M, FG3A, FTM, FTA, PTS = 8, 16, 2, 5, 7, 8, 25
    TOV, AST, OREB = 3, 6, 2

    def test_points_follow_from_the_shots(self) -> None:
        assert 2 * self.FGM + self.FG3M + self.FTM == self.PTS

    def test_shooting_percentages(self) -> None:
        assert f.shooting_pct(self.FGM, self.FGA) == 0.5
        assert f.shooting_pct(self.FG3M, self.FG3A) == 0.4
        assert f.shooting_pct(self.FTM, self.FTA) == 0.875

    def test_effective_field_goal(self) -> None:
        # (8 + 0.5 x 2) / 16
        assert f.effective_fg_pct(self.FGM, self.FG3M, self.FGA) == 9 / 16

    def test_scoring_attempts(self) -> None:
        assert f.scoring_attempts(self.FGA, self.FTA) == pytest.approx(16 + 0.44 * 8)

    def test_true_shooting(self) -> None:
        # 25 / (2 x 19.52)
        assert f.true_shooting_pct(self.PTS, self.FGA, self.FTA) == pytest.approx(25 / 39.04)
        assert f.true_shooting_pct(self.PTS, self.FGA, self.FTA) == pytest.approx(0.6404, abs=1e-4)

    def test_attempt_rates(self) -> None:
        assert f.three_point_attempt_rate(self.FG3A, self.FGA) == 5 / 16
        assert f.free_throw_rate(self.FTA, self.FGA) == 0.5

    def test_turnover_percentage(self) -> None:
        # 3 / (19.52 + 3)
        assert f.turnover_pct(self.TOV, self.FGA, self.FTA) == pytest.approx(3 / 22.52)

    def test_assist_to_turnover(self) -> None:
        assert f.assist_to_turnover(self.AST, self.TOV) == 2.0
        assert math.isnan(f.assist_to_turnover(self.AST, 0))

    def test_rates_per_game_minutes_and_possessions(self) -> None:
        assert f.per_game(250, 10) == 25.0
        assert f.per_36(20, 30) == 24.0
        assert f.per_100(20, 60) == pytest.approx(33.3333, abs=1e-4)
        assert f.rating(9714, 8444) == pytest.approx(115.04, abs=0.005)

    def test_estimated_possessions(self) -> None:
        # 85 + 0.44 x 20 - 10 + 14
        assert f.estimated_possessions(85, 20, 10, 14) == pytest.approx(97.8)

    def test_pace(self) -> None:
        assert f.pace(100, 48) == 100.0
        assert f.pace(8444, 3951) == pytest.approx(102.58, abs=0.01)

    def test_rebound_percentage(self) -> None:
        assert f.rebound_pct(10, 30) == 0.25
        assert math.isnan(f.rebound_pct(0, 0))

    def test_share(self) -> None:
        assert f.share(41, 82) == 0.5


class TestEdges:
    def test_a_player_with_no_attempts_has_no_percentage(self) -> None:
        assert math.isnan(f.shooting_pct(0, 0))
        assert math.isnan(f.effective_fg_pct(0, 0, 0))
        assert math.isnan(f.true_shooting_pct(0, 0, 0))
        assert math.isnan(f.turnover_pct(0, 0, 0))
        assert math.isnan(f.per_36(0, 0))

    def test_free_throws_alone_still_give_a_true_shooting_figure(self) -> None:
        assert f.true_shooting_pct(2, 0, 2) == pytest.approx(2 / (2 * 0.88))

    def test_every_formula_is_vectorised(self) -> None:
        frame = pd.DataFrame(
            {"pts": [25, 0], "fgm": [8, 0], "fg3m": [2, 0], "fga": [16, 0], "fta": [8, 0]}
        )
        true_shooting = f.true_shooting_pct(frame["pts"], frame["fga"], frame["fta"])
        effective = f.effective_fg_pct(frame["fgm"], frame["fg3m"], frame["fga"])
        assert true_shooting.iloc[0] == pytest.approx(25 / 39.04)
        assert effective.iloc[0] == 9 / 16
        assert true_shooting.isna().tolist() == [False, True]
        assert effective.isna().tolist() == [False, True]

    def test_inputs_are_not_modified(self) -> None:
        attempts = pd.Series([16, 0], dtype="Int64")
        before = attempts.copy()
        f.shooting_pct(pd.Series([8, 0], dtype="Int64"), attempts)
        pd.testing.assert_series_equal(attempts, before)


class TestAgainstTheLeague:
    """Our arithmetic on the league's totals must reproduce the league's own figures."""

    @pytest.mark.parametrize("season", [1996, 2012, 2025])
    def test_team_shooting_efficiency(self, raw, season: int) -> None:
        base = source_frame(raw(D.TEAM_SEASON_BASE, Season(season), REGULAR)).set_index("TEAM_ID")
        published = source_frame(raw(D.TEAM_SEASON_ADVANCED, Season(season), REGULAR)).set_index(
            "TEAM_ID"
        )
        effective = f.effective_fg_pct(base["FGM"], base["FG3M"], base["FGA"])
        true_shooting = f.true_shooting_pct(base["PTS"], base["FGA"], base["FTA"])
        assert (effective - published["EFG_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS
        assert (true_shooting - published["TS_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS

    @pytest.mark.parametrize("season", [2012, 2025])
    def test_team_offensive_rating(self, raw, season: int) -> None:
        base = source_frame(raw(D.TEAM_SEASON_BASE, Season(season), REGULAR)).set_index("TEAM_ID")
        published = source_frame(raw(D.TEAM_SEASON_ADVANCED, Season(season), REGULAR)).set_index(
            "TEAM_ID"
        )
        ours = f.rating(base["PTS"], published["POSS"])
        assert (ours - published["OFF_RATING"]).abs().max() < PUBLISHED_TO_ONE_DECIMAL

    def test_player_shooting_efficiency(self, raw) -> None:
        base = source_frame(raw(D.PLAYER_SEASON_BASE, Season(2025), REGULAR)).set_index("PLAYER_ID")
        published = source_frame(raw(D.PLAYER_SEASON_ADVANCED, Season(2025), REGULAR)).set_index(
            "PLAYER_ID"
        )
        shooters = base[base["FGA"] > 0]
        assert len(shooters) >= 35
        effective = f.effective_fg_pct(shooters["FGM"], shooters["FG3M"], shooters["FGA"])
        true_shooting = f.true_shooting_pct(shooters["PTS"], shooters["FGA"], shooters["FTA"])
        league = published.loc[shooters.index]
        assert (effective - league["EFG_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS
        assert (true_shooting - league["TS_PCT"]).abs().max() < PUBLISHED_TO_THREE_DECIMALS

    def test_player_assist_to_turnover(self, raw) -> None:
        base = source_frame(raw(D.PLAYER_SEASON_BASE, Season(2025), REGULAR)).set_index("PLAYER_ID")
        published = source_frame(raw(D.PLAYER_SEASON_ADVANCED, Season(2025), REGULAR)).set_index(
            "PLAYER_ID"
        )
        careless = base[base["TOV"] > 0]
        ours = f.assist_to_turnover(careless["AST"], careless["TOV"])
        assert (ours - published.loc[careless.index, "AST_TO"]).abs().max() < 0.0051

    def test_estimated_possessions_are_close_to_counted_ones(self, raw) -> None:
        """The box-score estimate is within a few percent of the league's count: an estimate."""
        base = source_frame(raw(D.TEAM_SEASON_BASE, Season(2025), REGULAR)).set_index("TEAM_ID")
        counted = source_frame(raw(D.TEAM_SEASON_ADVANCED, Season(2025), REGULAR)).set_index(
            "TEAM_ID"
        )["POSS"]
        estimated = f.estimated_possessions(base["FGA"], base["FTA"], base["OREB"], base["TOV"])
        relative_error = ((estimated - counted) / counted).abs()
        assert relative_error.max() < 0.04
        assert relative_error.mean() > 0.005  # and it really is only an estimate
