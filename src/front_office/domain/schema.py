"""Data contracts: the declared shape of every dataset that crosses a layer boundary.

A :class:`TableContract` names the columns of one canonical table, their types, what
each value means and where it comes from. Processing modules must produce frames that
satisfy a contract; storage builds its tables from the same definitions; the data
dictionary is generated from them. One definition, three uses.

"Contract" here always means a *data* contract. Player salary agreements are modelled
by the ``contracts`` and ``contract_years`` tables.

Validation is deliberately strict. A numeric column holding text, a text column holding
numbers, an empty string standing in for "missing": each is rejected rather than quietly
repaired, because a silent repair is how an untrustworthy number reaches a screen.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd


class DType(StrEnum):
    """Logical column types, independent of pandas or any database."""

    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    """A moment in time, always UTC, held without a timezone marker."""


class Provenance(StrEnum):
    """Where a value comes from.

    The workbench must keep measured statistics, modeled estimates and user assumptions
    visibly apart. Declaring provenance on the column lets every screen label a number
    correctly without knowing how it was produced.
    """

    IDENTIFIER = "identifier"
    """Keys, names and labels."""
    MEASURED = "measured"
    """Recorded by the source: box-score counts, official cap figures, signed salaries."""
    DERIVED = "derived"
    """Deterministic arithmetic on measured values, e.g. salary as a share of the cap."""
    MODELED = "modeled"
    """Output of a statistical model or weighted composite; an estimate, not a fact."""
    ASSUMPTION = "assumption"
    """Entered or chosen by the user."""
    OPERATIONAL = "operational"
    """Pipeline bookkeeping: fetch times, run status, versions."""


@dataclass(frozen=True, slots=True)
class Field:
    """One column of a table contract."""

    name: str
    dtype: DType
    description: str
    nullable: bool = True
    provenance: Provenance = Provenance.MEASURED
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    allowed: tuple[str, ...] | None = None
    references: str | None = None
    """``"table.column"`` this value points at, when it is a foreign key."""

    def __post_init__(self) -> None:
        if not self.name.isidentifier() or self.name != self.name.lower():
            raise ValueError(f"field name must be a lowercase identifier: {self.name!r}")
        if not self.description.strip():
            raise ValueError(f"field {self.name!r} needs a description")
        if self.allowed is not None and self.dtype is not DType.STRING:
            raise ValueError(f"field {self.name!r}: 'allowed' applies only to string fields")
        numeric = self.dtype in (DType.INTEGER, DType.FLOAT)
        if (self.minimum is not None or self.maximum is not None) and not numeric:
            raise ValueError(f"field {self.name!r}: range limits apply only to numeric fields")
        if self.references is not None and self.references.count(".") != 1:
            raise ValueError(f"field {self.name!r}: references must look like 'table.column'")


@dataclass(frozen=True, slots=True)
class TableContract:
    """The declared shape of one canonical table."""

    name: str
    domain: str
    description: str
    grain: str
    """What one row represents, in words."""
    fields: tuple[Field, ...]
    primary_key: tuple[str, ...]
    indexes: tuple[tuple[str, ...], ...] = ()
    introduced_in: str = "V1"

    def __post_init__(self) -> None:
        names = [field.name for field in self.fields]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"table {self.name!r} repeats fields: {duplicates}")
        if not self.primary_key:
            raise ValueError(f"table {self.name!r} needs a primary key")
        by_name = {field.name: field for field in self.fields}
        for column in self.primary_key:
            if column not in by_name:
                raise ValueError(
                    f"table {self.name!r}: primary key column {column!r} is undeclared"
                )
            if by_name[column].nullable:
                raise ValueError(f"table {self.name!r}: primary key column {column!r} is nullable")
        for index in self.indexes:
            missing = [column for column in index if column not in by_name]
            if missing:
                raise ValueError(f"table {self.name!r}: index uses undeclared columns {missing}")

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def field(self, name: str) -> Field:
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        raise KeyError(f"table {self.name!r} has no field {name!r}")

    def empty_frame(self) -> pd.DataFrame:
        """A zero-row frame with this contract's columns and canonical dtypes."""
        return pd.DataFrame(
            {field.name: pd.Series(dtype=pandas_dtype(field)) for field in self.fields}
        )


