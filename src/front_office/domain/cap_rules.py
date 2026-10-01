"""Season-specific salary-cap and roster rules.

These models describe *what* a season's financial rules are. The figures themselves are
never written in Python: they are loaded from ``configs/seasons/<season>.yaml`` by
:mod:`front_office.config.season_rules`, because they change every league year.

All money is whole US dollars.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, PositiveInt, field_validator, model_validator

from front_office.domain.seasons import Season


class _Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PayrollLine(StrEnum):
    """The payroll thresholds a roster's total salary is measured against."""

    MINIMUM_TEAM_SALARY = "minimum_team_salary"
    SALARY_CAP = "salary_cap"
    LUXURY_TAX = "luxury_tax"
    FIRST_APRON = "first_apron"
    SECOND_APRON = "second_apron"

    @property
    def title(self) -> str:
        return {
            "minimum_team_salary": "Minimum team salary",
            "salary_cap": "Salary cap",
            "luxury_tax": "Luxury tax line",
            "first_apron": "First apron",
            "second_apron": "Second apron",
        }[self.value]


class RulesStatus(StrEnum):
    PROJECTED = "projected"
    """A league projection for a future season; expect it to move."""
    FINAL = "final"
    """Set by the league for the season; does not change afterwards."""


class CapThresholds(_Rule):
    salary_cap: PositiveInt
    minimum_team_salary: PositiveInt
    luxury_tax: PositiveInt
    first_apron: PositiveInt
    second_apron: PositiveInt

    @model_validator(mode="after")
    def _ascending(self) -> CapThresholds:
        ladder = [(line, self.amount(line)) for line in PayrollLine]
        for (lower, low), (upper, high) in zip(ladder, ladder[1:], strict=False):
            if low >= high:
                raise ValueError(f"{lower.value} ({low:,}) must be below {upper.value} ({high:,})")
        return self

    def amount(self, line: PayrollLine) -> int:
        return int(getattr(self, line.value))


class SalaryExceptions(_Rule):
    non_taxpayer_mid_level: PositiveInt
    taxpayer_mid_level: PositiveInt
    room_mid_level: PositiveInt
    bi_annual: PositiveInt


class MaximumSalaries(_Rule):
    """Largest first-year salary a player may sign for, by years of NBA service."""

    service_0_to_6_years: PositiveInt
    service_7_to_9_years: PositiveInt
    service_10_plus_years: PositiveInt

    def for_years_of_service(self, years: int) -> int:
        if years < 0:
            raise ValueError("years of service cannot be negative")
        if years <= 6:
            return self.service_0_to_6_years
        if years <= 9:
            return self.service_7_to_9_years
        return self.service_10_plus_years


class RosterLimits(_Rule):
    max_standard_contracts: PositiveInt
    min_standard_contracts: PositiveInt
    max_two_way_contracts: PositiveInt
    offseason_max_players: PositiveInt

    @model_validator(mode="after")
    def _consistent(self) -> RosterLimits:
        if self.min_standard_contracts > self.max_standard_contracts:
            raise ValueError("min_standard_contracts exceeds max_standard_contracts")
        if self.offseason_max_players < self.max_standard_contracts:
            raise ValueError("offseason_max_players is below max_standard_contracts")
        return self


class SourceReference(_Rule):
    """Where a rule was verified, so every figure can be traced and re-checked."""

    publisher: str
    title: str
    url: str
    retrieved: date
    published: date | None = None
    covers: str | None = None

    @field_validator("url")
    @classmethod
    def _http(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError(f"source url must be http(s): {value!r}")
        return value


class SeasonRules(_Rule):
    """Everything season-specific that financial calculations depend on."""

    season: str
    status: RulesStatus
    thresholds: CapThresholds
    roster: RosterLimits
    sources: tuple[SourceReference, ...]
    exceptions: SalaryExceptions | None = None
    maximum_salaries: MaximumSalaries | None = None
    notes: str | None = None

    @field_validator("season")
    @classmethod
    def _season_label(cls, value: str) -> str:
        return Season.parse(value).label

    @field_validator("sources")
    @classmethod
    def _sourced(cls, value: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
        if not value:
            raise ValueError("season rules must cite at least one source")
        return value

    @property
    def season_id(self) -> Season:
        return Season.parse(self.season)

    @property
    def salary_cap(self) -> int:
        return self.thresholds.salary_cap

    @property
    def version(self) -> str:
        """A short fingerprint of the rules that affect calculations.

        Stored next to anything computed from these rules so a result can always say
        which figures produced it. Editing a source citation or a note does not change
        it; editing any amount or limit does.
        """
        figures = self.model_dump(mode="json", exclude={"sources", "notes"})
        canonical = json.dumps(figures, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def line(self, line: PayrollLine) -> int:
        """Dollar amount of one payroll threshold."""
        return self.thresholds.amount(line)

    def cap_share(self, salary: float) -> float:
        """A salary as a fraction of this season's cap.

        Cap-normalised salary is the unit for comparing contracts across seasons: $25M
        under a $100M cap is a very different commitment from $25M under a $165M cap.
        """
        return float(salary) / self.thresholds.salary_cap
