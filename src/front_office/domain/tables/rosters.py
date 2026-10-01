"""Data contracts for rosters the user builds.

Everything here is the user's own work. Unlike the tables built from league data, these
are never rebuilt: a roster survives every refresh of the data underneath it.
"""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import _fields as f

ROSTER_SLOTS = ("PG", "SG", "SF", "PF", "C", "BENCH")
STARTING_SLOTS = ROSTER_SLOTS[:5]


def _moment(name: str, description: str) -> Field:
    return Field(
        name, DType.DATETIME, description, nullable=False, provenance=Provenance.OPERATIONAL
    )


CUSTOM_ROSTERS = TableContract(
    name="custom_rosters",
    domain="user_rosters",
    description="Rosters assembled by the user in the Team Builder.",
    grain="One row per roster.",
    fields=(
        Field(
            "roster_id",
            DType.INTEGER,
            "Roster id, assigned when the roster is created.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        Field(
            "name",
            DType.STRING,
            "Name the user gave the roster.",
            nullable=False,
            provenance=Provenance.ASSUMPTION,
        ),
        Field(
            "stats_season",
            DType.STRING,
            "Season whose statistics describe the players.",
            nullable=False,
            provenance=Provenance.ASSUMPTION,
        ),
        Field(
            "payroll_season",
            DType.STRING,
            "Season whose salaries and cap the roster is priced against.",
            nullable=False,
            provenance=Provenance.ASSUMPTION,
        ),
        Field("notes", DType.STRING, "The user's notes.", provenance=Provenance.ASSUMPTION),
        _moment("created_at", "When the roster was created."),
        _moment("updated_at", "When the roster or its players last changed."),
    ),
    primary_key=("roster_id",),
)

ROSTER_PLAYERS = TableContract(
    name="roster_players",
    domain="user_rosters",
    description="The players on each user-built roster.",
    grain="One row per player per roster.",
    fields=(
        Field(
            "roster_id",
            DType.INTEGER,
            "The roster.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
            references="custom_rosters.roster_id",
        ),
        f.player_id(),
        Field(
            "slot",
            DType.STRING,
            "Where the user placed the player: a starting position or the bench.",
            nullable=False,
            provenance=Provenance.ASSUMPTION,
            allowed=ROSTER_SLOTS,
        ),
        Field(
            "assumed_salary",
            DType.INTEGER,
            "A salary the user entered for this player, used in place of contract data. "
            "Null means use the contract data.",
            provenance=Provenance.ASSUMPTION,
            unit="USD",
            minimum=0,
        ),
        _moment("added_at", "When the player was added."),
    ),
    primary_key=("roster_id", "player_id"),
    indexes=(("player_id",),),
)

TABLES: tuple[TableContract, ...] = (CUSTOM_ROSTERS, ROSTER_PLAYERS)
