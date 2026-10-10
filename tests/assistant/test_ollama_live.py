"""The assistant against the real local model. Needs Ollama running with the configured
model pulled; deselected by default (``pytest -m ollama``). The full measures are the
benchmark (``scripts/benchmark_ollama.py``) and the end-to-end evaluation
(``scripts/evaluate_answers.py``); these only show the pieces fit together."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.assistant.api import status
from front_office.assistant.evaluation import (
    context_for,
    load_cases,
    messages_for,
    question_of,
    score,
    score_answer,
)
from front_office.assistant.orchestrator import Assistant
from front_office.assistant.routing import first_move
from front_office.config import Settings, load_assistant_settings, load_settings
from front_office.providers.ollama import OllamaProvider
from front_office.services import Lab
from tests.assistant.recorded import world_toolbox

pytestmark = pytest.mark.ollama

ROOT = Path(__file__).resolve().parents[2]
CASES = load_cases(Path(__file__).parent / "fixtures" / "cases.yaml")


def test_the_assistant_is_ready_on_this_machine() -> None:
    result = status(ROOT)
    assert result.is_ready, result.message


@pytest.mark.parametrize("case_id", ["H01", "X01"])
def test_the_default_model_makes_the_right_first_move(case_id: str) -> None:
    settings = load_assistant_settings(load_settings(ROOT).config_dir)
    provider = OllamaProvider(settings.ollama.host, timeout=settings.ollama.timeout_seconds)
    case = next(item for item in CASES.cases if item.id == case_id)
    mode = settings.mode(case.mode)
    can_think = provider.details(settings.default_model).can_think
    move = first_move(
        provider,
        settings.default_model,
        context_for(CASES, case),
        messages_for(case),
        settings=mode,
        think=mode.think if can_think else None,
    )
    result = score(case, move)
    assert result.passed, result


@pytest.mark.parametrize("case_id", ["H01", "C03", "X01"])
def test_the_default_model_answers_end_to_end(
    case_id: str, built_lab: Settings, tmp_path: Path
) -> None:
    """A whole answer in the recorded world, as ``scripts/evaluate_answers.py`` runs it."""
    settings = load_assistant_settings(load_settings(ROOT).config_dir)
    provider = OllamaProvider(settings.ollama.host, timeout=settings.ollama.timeout_seconds)
    case = next(item for item in CASES.cases if item.id == case_id)
    history, question, _ = question_of(case)
    with Lab(built_lab) as lab:
        toolbox = world_toolbox(lab, case, tmp_path)
        answer = Assistant(lab, settings, provider, toolbox=toolbox).ask(
            question, context_for(CASES, case), history=history
        )
    scored = score_answer(case, answer)
    assert scored.passed, (scored, answer.text)
