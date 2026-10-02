"""Config layer: settings, season rules and eras read from ``configs/``.

Depends only on the domain layer. This is the only place YAML is parsed.
"""

from front_office.config.eras import eras_path, load_eras
from front_office.config.season_rules import (
    SeasonRulesNotFound,
    configured_seasons,
    load_all_season_rules,
    load_season_rules,
)
from front_office.config.settings import (
    ConfigError,
    Settings,
    find_project_root,
    load_settings,
)

__all__ = [
    "ConfigError",
    "SeasonRulesNotFound",
    "Settings",
    "configured_seasons",
    "eras_path",
    "find_project_root",
    "load_all_season_rules",
    "load_eras",
    "load_season_rules",
    "load_settings",
]
