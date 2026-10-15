"""Load the HTTP API's settings from ``configs/api.yaml`` (decision 0019)."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.api_settings import ApiSettings

API_FILE = "api.yaml"


def api_settings_path(config_dir: Path) -> Path:
    return config_dir / API_FILE


def load_api_settings(config_dir: Path) -> ApiSettings:
    """How long a sign-in lasts and how costly a password is to check. An unknown field -
    a key, say - is refused."""
    path = api_settings_path(config_dir)
    try:
        return ApiSettings.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid API settings in {path}:\n{error}") from error
