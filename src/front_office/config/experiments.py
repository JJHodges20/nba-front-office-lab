"""Load the rules for experiment proposals from ``configs/experiments.yaml`` (decision 0018,
A8): how the lab tests a change to each of its tested models."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.experiments import ExperimentRules

EXPERIMENTS_FILE = "experiments.yaml"


def experiment_rules_path(config_dir: Path) -> Path:
    return config_dir / EXPERIMENTS_FILE


def load_experiment_rules(config_dir: Path) -> ExperimentRules:
    """The rules for every tested model, in the order the file lists them."""
    path = experiment_rules_path(config_dir)
    try:
        return ExperimentRules.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid experiment rules in {path}:\n{error}") from error
