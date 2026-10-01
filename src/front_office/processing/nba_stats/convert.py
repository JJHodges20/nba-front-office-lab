"""Explicit value conversions for stats.nba.com columns.

Result sets arrive as untyped objects. Each helper converts one kind of column and fails
on anything it does not recognise, so an unexpected value is reported where it enters
rather than discovered later in an analysis.
"""

from __future__ import annotations

import re

import pandas as pd

from front_office.processing.nba_stats.resultsets import PayloadError

_HEIGHT = re.compile(r"^(\d)-(\d{1,2})$")


def integers(series: pd.Series) -> pd.Series:
    """Whole numbers (nullable). Accepts ints, integral floats and numeric text."""
    numbers = _numbers(series)
    fractional = numbers.notna() & (numbers != numbers.round())
    if fractional.any():
        raise PayloadError(
            f"column {series.name!r} should hold whole numbers; found {_examples(series[fractional])}"
        )
    return numbers.astype("Int64")


def rounded_counts(series: pd.Series, *, max_share: float = 0.05) -> tuple[pd.Series, int]:
    """Whole numbers from a column of counts that may hold a few fractional values.

    The league's season totals contain the occasional fractional count (one team-season
    in thirty years). Those are rounded to the nearest whole number and the number of
    rounded values is returned so the caller can report it. If more than ``max_share``
    of the column is fractional, the column is not a column of counts at all - most
    likely per-game averages - and that is an error, not something to round.
    """
    numbers = _numbers(series)
    fractional = numbers.notna() & (numbers != numbers.round())
    rounded = int(fractional.sum())
    if rounded and rounded > max_share * max(int(numbers.notna().sum()), 1):
        raise PayloadError(
            f"column {series.name!r} should hold whole numbers but {rounded} of "
            f"{int(numbers.notna().sum())} values are fractional: {_examples(series[fractional])}"
        )
    return numbers.round().astype("Int64"), rounded


def floats(series: pd.Series) -> pd.Series:
    """Real numbers, with missing values as NaN."""
    return _numbers(series)


def text(series: pd.Series) -> pd.Series:
    """Text, trimmed, with empty strings turned into nulls.

    The result is an object column whose missing values are ``None``, so callers can
    test a value's truthiness without tripping over NaN.
    """
    present = series.notna()
    not_text = present & ~series.map(lambda value: isinstance(value, str))
    if not_text.any():
        raise PayloadError(
            f"column {series.name!r} should hold text; found {_examples(series[not_text])}"
        )
    cleaned = [(value.strip() or None) if isinstance(value, str) else None for value in series]
    # Built from a list with an explicit dtype: pandas would otherwise infer its string
    # dtype and turn each None into NaN.
    return pd.Series(cleaned, index=series.index, name=series.name, dtype=object)


def flags(series: pd.Series, *, true: object, false: object) -> pd.Series:
    """Booleans (nullable) from a two-valued column such as W/L."""
    present = series.notna()
    unknown = present & ~series.isin([true, false])
    if unknown.any():
        raise PayloadError(
            f"column {series.name!r} should hold {true!r} or {false!r}; "
            f"found {_examples(series[unknown])}"
        )
    return series.map({true: True, false: False}).astype("boolean")


def heights(series: pd.Series) -> pd.Series:
    """Heights written as feet-inches ("6-8") converted to inches."""
    cleaned = text(series)

    def inches(value: object) -> int | None:
        if value is None:
            return None
        match = _HEIGHT.match(str(value))
        if match is None or int(match.group(2)) > 11:
            raise PayloadError(f"column {series.name!r}: unrecognised height {value!r}")
        return int(match.group(1)) * 12 + int(match.group(2))

    return cleaned.map(inches).astype("Int64")


def dates(series: pd.Series, *, format: str) -> pd.Series:
    """Dates written in one known format; anything else is an error."""
    cleaned = text(series)
    parsed = pd.to_datetime(cleaned, format=format, errors="coerce")
    unparsed = cleaned.notna() & parsed.isna()
    if unparsed.any():
        raise PayloadError(
            f"column {series.name!r}: dates not in format {format!r}: {_examples(cleaned[unparsed])}"
        )
    return parsed


def _numbers(series: pd.Series) -> pd.Series:
    is_bool = series.map(lambda value: isinstance(value, bool))
    if is_bool.any():
        raise PayloadError(f"column {series.name!r} should hold numbers; found booleans")
    numbers = pd.to_numeric(series, errors="coerce").astype("float64")
    unparsed = series.notna() & numbers.isna()
    if unparsed.any():
        raise PayloadError(
            f"column {series.name!r} should hold numbers; found {_examples(series[unparsed])}"
        )
    return numbers


def _examples(values: pd.Series) -> str:
    return repr(sorted({repr(value) for value in values})[:5])
