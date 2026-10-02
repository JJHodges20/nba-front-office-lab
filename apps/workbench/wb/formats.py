"""Turning values into text. Formatting only: no figure is derived here."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from front_office.domain.cap_rules import PayrollLine
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec

MISSING = "—"

LINE_LABELS = {
    PayrollLine.MINIMUM_TEAM_SALARY: "Floor",
    PayrollLine.SALARY_CAP: "Cap",
    PayrollLine.LUXURY_TAX: "Tax",
    PayrollLine.FIRST_APRON: "1st apron",
    PayrollLine.SECOND_APRON: "2nd apron",
}
"""What each payroll line is called where there is room for a word, not a phrase."""
LINES_EXPLAINED = (
    "Floor: the minimum team salary. Cap: the salary cap. Tax: the luxury tax line. "
    "Aprons: the two lines above the tax that add restrictions."
)


CONTRACT_TYPES = {"standard": "Standard", "two_way": "Two-way"}
CONTRACT_STATUSES = {"active": "Under contract", "dead_money": "Dead money"}


def words(value: object) -> str:
    """A stored code as words: ``early_termination`` -> ``Early termination``."""
    return MISSING if is_missing(value) else str(value).replace("_", " ").capitalize()


def is_missing(value: object) -> bool:
    return value is None or value is pd.NA or value != value  # NaN is unequal to itself


def money(value: object) -> str:
    """Whole dollars: ``$40,000,000``."""
    return MISSING if is_missing(value) else f"${float(value):,.0f}"


def money_compact(value: object) -> str:
    """Dollars in the largest unit that fits: ``$40.0M``, ``$600K``."""
    if is_missing(value):
        return MISSING
    amount = float(value)
    sign = "-" if amount < 0 else ""
    size = abs(amount)
    if size >= 1_000_000:
        return f"{sign}${size / 1_000_000:,.1f}M"
    if size >= 1_000:
        return f"{sign}${size / 1_000:,.0f}K"
    return f"{sign}${size:,.0f}"


def share(value: object, decimals: int = 1) -> str:
    """A fraction as a percentage: 0.243 -> ``24.3%``."""
    return MISSING if is_missing(value) else f"{float(value) * 100:.{decimals}f}%"


def number(value: object, decimals: int = 0) -> str:
    return MISSING if is_missing(value) else f"{float(value):,.{decimals}f}"


def ordinal(value: object) -> str:
    """A rank as it is spoken: ``1st``, ``22nd``, ``13th``."""
    if is_missing(value):
        return MISSING
    rank = int(value)
    if 10 <= rank % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def rank_of(rank: object, size: object) -> str:
    """``4th of 30``."""
    if is_missing(rank):
        return MISSING
    return f"{ordinal(rank)} of {int(size)}" if not is_missing(size) else ordinal(rank)


def percentile(value: object) -> str:
    """A percentile as a rank among a hundred: ``92nd percentile``.

    Shown from 1st to 99th: nobody is ahead of everyone including themselves, and the
    top of a large group would otherwise round up to a hundredth percentile.
    """
    if is_missing(value):
        return MISSING
    return f"{ordinal(min(max(round(float(value)), 1), 99))} percentile"


def height(inches: object) -> str:
    if is_missing(inches):
        return MISSING
    feet, rest = divmod(int(inches), 12)
    return f"{feet}'{rest}\""


def moment(value: object) -> str:
    """A stored UTC time as text: ``Oct 01, 2026 12:00 UTC``."""
    if is_missing(value):
        return MISSING
    stamp = value if isinstance(value, datetime) else pd.Timestamp(value).to_pydatetime()
    return f"{stamp:%b %d, %Y %H:%M} UTC"


def day(value: object) -> str:
    return MISSING if is_missing(value) else f"{pd.Timestamp(value):%b %d, %Y}"


def tickformat(spec: MetricSpec) -> str:
    """The d3 axis format that matches how a metric is shown."""
    if spec.format is MetricFormat.PERCENT:
        return f".{spec.decimals}%"
    if spec.format is MetricFormat.SIGNED:
        return f"+.{spec.decimals}f"
    if spec.format is MetricFormat.MONEY:
        return "$,.0f"
    if spec.format is MetricFormat.COUNT:
        return ",.0f"
    return f",.{spec.decimals}f"


def shown(catalog: MetricCatalog, frame: pd.DataFrame, key: str) -> pd.Series:
    """One metric column as the text a reader sees, on the frame's index."""
    spec = catalog[key]
    return frame[key].map(spec.format_value).astype("str")


def styled(frame: pd.DataFrame, catalog: MetricCatalog, extra: dict | None = None):  # type: ignore[no-untyped-def]
    """``frame`` with every metric column shown in its own format.

    The values underneath stay numbers, so a table sorts by value, not by text.
    ``extra`` maps other columns to a formatting function.
    """
    formats = {key: catalog[key].format_value for key in frame.columns if key in catalog}
    formats.update(extra or {})
    return frame.style.format(formats, na_rep=MISSING)