@dataclass(frozen=True, slots=True)
class Violation:
    """One way a frame fails its contract."""

    table: str
    rule: str
    column: str | None
    detail: str
    rows: int = 0

    def __str__(self) -> str:
        where = f"{self.table}.{self.column}" if self.column else self.table
        suffix = f" ({self.rows} rows)" if self.rows else ""
        return f"[{self.rule}] {where}: {self.detail}{suffix}"


class ContractViolationError(ValueError):
    """Raised when a frame does not satisfy its contract."""

    def __init__(self, table: str, violations: list[Violation]) -> None:
        self.table = table
        self.violations = violations
        shown = "\n".join(f"  - {violation}" for violation in violations[:20])
        more = f"\n  ... and {len(violations) - 20} more" if len(violations) > 20 else ""
        super().__init__(f"{table}: {len(violations)} contract violation(s)\n{shown}{more}")


def validate_frame(frame: pd.DataFrame, contract: TableContract) -> list[Violation]:
    """Return every way ``frame`` breaks ``contract`` (an empty list means it conforms)."""
    return _check(frame, contract)[1]


def conform_frame(frame: pd.DataFrame, contract: TableContract) -> pd.DataFrame:
    """Return ``frame`` with contract column order and canonical dtypes, or raise.

    The input is not modified.
    """
    conformed, violations = _check(frame, contract)
    if violations:
        raise ContractViolationError(contract.name, violations)
    return conformed


def pandas_dtype(field: Field) -> str:
    """Canonical pandas dtype for a field.

    Required integers and booleans use plain NumPy dtypes; nullable ones use pandas'
    masked dtypes so that a missing id never silently becomes a float.
    """
    if field.dtype is DType.INTEGER:
        return "Int64" if field.nullable else "int64"
    if field.dtype is DType.FLOAT:
        return "float64"
    if field.dtype is DType.STRING:
        return "str"
    if field.dtype is DType.BOOLEAN:
        return "boolean" if field.nullable else "bool"
    return "datetime64[ns]"


_ALL_MISSING_DTYPE = {
    DType.INTEGER: "Int64",
    DType.FLOAT: "float64",
    DType.STRING: "str",
    DType.BOOLEAN: "boolean",
    DType.DATE: "datetime64[ns]",
    DType.DATETIME: "datetime64[ns]",
}


def _check(frame: pd.DataFrame, contract: TableContract) -> tuple[pd.DataFrame, list[Violation]]:
    violations: list[Violation] = []
    table = contract.name

    for column in contract.column_names:
        if column not in frame.columns:
            violations.append(Violation(table, "missing_column", column, "column is absent"))
    for column in frame.columns:
        if column not in contract.column_names:
            violations.append(Violation(table, "unexpected_column", str(column), "not in contract"))

    columns: dict[str, pd.Series] = {}
    for field in contract.fields:
        if field.name not in frame.columns:
            continue
        original = frame[field.name]
        missing = int(original.isna().sum())
        if missing and not field.nullable:
            violations.append(Violation(table, "null_value", field.name, "required", missing))
        series, bad = _coerce(original, field)
        if bad:
            violations.append(
                Violation(table, "wrong_type", field.name, f"not a valid {field.dtype.value}", bad)
            )
        violations.extend(_check_values(table, field, series))
        columns[field.name] = series

    if all(column in columns for column in contract.primary_key):
        keys = pd.DataFrame({column: columns[column] for column in contract.primary_key})
        repeated = int(keys.duplicated(keep="first").sum())
        if repeated:
            key = ", ".join(contract.primary_key)
            violations.append(
                Violation(table, "duplicate_key", None, f"primary key ({key}) repeats", repeated)
            )

    if violations:
        return frame, violations

    conformed = pd.DataFrame(
        {field.name: columns[field.name].astype(pandas_dtype(field)) for field in contract.fields},
        index=frame.index,
    )
    return conformed.reset_index(drop=True), []


