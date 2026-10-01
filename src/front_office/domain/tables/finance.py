"""Data contracts for the financial domain: cap rules and player salary agreements."""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract

_USD = "USD"


def _threshold(name: str, description: str) -> Field:
    return Field(name, DType.INTEGER, description, nullable=False, unit=_USD, minimum=1)


def _optional_amount(name: str, description: str) -> Field:
    return Field(name, DType.INTEGER, description, unit=_USD, minimum=1)


def _limit(name: str, description: str) -> Field:
    return Field(name, DType.INTEGER, description, nullable=False, unit="players", minimum=1)


SALARY_CAP_RULES = TableContract(
    name="salary_cap_rules",
    domain="cap_rules",
    description=(
        "Season-specific salary-cap thresholds, salary exceptions and roster limits, "
        "tabulated from configs/seasons so they can be joined to salaries."
    ),
    grain="One row per NBA season.",
    fields=(
        Field(
            "season",
            DType.STRING,
            "Season label, e.g. 2025-26.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        Field(
            "status",
            DType.STRING,
            "Whether the figures are a league projection or final for the season.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
            allowed=("projected", "final"),
        ),
        _threshold("minimum_team_salary", "Payroll floor: 90% of the salary cap."),
        _threshold("salary_cap", "Salary cap."),
        _threshold("luxury_tax", "Luxury tax line; payroll above it is taxed."),
        _threshold("first_apron", "First apron; exceeding it restricts signings and trades."),
        _threshold("second_apron", "Second apron; exceeding it adds the heaviest restrictions."),
        _optional_amount("non_taxpayer_mid_level", "Non-taxpayer mid-level exception."),
        _optional_amount("taxpayer_mid_level", "Taxpayer mid-level exception."),
        _optional_amount("room_mid_level", "Mid-level exception for teams with cap room."),
        _optional_amount("bi_annual", "Bi-annual exception."),
        _optional_amount(
            "max_salary_0_to_6_years", "Maximum first-year salary, 0-6 years of service."
        ),
        _optional_amount(
            "max_salary_7_to_9_years", "Maximum first-year salary, 7-9 years of service."
        ),
        _optional_amount(
            "max_salary_10_plus_years", "Maximum first-year salary, 10 or more years of service."
        ),
        _limit("max_standard_contracts", "Most standard contracts a team may carry in season."),
        _limit("min_standard_contracts", "Fewest standard contracts a team must generally carry."),
        _limit("max_two_way_contracts", "Most two-way contracts a team may carry."),
        _limit(
            "offseason_max_players", "Most players a team may have under contract in the offseason."
        ),
        Field(
            "source_urls",
            DType.STRING,
            "Where the figures were verified; one URL per line.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "rules_version",
            DType.STRING,
            "Fingerprint of the figures, recorded with anything computed from them.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
    ),
    primary_key=("season",),
    introduced_in="V0",
)

TABLES: tuple[TableContract, ...] = (SALARY_CAP_RULES,)
