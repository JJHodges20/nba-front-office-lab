"""The registry of canonical tables.

Every table the lab stores is declared here as a :class:`TableContract`. Adding a table
means adding its contract to one of the domain modules and listing that module below;
storage, validation and the data dictionary pick it up from the registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from front_office.domain.schema import TableContract
from front_office.domain.tables import finance, operations, players, rosters, teams, value

# Built from the raw store; listed so that a table always follows the tables it references.
LEAGUE_TABLES: tuple[TableContract, ...] = (*teams.TABLES, *players.TABLES, *finance.TABLES)

# Computed from the league tables by a fitted model, in the same build.
MODELED_TABLES: tuple[TableContract, ...] = value.TABLES

# Dropped and rewritten by every build: the league data, what the models make of it, and
# the build's own report.
REBUILT_TABLES: tuple[TableContract, ...] = (
    *LEAGUE_TABLES,
    *MODELED_TABLES,
    *operations.BUILD_STATE_TABLES,
)

# Never dropped: the user's rosters and the history of fetches and builds.
KEPT_TABLES: tuple[TableContract, ...] = (*rosters.TABLES, *operations.HISTORY_TABLES)

ALL_TABLES: tuple[TableContract, ...] = (
    *LEAGUE_TABLES,
    *MODELED_TABLES,
    *rosters.TABLES,
    *operations.TABLES,
)

_BY_NAME = {contract.name: contract for contract in ALL_TABLES}
if len(_BY_NAME) != len(ALL_TABLES):
    raise RuntimeError("two table contracts share a name")


@dataclass(frozen=True, slots=True)
class PlannedTable:
    """A table the roadmap calls for whose contract has not been written yet."""

    name: str
    domain: str
    purpose: str
    milestone: int


# The roadmap's core database design (section 12). An entry is deleted from this list in
# the same commit that adds the table's contract.
PLANNED_TABLES: tuple[PlannedTable, ...] = (
    PlannedTable("player_archetypes", "player_value", "Role classification outputs.", 9),
    PlannedTable("lineups", "lineups", "Five-player lineup identities.", 10),
    PlannedTable("lineup_stats", "lineups", "Minutes and performance for lineups.", 10),
    PlannedTable("model_predictions", "modeling", "Versioned postseason probability outputs.", 12),
    PlannedTable("simulation_results", "simulation", "Scenario and Monte Carlo results.", 13),
)


def table(name: str) -> TableContract:
    """Look a contract up by table name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"no table contract named {name!r}; known: {sorted(_BY_NAME)}") from None


__all__ = ["ALL_TABLES", "PLANNED_TABLES", "PlannedTable", "table"]
