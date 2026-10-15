"""Config layer: settings, season rules, eras, archetypes and models read from ``configs/``,
and the lab's own documents from ``docs/``.

Depends only on the domain layer. This is the only place YAML is parsed.
"""

from front_office.config.api import api_settings_path, load_api_settings
from front_office.config.archetypes import archetypes_path, load_archetypes
from front_office.config.assistant import assistant_settings_path, load_assistant_settings
from front_office.config.documents import documents_path, load_sections
from front_office.config.eras import eras_path, load_eras
from front_office.config.experiments import experiment_rules_path, load_experiment_rules
from front_office.config.models import (
    fit_evidence_path,
    fit_spec_path,
    load_fit_evidence,
    load_fit_spec,
    load_postseason_model,
    load_postseason_spec,
    load_simulator_model,
    load_simulator_spec,
    load_value_model,
    load_value_spec,
    postseason_model_path,
    postseason_spec_path,
    save_fit_evidence,
    save_postseason_model,
    save_simulator_model,
    save_value_model,
    simulator_model_path,
    simulator_spec_path,
    value_model_path,
    value_spec_path,
)
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
    "api_settings_path",
    "archetypes_path",
    "assistant_settings_path",
    "configured_seasons",
    "documents_path",
    "eras_path",
    "experiment_rules_path",
    "find_project_root",
    "load_all_season_rules",
    "load_api_settings",
    "load_archetypes",
    "load_assistant_settings",
    "fit_evidence_path",
    "fit_spec_path",
    "load_fit_evidence",
    "load_fit_spec",
    "load_postseason_model",
    "load_postseason_spec",
    "load_sections",
    "load_simulator_model",
    "load_simulator_spec",
    "postseason_model_path",
    "postseason_spec_path",
    "save_fit_evidence",
    "save_postseason_model",
    "save_simulator_model",
    "simulator_model_path",
    "simulator_spec_path",
    "load_eras",
    "load_experiment_rules",
    "load_season_rules",
    "load_settings",
    "load_value_model",
    "load_value_spec",
    "save_value_model",
    "value_model_path",
    "value_spec_path",
]
