from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from front_office.processing.nba_stats import convert
from front_office.processing.nba_stats.resultsets import PayloadError


def column(values: list[object], name: str = "COL") -> pd.Series:
    return pd.Series(values, dtype=object, name=name)


class TestIntegers:
    def test_accepts_ints_integral_floats_and_numeric_text(self) -> None:
        result = convert.integers(column([1, 2.0, "3", None]))
        assert str(result.dtype) == "Int64"
        assert result.tolist()[:3] == [1, 2, 3]
        assert result.isna().tolist() == [False, False, False, True]

    def test_keeps_large_ids_exact(self) -> None:
        assert convert.integers(column([1610612738])).tolist() == [1610612738]

    def test_rejects_fractions(self) -> None:
        with pytest.raises(PayloadError, match="whole numbers"):
            convert.integers(column([1, 1253.8]))

    @pytest.mark.parametrize("bad", ["R", "12a", True])
    def test_rejects_non_numbers(self, bad: object) -> None:
        with pytest.raises(PayloadError, match="'COL'"):
            convert.integers(column([1, bad]))

    def test_empty_column(self) -> None:
        assert len(convert.integers(column([]))) == 0


class TestRoundedCounts:
    def test_whole_numbers_pass_through(self) -> None:
        values, rounded = convert.rounded_counts(column([10, 20.0, None]))
        assert values.tolist()[:2] == [10, 20]
        assert rounded == 0

    def test_a_rare_fraction_is_rounded_and_counted(self) -> None:
        values, rounded = convert.rounded_counts(column([1399.0] * 28 + [1253.8]))
        assert values.tolist()[-1] == 1254
        assert rounded == 1

    def test_a_column_of_averages_is_not_rounded_away(self) -> None:
        """Per-game averages where totals were expected must fail, not be silently rounded."""
        with pytest.raises(PayloadError, match="values are fractional"):
            convert.rounded_counts(column([112.4, 108.9, 115.2, 101.0]))

    def test_the_share_allowed_is_configurable(self) -> None:
        values, rounded = convert.rounded_counts(column([1.5, 2.0]), max_share=0.5)
        assert rounded == 1
        assert values.tolist() == [2, 2]


class TestFloats:
    def test_numbers_become_floats_and_missing_becomes_nan(self) -> None:
        result = convert.floats(column([1, 2.5, "3.25", None]))
        assert str(result.dtype) == "float64"
        assert result.tolist()[:3] == [1.0, 2.5, 3.25]
        assert np.isnan(result.iloc[3])

    def test_rejects_text(self) -> None:
        with pytest.raises(PayloadError):
            convert.floats(column([1.0, "n/a"]))


class TestText:
    def test_trims_and_turns_blanks_into_none(self) -> None:
        result = convert.text(column(["  BOS ", "", "   ", None, "Vučević"]))
        assert result.tolist() == ["BOS", None, None, None, "Vučević"]
        assert result.dtype == object

    def test_missing_values_are_none_not_nan(self) -> None:
        """Callers test truthiness; NaN is truthy and would slip through."""
        result = convert.text(column([np.nan, None, "x"]))
        assert result.tolist()[0] is None
        assert result.tolist()[1] is None

    def test_rejects_numbers(self) -> None:
        with pytest.raises(PayloadError, match="should hold text"):
            convert.text(column(["a", 5]))

    def test_keeps_index_and_name(self) -> None:
        source = pd.Series(["a", "b"], index=[7, 9], name="TEAM", dtype=object)
        result = convert.text(source)
        assert result.index.tolist() == [7, 9]
        assert result.name == "TEAM"


class TestFlags:
    def test_two_values_become_booleans(self) -> None:
        result = convert.flags(column(["W", "L", None]), true="W", false="L")
        assert str(result.dtype) == "boolean"
        assert result.tolist()[:2] == [True, False]
        assert result.isna().tolist() == [False, False, True]

    def test_rejects_anything_else(self) -> None:
        with pytest.raises(PayloadError, match="'W' or 'L'"):
            convert.flags(column(["W", "T"]), true="W", false="L")


class TestHeights:
    @pytest.mark.parametrize(
        ("text", "inches"), [("6-8", 80), ("7-0", 84), ("5-11", 71), ("6-10", 82)]
    )
    def test_feet_and_inches(self, text: str, inches: int) -> None:
        assert convert.heights(column([text])).tolist() == [inches]

    def test_missing_height(self) -> None:
        result = convert.heights(column([None, "", "6-8"]))
        assert result.isna().tolist() == [True, True, False]
        assert str(result.dtype) == "Int64"

    @pytest.mark.parametrize("bad", ["6'8", "6-12", "68", "six-eight"])
    def test_rejects_unrecognised_heights(self, bad: str) -> None:
        with pytest.raises(PayloadError, match="unrecognised height"):
            convert.heights(column([bad]))


class TestDates:
    def test_parses_the_given_format(self) -> None:
        result = convert.dates(column(["MAR 03, 1998", None]), format="%b %d, %Y")
        assert result.iloc[0] == pd.Timestamp("1998-03-03")
        assert pd.isna(result.iloc[1])

    def test_iso_dates(self) -> None:
        result = convert.dates(column(["2025-10-21"]), format="%Y-%m-%d")
        assert result.iloc[0] == pd.Timestamp("2025-10-21")

    def test_rejects_other_formats(self) -> None:
        with pytest.raises(PayloadError, match="dates not in format"):
            convert.dates(column(["2025-10-21", "10/21/2025"]), format="%Y-%m-%d")
