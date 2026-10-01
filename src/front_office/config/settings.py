"""Application settings, loaded from ``configs/base.yaml``.

Settings answer "where do things live and how much history do we keep". Anything that
varies by NBA season belongs in ``configs/seasons`` instead.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, PositiveInt, ValidationError, field_validator

from front_office.domain.seasons import Season

ENV_HOME = "FOL_HOME"
ENV_DATA_DIR = "FOL_DATA_DIR"

_BASE_CONFIG = Path("configs") / "base.yaml"


class ConfigError(RuntimeError):
    """Configuration is missing or invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PathSettings(_Section):
    data_dir: str = "data"


class SeasonSettings(_Section):
    history_start: str = "1996-97"
    player_detail_seasons: PositiveInt = 3

    @field_validator("history_start")
    @classmethod
    def _season_label(cls, value: str) -> str:
        return Season.parse(value).label


class _BaseFile(_Section):
    paths: PathSettings = PathSettings()
    seasons: SeasonSettings = SeasonSettings()


class Settings(_Section):
    """Resolved settings: every path is absolute."""

    project_root: Path
    config_dir: Path
    data_dir: Path
    seasons: SeasonSettings

    @property
    def season_rules_dir(self) -> Path:
        return self.config_dir / "seasons"

    @property
    def raw_dir(self) -> Path:
        """Immutable snapshots of what each provider returned."""
        return self.data_dir / "raw"

    @property
    def imports_dir(self) -> Path:
        """Files the user supplies by hand, such as contract exports."""
        return self.data_dir / "imports"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "front_office.sqlite"

    @property
    def history_start(self) -> Season:
        return Season.parse(self.seasons.history_start)


def find_project_root(start: Path | None = None) -> Path:
    """Locate the project root: the directory that holds ``configs/base.yaml``.

    Resolution order: the ``FOL_HOME`` environment variable, the nearest ancestor of
    ``start`` (default: the working directory), then the source checkout this package
    was imported from.
    """
    home = os.environ.get(ENV_HOME)
    if home:
        root = Path(home).expanduser().resolve()
        if not (root / _BASE_CONFIG).is_file():
            raise ConfigError(f"{ENV_HOME}={home!r} does not contain {_BASE_CONFIG.as_posix()}")
        return root

    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / _BASE_CONFIG).is_file():
            return candidate

    checkout = Path(__file__).resolve().parents[3]
    if (checkout / _BASE_CONFIG).is_file():
        return checkout

    raise ConfigError(
        f"could not find {_BASE_CONFIG.as_posix()} from {origin}; "
        f"run from the project directory or set {ENV_HOME}"
    )


def load_settings(project_root: Path | None = None) -> Settings:
    """Read ``configs/base.yaml`` and resolve paths against the project root."""
    root = (project_root or find_project_root()).resolve()
    config_dir = root / "configs"
    document = read_yaml(config_dir / "base.yaml")
    try:
        base = _BaseFile.model_validate(document)
    except ValidationError as error:
        raise ConfigError(f"invalid {config_dir / 'base.yaml'}:\n{error}") from error

    data_dir = Path(os.environ.get(ENV_DATA_DIR) or base.paths.data_dir).expanduser()
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return Settings(
        project_root=root,
        config_dir=config_dir,
        data_dir=data_dir.resolve(),
        seasons=base.seasons,
    )


def read_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML mapping, with errors that name the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(f"configuration file not found: {path}") from error
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{path} is not valid YAML: {error}") from error
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return document
