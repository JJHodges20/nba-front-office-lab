from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics.comparison import (
    Qualification,
    comparison,
    percentiles,
    pooled_metrics,
    position_group,
    ranks,
)
from front_office.analytics.players import PLAYER_METRICS, box_metrics, player_season_metrics
from front_office.domain.metrics import MetricCatalog, MetricSpec

CATALOG = MetricCatalog(
    (
        MetricSpec("score", "S", "Score", "Higher is better.", "Test"),
        MetricSpec("errors", "E", "Errors", "Lower is better.", "Test", higher_is_better=False),
        MetricSpec("age", "A", "Age", "Neither is better.", "Test", higher_is_better=None),
    )
)


def frame(**columns: list) -> pd.DataFrame:
    length = len(next(iter(columns.values())))
    return pd.DataFrame(columns, index=pd.Index(range(1, length + 1), name="player_id"))


class TestQualification:
    def test_default_admits_everyone(self) -> None:
        players = frame(games_played=[1, 80], minutes=[3.0, 2800.0])
        assert Qualification().mask(players).all()
        assert Qualification().describe() == "all players"

    def test_both_thresholds_must_be_met(self) -> None:
        players = frame(games_played=[60, 60, 10], minutes=[1500.0, 400.0, 1500.0])
        rule = Qualification(min_games=20, min_minutes=500)
        assert rule.mask(players).tolist() == [True, False, False]
        assert rule.describe() == "players with 20+ games and 500+ minutes"

    def test_thresholds_are_inclusive(self) -> None:
        players = frame(games_played=[20], minutes=[500.0])
        assert Qualification(min_games=20, min_minutes=500).mask(players).all()

    def test_one_threshold(self) -> None:
        assert Qualification(min_minutes=1000).describe() == "players with 1,000+ minutes"
        assert Qualification(min_games=41).describe() == "players with 41+ games"

    @pytest.mark.parametrize("kwargs", [{"min_games": -1}, {"min_minutes": -0.5}])
    def test_negative_thresholds_are_rejected(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            Qualification(**kwargs)


class TestPositionGroup:
    @pytest.mark.parametrize(
        ("position", "group"),
        [("G", "Guard"), ("F", "Forward"), ("C", "Center"), ("G-F", "Guard"), ("F-C", "Forward"),
         ("C-F", "Center"), ("f-g", "Forward")],
    )  # fmt: skip
    def test_grouped_by_the_first_listed_position(self, position: str, group: str) -> None:
        assert position_group(position) == group

    @pytest.mark.parametrize("position", [None, "", float("nan"), "X"])
    def test_unknown_positions_have_no_group(self, position) -> None:
        assert position_group(position) is None


class TestPercentiles:
    def test_the_middle_of_the_group_is_fifty(self) -> None:
        players = frame(score=[10.0, 20.0, 30.0, 40.0, 50.0])
        result = percentiles(players, CATALOG, ["score"])["score"]
        assert result.tolist() == [10.0, 30.0, 50.0, 70.0, 90.0]

    def test_lower_is_better_metrics_are_flipped(self) -> None:
        players = frame(errors=[1.0, 2.0, 3.0, 4.0, 5.0])
        result = percentiles(players, CATALOG, ["errors"])["errors"]
        assert result.tolist() == [90.0, 70.0, 50.0, 30.0, 10.0]

    def test_metrics_with_no_better_direction_rank_by_size(self) -> None:
        players = frame(age=[20.0, 30.0, 40.0])
        result = percentiles(players, CATALOG, ["age"])["age"]
        assert result.is_monotonic_increasing

    def test_ties_share_a_percentile(self) -> None:
        players = frame(score=[10.0, 20.0, 20.0, 30.0])
        result = percentiles(players, CATALOG, ["score"])["score"]
        assert result.tolist() == [12.5, 50.0, 50.0, 87.5]

    def test_percentiles_stay_strictly_between_zero_and_a_hundred(self) -> None:
        players = frame(score=[float(n) for n in range(200)])
        result = percentiles(players, CATALOG, ["score"])["score"]
        assert 0 < result.min() and result.max() < 100
        assert result.mean() == pytest.approx(50.0)

    def test_unqualified_rows_get_no_percentile_and_are_not_peers(self) -> None:
        players = frame(score=[10.0, 20.0, 30.0, 999.0])
        qualified = pd.Series([True, True, True, False], index=players.index)
        result = percentiles(players, CATALOG, ["score"], qualified=qualified)["score"]
        assert result.iloc[:3].tolist() == pytest.approx([100 / 6, 50.0, 500 / 6])
        assert math.isnan(result.iloc[3])

    def test_missing_values_get_no_percentile_and_are_not_peers(self) -> None:
        players = frame(score=[10.0, None, 30.0])
        result = percentiles(players, CATALOG, ["score"])["score"]
        assert result.iloc[0] == 25.0 and result.iloc[2] == 75.0
        assert math.isnan(result.iloc[1])

    def test_groups_are_ranked_separately(self) -> None:
        players = frame(score=[10.0, 20.0, 30.0, 40.0])
        group = pd.Series(["Guard", "Guard", "Center", "Center"], index=players.index)
        result = percentiles(players, CATALOG, ["score"], group=group)["score"]
        assert result.tolist() == [25.0, 75.0, 25.0, 75.0]

    def test_rows_without_a_group_get_no_percentile(self) -> None:
        players = frame(score=[10.0, 20.0, 30.0])
        group = pd.Series(["Guard", "Guard", None], index=players.index)
        result = percentiles(players, CATALOG, ["score"], group=group)["score"]
        assert math.isnan(result.iloc[2])

    def test_all_catalog_metrics_present_in_the_frame_by_default(self) -> None:
        players = frame(score=[1.0, 2.0], errors=[1.0, 2.0], unrelated=[5, 6])
        result = percentiles(players, CATALOG)
        assert list(result.columns) == ["score", "errors"]

    def test_a_single_qualified_player_sits_at_fifty(self) -> None:
        result = percentiles(frame(score=[12.0]), CATALOG, ["score"])["score"]
        assert result.tolist() == [50.0]

    def test_an_empty_frame(self) -> None:
        empty = pd.DataFrame({"score": pd.Series(dtype="float64")})
        assert percentiles(empty, CATALOG, ["score"]).empty

    def test_on_real_player_seasons(self, normalized) -> None:
        seasons = normalized["player_seasons"]
        regular = seasons[seasons["season_type"] == "regular"]
        metrics = player_season_metrics(regular).set_index("player_id")
        qualified = Qualification(min_games=20, min_minutes=300).mask(metrics)
        result = percentiles(metrics, PLAYER_METRICS, qualified=qualified)
        assert list(result.columns) == list(PLAYER_METRICS.keys)
        assert result.loc[~qualified].isna().all().all()
        scorers = metrics.loc[qualified, "pts_per_game"]
        assert result.loc[scorers.idxmax(), "pts_per_game"] == result["pts_per_game"].max()
        # Fewer turnovers is better, so the most careless qualified player ranks lowest.
        careless = metrics.loc[qualified, "tov_per_game"].idxmax()
        assert result.loc[careless, "tov_per_game"] == result["tov_per_game"].min()


class TestRanks:
    def test_one_is_best(self) -> None:
        players = frame(score=[10.0, 30.0, 20.0], errors=[1.0, 3.0, 2.0])
        assert ranks(players, CATALOG, "score").tolist() == [3, 1, 2]
        assert ranks(players, CATALOG, "errors").tolist() == [1, 3, 2]

    def test_ties_share_the_better_rank(self) -> None:
        players = frame(score=[30.0, 30.0, 10.0])
        assert ranks(players, CATALOG, "score").tolist() == [1, 1, 3]

    def test_unqualified_rows_are_unranked(self) -> None:
        players = frame(score=[10.0, 99.0, 20.0])
        qualified = pd.Series([True, False, True], index=players.index)
        result = ranks(players, CATALOG, "score", qualified=qualified)
        assert result.iloc[0] == 2 and result.iloc[2] == 1
        assert pd.isna(result.iloc[1])


class TestComparison:
    def test_one_line_per_metric_per_player_in_the_order_given(self) -> None:
        players = frame(score=[10.0, 20.0, 30.0], errors=[3.0, 2.0, 1.0])
        ranked = percentiles(players, CATALOG, ["score", "errors"])
        result = comparison(players, ranked, [3, 1], ["score", "errors"])
        assert list(result.columns) == ["metric", "player_id", "value", "percentile"]
        assert result["metric"].tolist() == ["score", "score", "errors", "errors"]
        assert result["player_id"].tolist() == [3, 1, 3, 1]
        assert result["value"].tolist() == [30.0, 10.0, 1.0, 3.0]
        assert result["percentile"].tolist() == pytest.approx([500 / 6, 100 / 6, 500 / 6, 100 / 6])

    def test_an_unknown_player_is_an_error(self) -> None:
        players = frame(score=[10.0])
        ranked = percentiles(players, CATALOG, ["score"])
        with pytest.raises(KeyError, match=r"not in the comparison population: \[99\]"):
            comparison(players, ranked, [1, 99], ["score"])


class TestPooledMetrics:
    def test_pooling_weights_by_volume_not_by_player(self) -> None:
        """A 1-for-10 shooter and a 90-for-100 shooter shoot 91-for-110 together, not 50%."""
        columns = {name: [0, 0] for name in ("fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb",
                                              "ast", "tov", "stl", "blk", "pf", "plus_minus")}  # fmt: skip
        totals = pd.DataFrame(
            {"games_played": [1, 10], "minutes": [10.0, 300.0], "fgm": [1, 90], "fga": [10, 100],
             "pts": [2, 180], **columns}
        )  # fmt: skip
        pooled = pooled_metrics(totals)
        assert pooled["fg_pct"] == pytest.approx(91 / 110)
        mean_of_rates = box_metrics(totals)["fg_pct"].mean()
        assert mean_of_rates == pytest.approx(0.5)
        assert pooled["pts_per_game"] == pytest.approx(182 / 11)

    def test_on_real_data_league_true_shooting_is_plausible(self, normalized) -> None:
        seasons = normalized["player_seasons"]
        pooled = pooled_metrics(seasons[seasons["season_type"] == "regular"])
        assert 0.5 < pooled["ts_pct"] < 0.65
        assert 0.3 < pooled["fg3_pct"] < 0.42
