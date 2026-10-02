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


TEAM_PAYROLL_COLUMNS = (
    "team_salary",
    "active_salary",
    "dead_money",
    "two_way_salary",
    "standard_contracts",
    "two_way_contracts",
)


def team_payrolls(contract_years: pd.DataFrame) -> pd.DataFrame:
    """Each team's payroll for one season, from the salaries it owes.

    ``contract_years`` is narrowed to one season and carries each contract's ``status``
    and ``contract_type``. Indexed by ``team_id``:

    - ``team_salary``: what counts against the cap. Standard contracts and dead money
      count; two-way contracts do not.
    - ``active_salary`` and ``dead_money``: its two parts.
    - ``two_way_salary``: owed on two-way contracts, outside team salary.
    - ``standard_contracts`` and ``two_way_contracts``: players under each kind of
      active contract.

    Salaries with no team cannot be assigned and are left out.
    """
    owed = contract_years[contract_years["team_id"].notna()]
    if owed.empty:
        empty = pd.Index([], name="team_id", dtype="int64")
        return pd.DataFrame(columns=list(TEAM_PAYROLL_COLUMNS), index=empty, dtype="int64")

    salary = owed["salary"].astype("int64")
    is_two_way = owed["contract_type"] == "two_way"
    is_active = owed["status"] == "active"
    parts = pd.DataFrame(
        {
            "team_id": owed["team_id"].astype("int64"),
            "active_salary": salary.where(is_active & ~is_two_way, 0),
            "dead_money": salary.where(~is_active & ~is_two_way, 0),
            "two_way_salary": salary.where(is_two_way, 0),
            "standard_contracts": (is_active & ~is_two_way).astype("int64"),
            "two_way_contracts": (is_active & is_two_way).astype("int64"),
        }
    )
    payrolls = parts.groupby("team_id").sum()
    payrolls["team_salary"] = payrolls["active_salary"] + payrolls["dead_money"]
    return payrolls[list(TEAM_PAYROLL_COLUMNS)]


@dataclass(frozen=True, slots=True)
class SeasonSalaries:
    """What a season's contract data adds up to."""

    contracts: int
    players: int
    teams: int
    """Teams that owe at least one salary."""
    total_salary: int
    """Every salary owed, of every kind."""
    dead_money: int
    two_way_salary: int
    unassigned: int
    """Salaries the contract file attached to no team."""


def season_salaries(contract_years: pd.DataFrame) -> SeasonSalaries:
    """Totals over one season's salaries.

    ``contract_years`` is narrowed to one season and carries each contract's ``status``
    and ``contract_type``.
    """
    salary = contract_years["salary"].astype("int64")
    is_dead = contract_years["status"] != "active"
    is_two_way = contract_years["contract_type"] == "two_way"
    return SeasonSalaries(
        contracts=len(contract_years),
        players=int(contract_years["player_id"].nunique()),
        teams=int(contract_years["team_id"].nunique()),
        total_salary=int(salary.sum()),
        dead_money=int(salary[is_dead].sum()),
        two_way_salary=int(salary[is_two_way].sum()),
        unassigned=int(contract_years["team_id"].isna().sum()),
    )


def payroll_positions(team_salary: pd.Series, rules: SeasonRules) -> pd.DataFrame:
    """Where each payroll of a series stands against a season's thresholds.

    Same index as ``team_salary``: ``cap_share``, then ``room_<line>`` for every
    :class:`PayrollLine` (dollars below the line, negative when over it), then
    ``highest_line_exceeded`` (the line's name, missing when under them all) and
    ``is_below_minimum``.
    """
    summaries = [payroll_summary(total, rules) for total in team_salary]
    positions = pd.DataFrame(index=team_salary.index)
    positions["cap_share"] = [summary.cap_share for summary in summaries]
    for line in PayrollLine:
        positions[f"room_{line.value}"] = [summary.position(line).room for summary in summaries]
    exceeded = [summary.highest_line_exceeded for summary in summaries]
    positions["highest_line_exceeded"] = pd.Series(
        [None if line is None else line.value for line in exceeded],
        index=team_salary.index,
        dtype="str",
    )
    positions["is_below_minimum"] = [summary.is_below_minimum for summary in summaries]
    return positions
