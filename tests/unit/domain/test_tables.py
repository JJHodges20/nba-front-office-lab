from __future__ import annotations

from pathlib import Path

import pytest

from front_office.domain.dictionary import _PROVENANCE_MEANING, render_data_dictionary
from front_office.domain.schema import Provenance
from front_office.domain.tables import ALL_TABLES, DOCUMENTED_TABLES, PLANNED_TABLES, table

# Tables the roadmap's "Core Database Design" section calls for.
ROADMAP_TABLES = {
    "players",
    "player_seasons",
    "player_game_logs",
    "teams",
    "team_seasons",
    "team_games",
    "team_rosters",
    "contracts",
    "contract_years",
    "salary_cap_rules",
    "lineups",
    "lineup_stats",
    "playoff_results",
    "player_archetypes",
    "player_value_scores",
    "custom_rosters",
    "roster_players",
    "model_predictions",
    "simulation_results",
}


def test_table_names_are_unique() -> None:
    names = [contract.name for contract in ALL_TABLES]
    assert len(names) == len(set(names))


def test_lookup_by_name() -> None:
    assert table("salary_cap_rules").primary_key == ("season",)
    with pytest.raises(KeyError, match="no table contract named"):
        table("nope")


def test_every_roadmap_table_is_either_declared_or_planned() -> None:
    declared = {contract.name for contract in ALL_TABLES}
    planned = {entry.name for entry in PLANNED_TABLES}
    assert not declared & planned, "a declared table is still listed as planned"
    # Two of the roadmap's tables were decided against: chances are computed on request
    # (decision 0014) and a scenario is kept as a roster (decision 0015).
    decided_against = {"model_predictions", "simulation_results"}
    assert ROADMAP_TABLES <= declared | planned | decided_against


def test_planned_tables_name_a_real_milestone() -> None:
    # A table deferred past the roadmap has no milestone; the rest name one of the fourteen.
    assert all(entry.milestone is None or 1 <= entry.milestone <= 14 for entry in PLANNED_TABLES)


def test_references_point_at_declared_columns() -> None:
    declared = {contract.name: contract for contract in ALL_TABLES}
    for contract in ALL_TABLES:
        for field in contract.fields:
            if field.references is None:
                continue
            target_table, target_column = field.references.split(".")
            assert target_table in declared, f"{contract.name}.{field.name} -> {field.references}"
            assert target_column in declared[target_table].column_names


def test_every_provenance_is_explained_in_the_dictionary() -> None:
    assert set(_PROVENANCE_MEANING) == set(Provenance)


def test_dictionary_lists_every_table_and_column() -> None:
    document = render_data_dictionary(DOCUMENTED_TABLES, PLANNED_TABLES)
    for contract in DOCUMENTED_TABLES:
        assert f"### {contract.name}" in document
        for field in contract.fields:
            assert f"| `{field.name}` |" in document
    for entry in PLANNED_TABLES:
        assert f"| `{entry.name}` |" in document


def test_committed_dictionary_matches_the_registry(repo_root: Path) -> None:
    """docs/DATA_DICTIONARY.md is generated; regenerate it with `fol dictionary --write`."""
    committed = (repo_root / "docs" / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert committed == render_data_dictionary(DOCUMENTED_TABLES, PLANNED_TABLES)
