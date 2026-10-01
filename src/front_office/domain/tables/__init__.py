"""The registry of canonical tables.

Every table the lab stores is declared here as a :class:`TableContract`. Adding a table
means adding its contract to one of the domain modules and listing that module below;
storage, validation and the data dictionary pick it up from the registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from front_office.domain.schema import TableContract
from front_office.domain.tables import finance

ALL_TABLES: tuple[TableContract, ...] = (*finance.TABLES,)

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
    PlannedTable("players", "players", "Stable player identity and profile fields.", 2),
    PlannedTable(
        "player_seasons",
        "player_performance",
        "Season-level player statistics and advanced metrics.",
        2,
    ),
    PlannedTable(
        "player_game_logs", "player_performance", "Game-level performance and availability.", 2
    ),
    PlannedTable("teams", "teams", "Stable team identity.", 2),
    PlannedTable("team_seasons", "teams", "Season-level team performance and outcomes.", 2),
    PlannedTable("team_games", "teams", "Game-level team results.", 2),
    PlannedTable("team_rosters", "players", "Player membership by team and season.", 2),
    PlannedTable("playoff_results", "historical_outcomes", "Series and postseason advancement.", 2),
    PlannedTable(
        "contracts", "contracts", "Contract-level metadata, guarantees, options, start/end.", 3
    ),
    PlannedTable("contract_years", "contracts", "Salary by season and cap percentage.", 3),
    PlannedTable("custom_rosters", "user_rosters", "User-created roster scenarios.", 4),
    PlannedTable("roster_players", "user_rosters", "Members of each custom roster.", 4),
    PlannedTable("player_archetypes", "player_value", "Role classification outputs.", 9),
    PlannedTable("player_value_scores", "player_value", "Versioned player value calculations.", 9),
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
