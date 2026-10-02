"""Load the eras for historical research from ``configs/eras.yaml``."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.eras import EraSet

ERAS_FILE = "eras.yaml"


def eras_path(config_dir: Path) -> Path:
    return config_dir / ERAS_FILE


def load_eras(config_dir: Path) -> EraSet:
    """The configured eras, in the order the file lists them."""
    path = eras_path(config_dir)
    try:
        return EraSet.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid eras in {path}:\n{error}") from error
