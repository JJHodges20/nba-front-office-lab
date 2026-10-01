"""Metric definitions: what a number is, how to show it, and which way is good.

Analytics computes metrics; the workbench displays them. A :class:`MetricSpec` travels
with each metric so that a screen can label it, format it, explain it, and mark whether
it was measured or derived, without knowing anything about how it was produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from front_office.domain.schema import Provenance


class MetricFormat(StrEnum):
    COUNT = "count"
    """A whole number: games, wins."""
    DECIMAL = "decimal"
    """A plain number shown to a fixed number of decimals: points per game."""
    PERCENT = "percent"
    """A fraction between 0 and 1 shown as a percentage: 0.588 -> 58.8%."""
    SIGNED = "signed"
    """A number whose sign matters and is always shown: +5.7, -2.1."""
    MONEY = "money"
    """US dollars."""


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    """Column name in analytics output."""
    label: str
    """Short header, as on a stat sheet: ``TS%``."""
    name: str
    """Full name: ``True shooting percentage``."""
    description: str
    """What it measures and, for a derived metric, how it is computed."""
    category: str
    format: MetricFormat = MetricFormat.DECIMAL
    provenance: Provenance = Provenance.DERIVED
    higher_is_better: bool | None = True
    """``None`` when neither direction is better, as for age or minutes."""
    decimals: int = 1

    def __post_init__(self) -> None:
        if not self.key.isidentifier() or self.key != self.key.lower():
            raise ValueError(f"metric key must be a lowercase identifier: {self.key!r}")
        for attribute in ("label", "name", "description", "category"):
            if not getattr(self, attribute).strip():
                raise ValueError(f"metric {self.key!r} needs a {attribute}")
        if self.decimals < 0:
            raise ValueError(f"metric {self.key!r}: decimals cannot be negative")

    def format_value(self, value: float | None) -> str:
        """The value as it should appear on screen; an em dash when it is missing."""
        if value is None or value != value:  # NaN is the only value unequal to itself
            return "—"
        if self.format is MetricFormat.COUNT:
            return f"{value:,.0f}"
        if self.format is MetricFormat.PERCENT:
            return f"{value * 100:.{self.decimals}f}%"
        if self.format is MetricFormat.SIGNED:
            return f"{value:+.{self.decimals}f}"
        if self.format is MetricFormat.MONEY:
            return f"${value:,.0f}"
        return f"{value:,.{self.decimals}f}"


class MetricCatalog:
    """An ordered, uniquely-keyed collection of metric definitions."""

    def __init__(self, specs: tuple[MetricSpec, ...]) -> None:
        keys = [spec.key for spec in specs]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"metric keys repeat: {repeated}")
        self._specs = specs
        self._by_key = {spec.key: spec for spec in specs}

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def __getitem__(self, key: str) -> MetricSpec:
        try:
            return self._by_key[key]
        except KeyError:
            raise KeyError(f"no metric named {key!r}") from None

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._by_key)

    @property
    def categories(self) -> tuple[str, ...]:
        """Categories in the order they first appear."""
        return tuple(dict.fromkeys(spec.category for spec in self._specs))

    def in_category(self, category: str) -> tuple[MetricSpec, ...]:
        return tuple(spec for spec in self._specs if spec.category == category)
