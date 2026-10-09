"""What the workbench may call: the one module of the assistant it imports (decision 0018).

So far: whether the assistant can answer, and if not, what to do about it. Ollama not
running, or the model not pulled, is a message on the page, never an error: the rest of
the lab works without the assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from front_office.config import ConfigError, load_assistant_settings, load_settings
from front_office.providers.ollama import (
    ModelNotAvailable,
    NotLocal,
    OllamaError,
    OllamaProvider,
    OllamaUnavailable,
)

STATUS_TIMEOUT_SECONDS = 5.0


class AssistantState(StrEnum):
    READY = "ready"
    OFFLINE = "offline"
    """Ollama is not running or not answering."""
    NO_MODEL = "no_model"
    """Ollama runs, but neither configured model is on this machine and able to use tools."""
    MISCONFIGURED = "misconfigured"


@dataclass(frozen=True, slots=True)
class AssistantStatus:
    state: AssistantState
    message: str
    """What the reader is told: where things stand and what to do."""
    model: str | None = None
    """The model that will answer, when one can."""
    ollama_version: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.state is AssistantState.READY


def status(
    project_root: Path | None = None, *, provider: OllamaProvider | None = None
) -> AssistantStatus:
    """Whether the assistant can answer, checked against the running Ollama."""
    try:
        settings = load_assistant_settings(load_settings(project_root).config_dir)
    except ConfigError as error:
        return AssistantStatus(AssistantState.MISCONFIGURED, f"The assistant's settings: {error}")
    host = settings.ollama.host
    try:
        provider = provider or OllamaProvider(host, timeout=STATUS_TIMEOUT_SECONDS)
        version = provider.version()
    except (OllamaUnavailable, NotLocal):
        return AssistantStatus(
            AssistantState.OFFLINE,
            f"Ollama is not running at {host}. Start the Ollama app (or run: ollama serve), "
            "then reload. Everything else in the lab works without it.",
        )
    except OllamaError as error:
        return AssistantStatus(AssistantState.OFFLINE, f"Ollama answered with an error: {error}")

    default, fallback = settings.default_model, settings.fallback_model
    for model in filter(None, (default, fallback)):
        try:
            provider.require_local(model)
            if not provider.details(model).can_call_tools:
                continue
        except (ModelNotAvailable, NotLocal):
            continue
        note = (
            "" if model == default else f" ({default} is not on this machine; using the fallback)"
        )
        return AssistantStatus(
            AssistantState.READY, f"Ready: {model} on Ollama {version}{note}.", model, version
        )
    return AssistantStatus(
        AssistantState.NO_MODEL,
        f"Ollama {version} is running, but {default} is not on this machine. "
        f"Run: ollama pull {default}",
        None,
        version,
    )
