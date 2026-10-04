"""Load the archetype definitions from ``configs/archetypes.yaml``."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.archetypes import ArchetypeSet

ARCHETYPES_FILE = "archetypes.yaml"


def archetypes_path(config_dir: Path) -> Path:
    return config_dir / ARCHETYPES_FILE


def load_archetypes(config_dir: Path) -> ArchetypeSet:
    """The configured archetypes, in the order the file lists them."""
    path = archetypes_path(config_dir)
    try:
        return ArchetypeSet.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid archetypes in {path}:\n{error}") from error
