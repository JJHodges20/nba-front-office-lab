"""Payroll arithmetic: salaries measured against a season's cap.

Cap figures arrive as a :class:`SeasonRules`; none is written here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from front_office.analytics import formulas as f
from front_office.domain.cap_rules import PayrollLine, SeasonRules


def cap_share(salary: float | pd.Series, salary_cap: float) -> float | pd.Series:
    """A salary as a fraction of the cap: the unit for comparing contracts across seasons."""
    return f.share(salary, salary_cap)


@dataclass(frozen=True, slots=True)
class LinePosition:
    """Where a payroll stands against one threshold."""

    line: PayrollLine
    amount: int
    room: int
    """Dollars below the line; negative when the payroll is over it."""

    @property
    def is_over(self) -> bool:
        return self.room < 0


@dataclass(frozen=True, slots=True)
class PayrollSummary:
    season: str
    total: int
    cap_share: float
    positions: tuple[LinePosition, ...]

    def position(self, line: PayrollLine) -> LinePosition:
        return next(position for position in self.positions if position.line is line)

    @property
    def highest_line_exceeded(self) -> PayrollLine | None:
        """The highest threshold the payroll is over, or ``None`` if it is under them all.

        The minimum team salary is a floor, not a ceiling, so it is never "exceeded" in
        this sense; see :attr:`is_below_minimum`.
        """
        ceilings = [p for p in self.positions if p.line is not PayrollLine.MINIMUM_TEAM_SALARY]
        over = [position.line for position in ceilings if position.is_over]
        return over[-1] if over else None

    @property
    def is_below_minimum(self) -> bool:
        """Whether the payroll is short of the minimum team salary."""
        return self.position(PayrollLine.MINIMUM_TEAM_SALARY).room > 0


def payroll_summary(total_salary: float, rules: SeasonRules) -> PayrollSummary:
    """A payroll total measured against every threshold of a season."""
    total = round(total_salary)
    positions = tuple(
        LinePosition(line, rules.line(line), rules.line(line) - total) for line in PayrollLine
    )
    return PayrollSummary(rules.season, total, rules.cap_share(total), positions)
