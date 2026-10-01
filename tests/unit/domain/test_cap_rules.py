from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from front_office.domain.cap_rules import (
    CapThresholds,
    MaximumSalaries,
    PayrollLine,
    RosterLimits,
    RulesStatus,
    SeasonRules,
    SourceReference,
)

# Deliberately invented figures: the real ones live in configs/seasons.
THRESHOLDS = {
    "minimum_team_salary": 90,
    "salary_cap": 100,
    "luxury_tax": 120,
    "first_apron": 130,
    "second_apron": 140,
}
ROSTER = {
    "max_standard_contracts": 15,
    "min_standard_contracts": 14,
    "max_two_way_contracts": 3,
    "offseason_max_players": 21,
}
SOURCE = {
    "publisher": "Test",
    "title": "Invented",
    "url": "https://example.com/cap",
    "retrieved": date(2026, 10, 1),
}


def rules(**overrides: object) -> SeasonRules:
    document = {
        "season": "2025-26",
        "status": "final",
        "thresholds": THRESHOLDS,
        "roster": ROSTER,
        "sources": [SOURCE],
    }
    document.update(overrides)
    return SeasonRules.model_validate(document)


def test_lines_are_read_by_name() -> None:
    season_rules = rules()
    assert season_rules.salary_cap == 100
    assert [season_rules.line(line) for line in PayrollLine] == [90, 100, 120, 130, 140]
    assert season_rules.status is RulesStatus.FINAL
    assert season_rules.season_id.start_year == 2025


def test_payroll_lines_are_listed_from_lowest_to_highest() -> None:
    assert [line.value for line in PayrollLine] == [
        "minimum_team_salary",
        "salary_cap",
        "luxury_tax",
        "first_apron",
        "second_apron",
    ]
    assert PayrollLine.LUXURY_TAX.title == "Luxury tax line"


def test_cap_share_normalises_salary_by_the_cap() -> None:
    assert rules().cap_share(25) == pytest.approx(0.25)
    assert rules().cap_share(0) == 0.0


@pytest.mark.parametrize(
    "change",
    [
        {"minimum_team_salary": 100},  # floor equal to the cap
        {"luxury_tax": 99},  # tax line below the cap
        {"first_apron": 120},  # apron equal to the tax line
        {"second_apron": 125},  # second apron below the first
    ],
)
def test_thresholds_must_ascend(change: dict[str, int]) -> None:
    with pytest.raises(ValidationError, match="must be below"):
        CapThresholds.model_validate({**THRESHOLDS, **change})


@pytest.mark.parametrize("amount", [0, -5])
def test_thresholds_must_be_positive(amount: int) -> None:
    with pytest.raises(ValidationError):
        CapThresholds.model_validate({**THRESHOLDS, "salary_cap": amount})


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CapThresholds.model_validate({**THRESHOLDS, "third_apron": 150})
    with pytest.raises(ValidationError):
        rules(hard_cap=1)


def test_rules_are_immutable() -> None:
    with pytest.raises(ValidationError):
        rules().thresholds.salary_cap = 1  # type: ignore[misc]


def test_season_label_is_validated() -> None:
    with pytest.raises(ValidationError):
        rules(season="2025-27")


def test_rules_must_cite_a_source() -> None:
    with pytest.raises(ValidationError, match="at least one source"):
        rules(sources=[])


def test_source_urls_must_be_http() -> None:
    with pytest.raises(ValidationError):
        SourceReference.model_validate({**SOURCE, "url": "ftp://example.com"})


@pytest.mark.parametrize(
    "change",
    [
        {"min_standard_contracts": 16},
        {"offseason_max_players": 14},
    ],
)
def test_roster_limits_must_be_consistent(change: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        RosterLimits.model_validate({**ROSTER, **change})


@pytest.mark.parametrize(
    ("years", "expected"),
    [(0, 25), (6, 25), (7, 30), (9, 30), (10, 35), (19, 35)],
)
def test_maximum_salary_tiers(years: int, expected: int) -> None:
    tiers = MaximumSalaries(
        service_0_to_6_years=25, service_7_to_9_years=30, service_10_plus_years=35
    )
    assert tiers.for_years_of_service(years) == expected


def test_maximum_salary_rejects_negative_service() -> None:
    tiers = MaximumSalaries(
        service_0_to_6_years=25, service_7_to_9_years=30, service_10_plus_years=35
    )
    with pytest.raises(ValueError):
        tiers.for_years_of_service(-1)
