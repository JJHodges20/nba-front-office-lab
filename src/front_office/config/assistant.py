"""Load the AI research assistant's settings from ``configs/assistant.yaml``."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.assistant import AssistantSettings, OllamaConnection

ASSISTANT_FILE = "assistant.yaml"
OLLAMA_HOST_VARIABLE = "FOL_OLLAMA_HOST"
"""Where the model is, set from outside the file: Docker Compose sets it to its own Ollama
container, or to the computer's (decision 0019). Held to the same rule as the file's."""


def assistant_settings_path(config_dir: Path) -> Path:
    return config_dir / ASSISTANT_FILE


def load_assistant_settings(config_dir: Path) -> AssistantSettings:
    """The assistant's model and limits. An address off this machine, a cloud model or an
    unknown field (a key, say) is refused - from ``FOL_OLLAMA_HOST`` too."""
    path = assistant_settings_path(config_dir)
    try:
        settings = AssistantSettings.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid assistant settings in {path}:\n{error}") from error
    host = os.environ.get(OLLAMA_HOST_VARIABLE, "").strip()
    if not host:
        return settings
    try:
        connection = OllamaConnection.model_validate({**settings.ollama.model_dump(), "host": host})
    except ValidationError as error:
        raise ConfigError(f"invalid {OLLAMA_HOST_VARIABLE}:\n{error}") from error
    return settings.model_copy(update={"ollama": connection})
