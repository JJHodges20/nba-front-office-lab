"""Load the AI research assistant's settings from ``configs/assistant.yaml``."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.assistant import AssistantSettings

ASSISTANT_FILE = "assistant.yaml"


def assistant_settings_path(config_dir: Path) -> Path:
    return config_dir / ASSISTANT_FILE


def load_assistant_settings(config_dir: Path) -> AssistantSettings:
    """The assistant's model and limits. An address off this machine, a cloud model or an
    unknown field (a key, say) is refused."""
    path = assistant_settings_path(config_dir)
    try:
        return AssistantSettings.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid assistant settings in {path}:\n{error}") from error
