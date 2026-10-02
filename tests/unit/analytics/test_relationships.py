from __future__ import annotations

import math

import pandas as pd
import pytest

from front_office.analytics.relationships import MIN_SAMPLE, Relationship, relationship


def frame(x: list, y: list) -> pd.DataFrame:
    return pd.DataFrame({"x": x, "y": y})


def test_a_perfect_line() -> None:
    result = relationship(frame([1, 2, 3, 4], [10, 20, 30, 40]), "x", "y")
    assert result == Relationship("x", "y", 4, pytest.approx(1.0), pytest.approx(1.0))


def test_a_falling_relationship_is_negative() -> None:
    result = relationship(frame([1, 2, 3, 4], [9, 7, 4, 1]), "x", "y")
    assert result.pearson < -0.98 and result.spearman == pytest.approx(-1.0)


def test_rank_correlation_sees_a_curve_as_perfectly_monotone() -> None:
    result = relationship(frame([1, 2, 3, 4, 5], [1, 4, 9, 16, 25]), "x", "y")
    assert result.spearman == pytest.approx(1.0)
    assert 0.9 < result.pearson < 1.0


def test_a_worked_example() -> None:
    """x = 1, 2, 3, 4 and y = 2, 1, 4, 3: covariance 1, variances 5/3, so r = 0.6."""
    result = relationship(frame([1, 2, 3, 4], [2, 1, 4, 3]), "x", "y")
    assert result.pearson == pytest.approx(0.6)
    assert result.spearman == pytest.approx(0.6)


def test_rows_missing_either_value_are_left_out() -> None:
    result = relationship(frame([1, 2, None, 4, 5], [2, 4, 6, None, 10]), "x", "y")
    assert result.sample == 3
    assert result.pearson == pytest.approx(1.0)


def test_too_few_rows_give_no_correlation() -> None:
    assert MIN_SAMPLE == 3
    result = relationship(frame([1, 2], [3, 5]), "x", "y")
    assert result.sample == 2
    assert math.isnan(result.pearson) and math.isnan(result.spearman)


def test_a_constant_column_gives_no_correlation() -> None:
    result = relationship(frame([1, 2, 3, 4], [5, 5, 5, 5]), "x", "y")
    assert result.sample == 4
    assert math.isnan(result.pearson) and math.isnan(result.spearman)


def test_a_metric_against_itself() -> None:
    result = relationship(frame([1, 5, 2, 8], [0, 0, 0, 0]), "x", "x")
    assert (result.x, result.y, result.sample) == ("x", "x", 4)
    assert result.pearson == pytest.approx(1.0)


def test_nullable_integer_columns() -> None:
    data = pd.DataFrame(
        {"x": pd.array([1, 2, 3, None], dtype="Int64"), "y": pd.array([2, 4, 7, 9], dtype="Int64")}
    )
    result = relationship(data, "x", "y")
    assert result.sample == 3 and result.pearson > 0.9


def test_an_empty_frame() -> None:
    result = relationship(frame([], []), "x", "y")
    assert result.sample == 0 and math.isnan(result.pearson)


def test_on_real_players_usage_and_scoring_rise_together(normalized) -> None:
    seasons = normalized["player_seasons"]
    regular = seasons[seasons["season_type"] == "regular"]
    result = relationship(regular, "usage_pct", "pts")
    assert result.sample == len(regular.dropna(subset=["usage_pct", "pts"]))
    assert result.pearson > 0.5 and result.spearman > 0.5


def test_the_input_is_not_modified() -> None:
    data = frame([1, 2, 3], [3, 2, 1])
    before = data.copy(deep=True)
    relationship(data, "x", "y")
    pd.testing.assert_frame_equal(data, before)
