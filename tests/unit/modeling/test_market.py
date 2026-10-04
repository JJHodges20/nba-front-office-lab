"""The price of a win, read off salaries and wins."""

from __future__ import annotations

import pandas as pd
import pytest

from front_office.modeling.value.market import (
    MIN_CONTRACTS,
    SURPLUS_COLUMNS,
    Market,
    fit_market,
    surplus,
)


def series(*values: float | None) -> pd.Series:
    return pd.Series(values, index=range(101, 101 + len(values)), dtype="float64")


class TestFitMarket:
    def test_a_line_that_pays_so_much_a_win_is_found_exactly(self) -> None:
        wins = series(0.0, 2.0, 5.0, 10.0)
        salary = 2_000_000 + 4_000_000 * wins
        market = fit_market(salary, wins)
        assert market.contracts == 4
        assert market.replacement_cost == pytest.approx(2_000_000)
        assert market.price_per_win == pytest.approx(4_000_000)
        assert market.r2 == pytest.approx(1.0)

    def test_it_is_ordinary_least_squares_on_wins(self) -> None:
        wins, salary = series(1.0, 2.0, 3.0), series(10.0, 40.0, 40.0)
        market = fit_market(salary, wins)
        # Slope: covariance over variance = (-1 x -20 + 0 + 1 x 10) / 2 = 15.
        assert market.price_per_win == pytest.approx(15.0)
        assert market.replacement_cost == pytest.approx(30.0 - 15.0 * 2.0)
        residuals = [10 - 15, 40 - 30, 40 - 45]
        spread = 20**2 + 10**2 + 10**2
        assert market.r2 == pytest.approx(1 - sum(r**2 for r in residuals) / spread)

    def test_a_player_below_replacement_counts_as_worth_no_wins(self) -> None:
        wins = series(-3.0, 0.0, 2.0, 5.0)
        salary = series(2.0, 2.0, 10.0, 22.0)
        market = fit_market(salary, wins)
        clipped = fit_market(salary, wins.clip(lower=0))
        assert market == clipped

    def test_players_without_both_a_salary_and_wins_are_left_out(self) -> None:
        wins = series(0.0, 2.0, 5.0, 10.0, None, 7.0)
        salary = series(2.0, 10.0, 22.0, 42.0, 99.0, None)
        market = fit_market(salary, wins)
        assert market.contracts == 4 and market.price_per_win == pytest.approx(4.0)

    def test_players_are_matched_by_their_ids(self) -> None:
        wins = pd.Series([0.0, 2.0, 5.0], index=[1, 2, 3])
        salary = pd.Series([22.0, 2.0, 10.0], index=[3, 1, 2])
        assert fit_market(salary, wins).price_per_win == pytest.approx(4.0)

    def test_too_few_contracts_say_nothing(self) -> None:
        assert MIN_CONTRACTS == 3
        assert fit_market(series(2.0, 10.0), series(0.0, 2.0)) is None
        assert fit_market(series(), series()) is None

    def test_players_all_worth_the_same_have_no_slope(self) -> None:
        assert fit_market(series(2.0, 10.0, 30.0), series(3.0, 3.0, 3.0)) is None
        # All below replacement is all worth nothing.
        assert fit_market(series(2.0, 10.0, 30.0), series(-1.0, -2.0, -3.0)) is None

    def test_contracts_that_pay_less_for_more_wins_give_no_price(self) -> None:
        assert fit_market(series(30.0, 20.0, 10.0), series(1.0, 2.0, 3.0)) is None
        assert fit_market(series(20.0, 20.0, 20.0), series(1.0, 2.0, 3.0)) is None

    def test_a_noisy_market_explains_part_of_salary(self) -> None:
        wins = series(0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
        salary = series(3.0, 4.0, 14.0, 9.0, 22.0, 20.0)
        market = fit_market(salary, wins)
        assert market.price_per_win > 0 and 0 < market.r2 < 1


class TestSurplus:
    MARKET = Market(contracts=10, replacement_cost=2.0, price_per_win=4.0, r2=0.5)

    def test_worth_is_the_line_and_surplus_is_what_is_left_after_the_salary(self) -> None:
        found = surplus(series(10.0, 30.0), series(5.0, 5.0), self.MARKET)
        assert tuple(found.columns) == SURPLUS_COLUMNS
        assert found["market_value"].tolist() == [22.0, 22.0]
        assert found["surplus"].tolist() == [12.0, -8.0]
        assert found["cost_per_win"].tolist() == [2.0, 6.0]

    def test_below_replacement_is_worth_the_replacement_cost(self) -> None:
        found = surplus(series(1.0, 1.0), series(-2.0, 0.0), self.MARKET)
        assert found["market_value"].tolist() == [2.0, 2.0]
        assert found["surplus"].tolist() == [1.0, 1.0]

    def test_cost_per_win_needs_wins_worth_more_than_none(self) -> None:
        found = surplus(series(10.0, 10.0, 10.0), series(0.0, -1.0, 4.0), self.MARKET)
        assert found["cost_per_win"].isna().tolist() == [True, True, False]
        assert found["cost_per_win"].iloc[2] == 2.5

    def test_without_a_market_only_the_cost_per_win_is_known(self) -> None:
        found = surplus(series(10.0, 30.0), series(5.0, 2.0), None)
        assert found["market_value"].isna().all() and found["surplus"].isna().all()
        assert found["cost_per_win"].tolist() == [2.0, 15.0]

    def test_wins_are_matched_to_salaries_by_id(self) -> None:
        salary = pd.Series([10.0, 30.0], index=[7, 8])
        wins = pd.Series([1.0, 5.0], index=[8, 7])
        found = surplus(salary, wins, self.MARKET)
        assert found.index.tolist() == [7, 8]
        assert found["market_value"].tolist() == [22.0, 6.0]

    def test_a_player_without_wins_has_no_worth(self) -> None:
        found = surplus(series(10.0, 30.0), series(5.0, None), self.MARKET)
        assert found.iloc[1].isna().all()

    def test_no_players_no_rows(self) -> None:
        found = surplus(series(), series(), self.MARKET)
        assert found.empty and tuple(found.columns) == SURPLUS_COLUMNS

    def test_the_market_values_a_series_of_wins(self) -> None:
        assert self.MARKET.value(series(-1.0, 0.0, 2.5)).tolist() == [2.0, 2.0, 12.0]
