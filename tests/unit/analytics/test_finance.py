from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from front_office.analytics.finance import cap_share, payroll_summary
from front_office.domain.cap_rules import PayrollLine, SeasonRules

# Invented, round thresholds: floor 90, cap 100, tax 120, aprons 130 and 140.
RULES = SeasonRules.model_validate(
    {
        "season": "2026-27",
        "status": "final",
        "thresholds": {
            "minimum_team_salary": 90,
            "salary_cap": 100,
            "luxury_tax": 120,
            "first_apron": 130,
            "second_apron": 140,
        },
        "roster": {
            "max_standard_contracts": 15,
            "min_standard_contracts": 14,
            "max_two_way_contracts": 3,
            "offseason_max_players": 21,
        },
        "sources": [
            {
                "publisher": "Test",
                "title": "Invented",
                "url": "https://example.com",
                "retrieved": date(2026, 10, 1),
            }
        ],
    }
)


def test_cap_share_of_a_salary_and_of_a_column() -> None:
    assert cap_share(25, 100) == 0.25
    shares = cap_share(pd.Series([10, 35]), 100)
    assert shares.tolist() == [0.10, 0.35]


def test_summary_measures_the_payroll_against_every_line() -> None:
    summary = payroll_summary(125, RULES)
    assert summary.season == "2026-27"
    assert summary.total == 125
    assert summary.cap_share == 1.25
    assert [(p.line, p.amount, p.room) for p in summary.positions] == [
        (PayrollLine.MINIMUM_TEAM_SALARY, 90, -35),
        (PayrollLine.SALARY_CAP, 100, -25),
        (PayrollLine.LUXURY_TAX, 120, -5),
        (PayrollLine.FIRST_APRON, 130, 5),
        (PayrollLine.SECOND_APRON, 140, 15),
    ]


@pytest.mark.parametrize(
    ("total", "exceeded"),
    [
        (50, None),
        (100, None),  # exactly at the cap is not over it
        (101, PayrollLine.SALARY_CAP),
        (120, PayrollLine.SALARY_CAP),
        (121, PayrollLine.LUXURY_TAX),
        (135, PayrollLine.FIRST_APRON),
        (500, PayrollLine.SECOND_APRON),
    ],
)
def test_highest_line_exceeded(total: int, exceeded: PayrollLine | None) -> None:
    assert payroll_summary(total, RULES).highest_line_exceeded is exceeded


@pytest.mark.parametrize(("total", "below"), [(0, True), (89, True), (90, False), (150, False)])
def test_below_the_minimum_team_salary(total: int, below: bool) -> None:
    assert payroll_summary(total, RULES).is_below_minimum is below


def test_room_under_a_line() -> None:
    summary = payroll_summary(95, RULES)
    assert summary.position(PayrollLine.SALARY_CAP).room == 5
    assert not summary.position(PayrollLine.SALARY_CAP).is_over
    assert summary.position(PayrollLine.MINIMUM_TEAM_SALARY).is_over


def test_fractional_totals_are_rounded_to_whole_dollars() -> None:
    assert payroll_summary(99.6, RULES).total == 100


def test_with_the_shipped_2026_27_rules(season_rules) -> None:
    rules = next(r for r in season_rules if r.season == "2026-27")
    summary = payroll_summary(rules.line(PayrollLine.LUXURY_TAX) + 1, rules)
    assert summary.highest_line_exceeded is PayrollLine.LUXURY_TAX
    assert summary.position(PayrollLine.FIRST_APRON).room == (
        rules.line(PayrollLine.FIRST_APRON) - rules.line(PayrollLine.LUXURY_TAX) - 1
    )