def _coerce(series: pd.Series, field: Field) -> tuple[pd.Series, int]:
    """Bring ``series`` to the field's type.

    Returns the converted series, with unconvertible values blanked out, and how many
    values were unconvertible.
    """
    present = series.notna()
    if not present.any():
        empty = pd.array([None] * len(series), dtype=_ALL_MISSING_DTYPE[field.dtype])
        return pd.Series(empty, index=series.index), 0

    kind = series.dtype
    is_bool = pd.api.types.is_bool_dtype(kind)
    is_number = pd.api.types.is_numeric_dtype(kind) and not is_bool
    none_bad = pd.Series(False, index=series.index)

    if field.dtype in (DType.INTEGER, DType.FLOAT):
        bad = none_bad if is_number else present & ~series.map(_is_number)
        numeric = pd.to_numeric(series.where(~bad), errors="coerce").astype("float64")
        bad = bad | (present & ~np.isfinite(numeric))
        if field.dtype is DType.FLOAT:
            return numeric.where(~bad), int(bad.sum())
        bad = bad | (present & ~bad & (numeric != np.floor(numeric)))
        if bad.any():
            return numeric.where(~bad), int(bad.sum())
        # Convert from the original values: a float64 round trip would lose precision
        # on very large integers.
        return pd.to_numeric(series, errors="coerce").astype("Int64"), 0

    if field.dtype is DType.STRING:
        # An object column may hold anything, so its values are checked one by one.
        if not pd.api.types.is_object_dtype(kind) and pd.api.types.is_string_dtype(kind):
            return series, 0
        bad = present & ~series.map(lambda value: isinstance(value, str))
        return series.where(~bad), int(bad.sum())

    if field.dtype is DType.BOOLEAN:
        if is_bool:
            return series, 0
        bad = present & ~series.map(lambda value: isinstance(value, bool | np.bool_))
        cleaned = series.where(~bad)
        return (cleaned if bad.any() else cleaned.astype("boolean")), int(bad.sum())

    # DATE and DATETIME. Numbers are rejected outright: pandas would otherwise read an
    # integer such as 20251021 as nanoseconds since 1970. Text must be ISO 8601, so a
    # value like "03/04/2025" is never guessed at.
    if is_number or is_bool:
        return series, int(present.sum())
    if pd.api.types.is_datetime64_any_dtype(kind):
        bad = none_bad
    else:
        bad = present & ~series.map(_is_temporal)
    moments = pd.to_datetime(
        series.where(~bad), format="ISO8601", errors="coerce", utc=True
    ).dt.tz_localize(None)
    bad = bad | (present & moments.isna())
    if field.dtype is DType.DATE:
        bad = bad | (present & ~bad & (moments != moments.dt.normalize()))
    return moments.where(~bad), int(bad.sum())


def _is_number(value: object) -> bool:
    return isinstance(value, int | float | np.integer | np.floating) and not isinstance(
        value, bool | np.bool_
    )


def _is_temporal(value: object) -> bool:
    return isinstance(value, str | dt.date | np.datetime64)


def _check_values(table: str, field: Field, series: pd.Series) -> list[Violation]:
    found: list[Violation] = []
    if field.minimum is not None or field.maximum is not None:
        numeric = pd.to_numeric(series, errors="coerce").astype("float64")
        if field.minimum is not None:
            low = int((numeric < field.minimum).sum())
            if low:
                found.append(
                    Violation(
                        table, "below_minimum", field.name, f"less than {field.minimum:g}", low
                    )
                )
        if field.maximum is not None:
            high = int((numeric > field.maximum).sum())
            if high:
                found.append(
                    Violation(
                        table, "above_maximum", field.name, f"more than {field.maximum:g}", high
                    )
                )
    if field.dtype is DType.STRING:
        text = series[series.map(lambda value: isinstance(value, str))]
        blank = int((text.str.strip() == "").sum())
        if blank:
            found.append(
                Violation(
                    table, "blank_value", field.name, "empty text; use null for missing", blank
                )
            )
        if field.allowed is not None:
            outside = ~text.isin(field.allowed)
            if outside.any():
                examples = sorted(set(text[outside]))[:5]
                found.append(
                    Violation(
                        table,
                        "not_allowed",
                        field.name,
                        f"unexpected values {examples}; allowed {list(field.allowed)}",
                        int(outside.sum()),
                    )
                )
    return found
