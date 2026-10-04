"""The archetype definitions in ``configs/archetypes.yaml``."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import archetypes_path, load_archetypes
from front_office.config.settings import ConfigError
from front_office.modeling.archetypes import check_definitions

ROADMAP_ROLES = (
    "Primary Creator",
    "Secondary Creator",
    "Floor Spacer",
    "Perimeter Defender",
    "Switchable Wing",
    "Rim Protector",
    "Stretch Big",
    "Connector",
)


class TestTheShippedDefinitions:
    def test_they_are_the_roadmaps_roles_in_its_order(self, repo_root: Path) -> None:
        shipped = load_archetypes(repo_root / "configs")
        assert tuple(archetype.name for archetype in shipped) == ROADMAP_ROLES
        assert (shipped.label, shipped.min_minutes, shipped.fills_at) == ("v1", 500, 67)

    def test_the_lab_can_compute_every_one(self, repo_root: Path) -> None:
        check_definitions(load_archetypes(repo_root / "configs"))

    def test_each_says_what_its_measures_stand_in_for(self, repo_root: Path) -> None:
        for archetype in load_archetypes(repo_root / "configs"):
            assert archetype.description.endswith(".") and archetype.note.endswith(".")

    def test_creators_come_in_two_tiers_that_do_not_overlap(self, repo_root: Path) -> None:
        shipped = load_archetypes(repo_root / "configs")
        primary, secondary = shipped["primary_creator"], shipped["secondary_creator"]
        assert primary.measures == secondary.measures
        assert shipped.cut(primary) == secondary.fills_below == 85
        assert shipped.cut(secondary) == shipped.fills_at


class TestLoading:
    def test_the_file_is_in_the_configuration_directory(self, project: Path) -> None:
        assert archetypes_path(project / "configs") == project / "configs" / "archetypes.yaml"
        assert archetypes_path(project / "configs").is_file()

    def test_a_missing_file_is_named(self, project: Path) -> None:
        archetypes_path(project / "configs").unlink()
        with pytest.raises(ConfigError, match=r"configuration file not found: .*archetypes\.yaml"):
            load_archetypes(project / "configs")

    def test_a_rule_that_does_not_hold_together_is_refused_with_the_file_named(
        self, project: Path
    ) -> None:
        path = archetypes_path(project / "configs")
        path.write_text(
            "version: 1\nmin_minutes: 500\nfills_at: 67\narchetypes:\n"
            "  - {key: role, name: Role, description: A role., measures: [usage_pct],"
            " fills_below: 50}\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError) as error:
            load_archetypes(project / "configs")
        assert "invalid archetypes in" in str(error.value) and str(path) in str(error.value)
        assert "fills_below (50) must be above fills_at (67)" in str(error.value)
