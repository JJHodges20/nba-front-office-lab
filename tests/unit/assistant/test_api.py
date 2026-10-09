from __future__ import annotations

from pathlib import Path

from front_office.assistant.api import AssistantState, status
from front_office.config.assistant import assistant_settings_path
from front_office.providers.ollama import OllamaProvider
from tests.ollama_fakes import ScriptedOllama


def check(project: Path, ollama: ScriptedOllama):  # type: ignore[no-untyped-def]
    return status(project, provider=OllamaProvider(transport=ollama))


def test_ready_with_the_default_model(project: Path) -> None:
    result = check(
        project, ScriptedOllama(version="0.40.2", models=["qwen3:8b", "qwen3:4b-instruct"])
    )
    assert result.is_ready and result.model == "qwen3:8b"
    assert result.message == "Ready: qwen3:8b on Ollama 0.40.2."


def test_the_fallback_answers_when_the_default_is_missing(project: Path) -> None:
    result = check(project, ScriptedOllama(models=["qwen3:4b-instruct"]))
    assert result.is_ready and result.model == "qwen3:4b-instruct"
    assert "using the fallback" in result.message


def test_a_model_that_cannot_use_tools_does_not_count(project: Path) -> None:
    no_tools = {"capabilities": ["completion"], "model_info": {}}
    result = check(project, ScriptedOllama(models=["qwen3:8b"], details={"qwen3:8b": no_tools}))
    assert result.state is AssistantState.NO_MODEL


def test_no_model_says_what_to_pull(project: Path) -> None:
    result = check(project, ScriptedOllama(models=["llama3.2:latest"]))
    assert result.state is AssistantState.NO_MODEL
    assert "Run: ollama pull qwen3:8b" in result.message


def test_ollama_not_running_is_a_message_not_an_error(project: Path) -> None:
    result = check(project, ScriptedOllama(down=True))
    assert result.state is AssistantState.OFFLINE and not result.is_ready
    assert "Start the Ollama app" in result.message
    assert "Everything else in the lab works without it" in result.message


def test_broken_settings_are_reported(project: Path) -> None:
    assistant_settings_path(project / "configs").write_text("version: 1\n", encoding="utf-8")
    result = check(project, ScriptedOllama())
    assert result.state is AssistantState.MISCONFIGURED
