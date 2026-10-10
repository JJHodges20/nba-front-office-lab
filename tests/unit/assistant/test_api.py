from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from front_office.assistant import api
from front_office.assistant.api import AssistantState, status
from front_office.assistant.toolbox import Toolbox
from front_office.config import Settings
from front_office.config.assistant import assistant_settings_path
from front_office.domain.assistant import Answer, Mode, Outcome
from front_office.providers.ollama import OllamaProvider
from front_office.services import Lab
from tests.ollama_fakes import ScriptedOllama, chat_chunks, tool_call


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


# --- a question in the background ---------------------------------------------------------

BOS = 1610612738
CELTICS = tool_call("team_stats", team_id=BOS, season="2025-26")
QUESTION = api.Question("What was the Celtics' net rating in 2025-26?", season="2025-26")


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A scripted model behind the facade, and the lab's own tools only."""

    def use(ollama: ScriptedOllama) -> ScriptedOllama:
        monkeypatch.setattr(api, "connect", lambda host, timeout: OllamaProvider(transport=ollama))
        monkeypatch.setattr(api, "tools_for", lambda lab: Toolbox.lab_only())
        return ollama

    return use


def test_a_question_is_answered_in_the_background(scripted, built_readonly: Settings) -> None:
    scripted(
        ScriptedOllama(chats=[chat_chunks(tool_calls=[CELTICS]), chat_chunks("It was +8.3 [r1].")])
    )
    job = api.start(QUESTION, project_root=built_readonly.project_root, today=date(2026, 10, 9))
    assert job.wait(30)
    turn = job.turn()
    assert turn.error is None and turn.answer is not None
    assert turn.answer.outcome is Outcome.SUPPORTED and turn.answer.text == "It was +8.3 [r1]."
    assert [step.kind for step in turn.steps] == ["model", "tool", "model"]
    assert turn.seconds > 0


def test_a_stopped_question_says_so_and_keeps_what_it_gathered(
    scripted, built_readonly: Settings
) -> None:
    scripted(ScriptedOllama(chats=[chat_chunks(tool_calls=[CELTICS])]))
    job = api.Job(QUESTION, project_root=built_readonly.project_root)
    job.stop()  # taken at the next step, whether or not the model has been asked yet
    assert job.wait(30) and job.stopping
    turn = job.turn()
    assert turn.answer is not None
    assert turn.answer.text.startswith("Stopped before an answer")
    assert turn.answer.warnings == ("Stopped by the user.",)


def test_ollama_down_is_said_not_raised(scripted, built_readonly: Settings) -> None:
    scripted(ScriptedOllama(down=True))
    job = api.start(QUESTION, project_root=built_readonly.project_root)
    assert job.wait(30)
    turn = job.turn()
    assert turn.answer is None and "Ollama is not running" in (turn.error or "")


def test_the_next_question_carries_the_last_three_answered_turns() -> None:
    answered = [
        api.Turn(QUESTION, Answer(f"q{n}", f"answer {n}", Outcome.SUPPORTED)) for n in range(5)
    ]
    failed = api.Turn(QUESTION, None, "Ollama is not running")
    messages = api.history([*answered, failed])
    assert [m.role for m in messages] == ["user", "assistant"] * 3
    assert [m.content for m in messages if m.role == "assistant"] == [
        "answer 2",
        "answer 3",
        "answer 4",
    ]


def test_the_context_says_where_the_season_and_the_data_stand(built_readonly: Settings) -> None:
    with Lab(built_readonly) as lab:
        context = api.context_for(lab, QUESTION, date(2026, 10, 9))
    assert context.calendar.startswith("2026-27 league year; none of its games played yet")
    assert context.data.startswith("data build 1 of 2026-10-01; team statistics 1996-97 to 2025-26")
    assert context.data.endswith("no contract file.")
    assert (context.season, context.mode) == ("2025-26", Mode.QUICK)


def test_status_says_whether_web_search_is_set_up(project: Path) -> None:
    assert not check(project, ScriptedOllama()).web_search
    (project / ".env").write_text("FOL_OLLAMA_API_KEY=not-a-real-key\n", encoding="utf-8")
    assert check(project, ScriptedOllama()).web_search


def test_a_refresh_by_hand_reports_each_source(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    from front_office.pipelines.current import CurrentRefresh, SourceRefresh

    asked = []

    def fake(settings, *, force):  # type: ignore[no-untyped-def]
        asked.append(force)
        return CurrentRefresh((SourceRefresh("games", "none", 0, "no 2026-27 games played yet"),))

    monkeypatch.setattr(api, "fetch_current", fake)
    assert api.refresh_current(project, force=True) == (
        api.Refreshed("games", "none", "no 2026-27 games played yet"),
    )
    assert asked == [True]
