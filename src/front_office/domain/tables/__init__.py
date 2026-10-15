"""The registry of canonical tables.

Every table the lab stores is declared here as a :class:`TableContract`. Adding a table
means adding its contract to one of the domain modules and listing that module below;
storage, validation and the data dictionary pick it up from the registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from front_office.domain.schema import TableContract
from front_office.domain.tables import (
    accounts,
    current,
    finance,
    fit,
    operations,
    players,
    research,
    rosters,
    teams,
    value,
)

# Built from the raw store; listed so that a table always follows the tables it references.
LEAGUE_TABLES: tuple[TableContract, ...] = (*teams.TABLES, *players.TABLES, *finance.TABLES)

# Computed from the league tables by a fitted model and the role rules, in the same build.
MODELED_TABLES: tuple[TableContract, ...] = (*value.TABLES, *fit.TABLES)

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

# Current information since the build, for the AI research assistant: kept in its own file,
# data/current.sqlite, never in the lab's database (decision 0018).
CURRENT_TABLES: tuple[TableContract, ...] = current.TABLES

# The user's research with the assistant - workspaces, questions and answers, findings,
# proposals and approvals: kept in its own file, data/assistant/assistant.sqlite, which no
# build touches (decision 0018, A6).
RESEARCH_TABLES: tuple[TableContract, ...] = research.TABLES

# The API's accounts - its users and the questions each one asked: kept in their own file,
# data/api/accounts.sqlite, which no build touches (decision 0019).
ACCOUNT_TABLES: tuple[TableContract, ...] = accounts.TABLES

# Every table the data dictionary describes: the lab's database, the current cache, the
# research store, then the API's accounts.
DOCUMENTED_TABLES: tuple[TableContract, ...] = (
    *ALL_TABLES,
    *CURRENT_TABLES,
    *RESEARCH_TABLES,
    *ACCOUNT_TABLES,
)
if len({contract.name for contract in DOCUMENTED_TABLES}) != len(DOCUMENTED_TABLES):
    raise RuntimeError("two table contracts share a name")


@dataclass(frozen=True, slots=True)
class PlannedTable:
    """A table the roadmap calls for whose contract has not been written yet."""

    name: str
    domain: str
    purpose: str
    milestone: int | None
    """The milestone that builds it, or ``None`` for a table deferred past the roadmap."""


# The roadmap's core database design (section 12). An entry is deleted from this list in
# the same commit that adds the table's contract, or in the decision that leaves it out:
# model_predictions (decision 0014: chances are computed on request from the model file)
# and simulation_results (decision 0015: a scenario is saved as a roster). Lineups were
# deferred past the roadmap's milestones.
PLANNED_TABLES: tuple[PlannedTable, ...] = (
    PlannedTable("lineups", "lineups", "Five-player lineup identities.", None),
    PlannedTable("lineup_stats", "lineups", "Minutes and performance for lineups.", None),
)


def table(name: str) -> TableContract:
    """Look a contract up by table name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"no table contract named {name!r}; known: {sorted(_BY_NAME)}") from None


__all__ = [
    "ACCOUNT_TABLES",
    "ALL_TABLES",
    "CURRENT_TABLES",
    "DOCUMENTED_TABLES",
    "PLANNED_TABLES",
    "RESEARCH_TABLES",
    "PlannedTable",
    "table",
]
