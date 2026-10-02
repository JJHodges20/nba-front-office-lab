from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from front_office.analytics.finance import (
    TEAM_PAYROLL_COLUMNS,
    SeasonSalaries,
    cap_share,
    payroll_positions,
    payroll_summary,
    season_salaries,
    team_payrolls,
)
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


def owed(team: int | None, salary: int, *, status: str = "active", kind: str = "standard") -> dict:
    return {"team_id": team, "salary": salary, "status": status, "contract_type": kind}


class TestTeamPayrolls:
    def test_standard_contracts_and_dead_money_count_two_way_contracts_do_not(self) -> None:
        years = pd.DataFrame(
            [
                owed(1, 60),
                owed(1, 40),
                owed(1, 5, status="dead_money"),
                owed(1, 1, kind="two_way"),
                owed(2, 30),
            ]
        )
        payrolls = team_payrolls(years)
        assert payrolls.index.tolist() == [1, 2] and payrolls.index.name == "team_id"
        assert list(payrolls.columns) == list(TEAM_PAYROLL_COLUMNS)
        first = payrolls.loc[1]
        assert (first["active_salary"], first["dead_money"], first["two_way_salary"]) == (100, 5, 1)
        assert first["team_salary"] == 105
        assert (first["standard_contracts"], first["two_way_contracts"]) == (2, 1)
        assert payrolls.loc[2, "team_salary"] == 30

    def test_a_waived_player_is_not_counted_as_under_contract(self) -> None:
        years = pd.DataFrame([owed(1, 5, status="dead_money"), owed(1, 2, status="dead_money")])
        payroll = team_payrolls(years).loc[1]
        assert (payroll["team_salary"], payroll["dead_money"]) == (7, 7)
        assert (payroll["standard_contracts"], payroll["two_way_contracts"]) == (0, 0)

    def test_dead_money_on_a_two_way_contract_stays_outside_team_salary(self) -> None:
        years = pd.DataFrame([owed(1, 3, status="dead_money", kind="two_way"), owed(1, 50)])
        payroll = team_payrolls(years).loc[1]
        assert (payroll["team_salary"], payroll["two_way_salary"]) == (50, 3)
        assert payroll["two_way_contracts"] == 0

    def test_a_salary_without_a_team_is_left_out(self) -> None:
        years = pd.DataFrame([owed(None, 12), owed(1, 50)])
        payrolls = team_payrolls(years)
        assert payrolls.index.tolist() == [1]
        assert payrolls["team_salary"].sum() == 50

    def test_no_salaries(self) -> None:
        empty = team_payrolls(pd.DataFrame([owed(1, 5)]).iloc[0:0])
        assert len(empty) == 0 and list(empty.columns) == list(TEAM_PAYROLL_COLUMNS)
        nobody = team_payrolls(pd.DataFrame([owed(None, 5)]))
        assert len(nobody) == 0


class TestPayrollPositions:
    def test_each_payroll_against_every_line(self) -> None:
        payrolls = pd.Series([85, 100, 125, 150], index=pd.Index([10, 20, 30, 40], name="team_id"))
        positions = payroll_positions(payrolls, RULES)
        assert positions.index.equals(payrolls.index)
        assert positions["cap_share"].tolist() == [0.85, 1.0, 1.25, 1.5]
        assert positions["room_salary_cap"].tolist() == [15, 0, -25, -50]
        assert positions["room_second_apron"].tolist() == [55, 40, 15, -10]
        assert positions["is_below_minimum"].tolist() == [True, False, False, False]

    def test_the_highest_line_exceeded_is_named_or_missing(self) -> None:
        positions = payroll_positions(pd.Series([85, 100, 125, 150]), RULES)
        exceeded = positions["highest_line_exceeded"]
        assert exceeded.isna().tolist() == [True, True, False, False]
        assert exceeded.tolist()[2:] == ["luxury_tax", "second_apron"]

    def test_a_column_for_every_line(self) -> None:
        positions = payroll_positions(pd.Series([100]), RULES)
        assert [c for c in positions.columns if c.startswith("room_")] == [
            f"room_{line.value}" for line in PayrollLine
        ]

    def test_no_payrolls(self) -> None:
        positions = payroll_positions(pd.Series([], dtype="int64"), RULES)
        assert len(positions) == 0 and "cap_share" in positions.columns


class TestSeasonSalaries:
    def frame(self) -> pd.DataFrame:
        rows = [
            owed(1, 60) | {"player_id": 11},
            owed(1, 5, status="dead_money") | {"player_id": 12},
            owed(2, 1, kind="two_way") | {"player_id": 13},
            owed(2, 3, status="dead_money", kind="two_way") | {"player_id": 12},
            owed(None, 12) | {"player_id": 14},
        ]
        return pd.DataFrame(rows)

    def test_counts_and_totals(self) -> None:
        summary = season_salaries(self.frame())
        assert (summary.contracts, summary.players, summary.teams) == (5, 4, 2)
        assert summary.total_salary == 81
        assert summary.dead_money == 8
        assert summary.two_way_salary == 4
        assert summary.unassigned == 1

    def test_no_salaries(self) -> None:
        summary = season_salaries(self.frame().iloc[0:0])
        assert summary == SeasonSalaries(0, 0, 0, 0, 0, 0, 0)
