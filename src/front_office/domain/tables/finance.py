"""Data contracts for the financial domain: cap rules and player salary agreements."""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import _fields as f

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

CONTRACT_TYPES = ("standard", "two_way")
CONTRACT_STATUSES = ("active", "dead_money")
OPTION_TYPES = ("player", "team", "early_termination")
GUARANTEE_LEVELS = ("full", "partial", "none")

CONTRACTS = TableContract(
    name="contracts",
    domain="contracts",
    description=(
        "Player salary agreements as supplied in an imported contract file: one row for "
        "each run of consecutive seasons a team owes a player."
    ),
    grain="One row per player per team per run of consecutive seasons.",
    fields=(
        f.label(
            "contract_id", "Key built from player, team, first season and status.", nullable=False
        ),
        f.player_id(),
        f.team_id(
            description="Team that owes the salary. Null if the file gave no team.", nullable=True
        ),
        f.label("player_name", "Player name as written in the contract file.", nullable=False),
        f.label(
            "contract_type",
            "Standard contracts count against the roster limit of fifteen; two-way contracts "
            "have their own limit and do not count against the cap.",
            nullable=False,
            allowed=CONTRACT_TYPES,
        ),
        f.label(
            "status",
            "Active: the player is under contract. Dead money: salary still owed to a "
            "player who was waived.",
            nullable=False,
            allowed=CONTRACT_STATUSES,
        ),
        f.label("first_season", "First season the file lists salary for.", nullable=False),
        f.label("last_season", "Last season the file lists salary for.", nullable=False),
        f.count("seasons", "Number of seasons listed.", unit="seasons"),
        Field(
            "total_salary",
            DType.INTEGER,
            "Sum of the listed seasons' salaries.",
            nullable=False,
            provenance=Provenance.DERIVED,
            unit=_USD,
            minimum=0,
        ),
        Field(
            "guaranteed_amount",
            DType.INTEGER,
            "Total guaranteed money, as the file states it. Null if not stated.",
            unit=_USD,
            minimum=0,
        ),
        Field(
            "source_label",
            DType.STRING,
            "Where the person who supplied the file got the figures.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
        Field(
            "as_of_date",
            DType.DATE,
            "Date the figures were current, as stated at import.",
            nullable=False,
            provenance=Provenance.OPERATIONAL,
        ),
    ),
    primary_key=("contract_id",),
    indexes=(("player_id",), ("team_id",)),
)

CONTRACT_YEARS = TableContract(
    name="contract_years",
    domain="contracts",
    description="Salary for each season of each contract, with its share of that season's cap.",
    grain="One row per contract per season.",
    fields=(
        f.label(
            "contract_id",
            "The contract this season belongs to.",
            nullable=False,
            references="contracts.contract_id",
        ),
        f.season(),
        f.player_id(),
        f.team_id(description="Team that owes the salary.", nullable=True),
        Field(
            "salary", DType.INTEGER, "Salary for the season.", nullable=False, unit=_USD, minimum=0
        ),
        Field(
            "salary_cap_pct",
            DType.FLOAT,
            "Salary as a fraction of that season's cap. Null when the season's cap is not "
            "configured, as for future seasons the league has not set.",
            provenance=Provenance.DERIVED,
            unit="fraction",
            minimum=0,
        ),
        f.label("option", "Option attached to the season, if any.", allowed=OPTION_TYPES),
        f.label(
            "guarantee",
            "How much of the season's salary is guaranteed. Null if the file does not say.",
            allowed=GUARANTEE_LEVELS,
        ),
        Field(
            "years_remaining",
            DType.INTEGER,
            "Seasons left on the contract after this one.",
            nullable=False,
            provenance=Provenance.DERIVED,
            unit="seasons",
            minimum=0,
        ),
    ),
    primary_key=("contract_id", "season"),
    indexes=(("season", "team_id"), ("player_id", "season")),
)

TABLES: tuple[TableContract, ...] = (SALARY_CAP_RULES, CONTRACTS, CONTRACT_YEARS)
