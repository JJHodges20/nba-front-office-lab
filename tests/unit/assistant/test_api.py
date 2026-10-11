from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from front_office.assistant import api
from front_office.assistant import tools as t
from front_office.assistant.api import AssistantState, status
from front_office.assistant.toolbox import LAB_HANDLERS, Toolbox
from front_office.config import Settings, load_settings
from front_office.config.assistant import assistant_settings_path
from front_office.domain.assistant import Answer, Mode, Outcome
from front_office.domain.research import Focus, SavedTurn
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


def workspace(home: Settings, name: str = "Questions") -> int:
    with Lab(home) as lab:
        return lab.workspaces.create(name).workspace_id


def asked(home: Settings, question: api.Question, workspace_id: int) -> api.Job:
    job = api.start(question, workspace_id, project_root=home.project_root, today=date(2026, 10, 9))
    assert job.wait(30)
    return job


def test_a_question_is_answered_in_the_background_and_kept(scripted, built_lab: Settings) -> None:
    scripted(
        ScriptedOllama(chats=[chat_chunks(tool_calls=[CELTICS]), chat_chunks("It was +8.3 [r1].")])
    )
    place = workspace(built_lab)
    turn = asked(built_lab, QUESTION, place).turn()
    assert turn.error is None and turn.answer is not None
    assert turn.answer.outcome is Outcome.SUPPORTED and turn.answer.text == "It was +8.3 [r1]."
    assert [step.kind for step in turn.steps] == ["model", "tool", "model"]
    assert turn.seconds > 0 and turn.turn_id is not None
    with Lab(built_lab) as lab:
        (kept,) = lab.workspaces.turns(place)
        stamp = lab.workspaces.stamp()
    assert kept.answer is not None and kept.answer.text == "It was +8.3 [r1]."
    assert (kept.build_id, kept.value_model) == stamp
    assert kept.focus.season == "2025-26" and kept.asked_from == "AI Research"


def test_a_stopped_question_says_so_and_keeps_what_it_gathered(
    scripted, built_lab: Settings
) -> None:
    scripted(ScriptedOllama(chats=[chat_chunks(tool_calls=[CELTICS])]))
    job = api.Job(QUESTION, workspace(built_lab), project_root=built_lab.project_root)
    job.stop()  # taken at the next step, whether or not the model has been asked yet
    assert job.wait(30) and job.stopping
    turn = job.turn()
    assert turn.answer is not None
    assert turn.answer.text.startswith("Stopped before an answer")
    assert turn.answer.warnings == ("Stopped by the user.",)


def test_ollama_down_is_said_not_raised_and_kept(scripted, built_lab: Settings) -> None:
    scripted(ScriptedOllama(down=True))
    place = workspace(built_lab)
    turn = asked(built_lab, QUESTION, place).turn()
    assert turn.answer is None and "Ollama is not running" in (turn.error or "")
    with Lab(built_lab) as lab:
        (kept,) = lab.workspaces.turns(place)
    assert kept.answer is None and "Ollama is not running" in (kept.error or "")


def test_a_follow_up_carries_its_own_workspace_and_nothing_else(
    scripted, built_lab: Settings
) -> None:
    """A6: no cross-workspace leaks. A follow-up reads its own workspace's conversation."""
    knicks_question = api.Question("How did the Knicks do in 2025-26?", season="2025-26")
    model = scripted(
        ScriptedOllama(
            chats=[
                chat_chunks("Celtics answer, without figures [no tool]."),
                chat_chunks("Knicks answer, without figures [no tool]."),
                chat_chunks("A follow-up answer."),
            ]
        )
    )
    celtics, knicks = workspace(built_lab, "Celtics"), workspace(built_lab, "Knicks")
    asked(built_lab, QUESTION, celtics)
    asked(built_lab, knicks_question, knicks)
    asked(built_lab, api.Question("And in 2012-13?", season="2025-26"), knicks)
    follow_up = model.chat_payloads[-1]["messages"]
    said = [message["content"] for message in follow_up if message["role"] != "system"]
    assert said[:2] == [
        "How did the Knicks do in 2025-26?",
        "Knicks answer, without figures [no tool].",
    ]
    assert not any("Celtics" in text for text in said), "nothing of the other workspace"


def test_the_notes_are_background_not_evidence(scripted, built_lab: Settings) -> None:
    """A6: a workspace's notes reach the model, but a figure from them is not one it may
    state: the checker does not read them."""
    model = scripted(
        ScriptedOllama(
            chats=[
                chat_chunks("The note says 99.9, so it was +99.9."),
                chat_chunks("The note says 99.9, so it was +99.9."),
            ]
        )
    )
    place = workspace(built_lab)
    with Lab(built_lab) as lab:
        lab.workspaces.update(place, notes="Their net rating was +99.9 last time I looked.")
    turn = asked(built_lab, QUESTION, place).turn()
    system = model.chat_payloads[0]["messages"][0]["content"]
    assert "Workspace notes" in system and "+99.9 last time" in system
    assert turn.answer is not None and "99.9" in turn.answer.removed


def test_kept_turns_become_the_conversation_a_follow_up_reads() -> None:
    def kept(n: int, answer: Answer | None) -> SavedTurn:
        return SavedTurn(
            workspace_id=1,
            conversation=1,
            asked_at=datetime(2026, 10, 10, 13, n),
            question=f"q{n}",
            mode=Mode.QUICK,
            focus=Focus(season="2025-26"),
            asked_from="AI Research",
            answer=answer,
            error=None if answer else "Ollama is not running",
        )

    turns = [kept(n, Answer(f"q{n}", f"answer {n}", Outcome.SUPPORTED)) for n in range(2)]
    messages = api.history([*turns, kept(2, None)])
    assert [(m.role, m.content) for m in messages] == [
        ("user", "q0"),
        ("assistant", "answer 0"),
        ("user", "q1"),
        ("assistant", "answer 1"),
    ]


def test_a_kept_question_can_be_asked_again_as_it_was() -> None:
    turn = SavedTurn(
        workspace_id=1,
        conversation=1,
        asked_at=datetime(2026, 10, 10),
        question="Their defense?",
        mode=Mode.DEEP,
        focus=Focus(season="2012-13", season_type="playoffs", team_id=BOS, roster_id=4),
        asked_from="Team Explorer",
        answer=None,
        about="Boston Celtics, 2012-13 playoffs",
    )
    again = api.Question.again(turn)
    assert (again.text, again.mode, again.season, again.season_type) == (
        "Their defense?",
        Mode.DEEP,
        "2012-13",
        "playoffs",
    )
    assert (again.team_id, again.roster_id, again.asked_from, again.about) == (
        BOS,
        4,
        "Team Explorer",
        "Boston Celtics, 2012-13 playoffs",
    )


def test_a_conversation_is_summarized_into_the_notes(scripted, built_lab: Settings) -> None:
    scripted(
        ScriptedOllama(
            chats=[
                chat_chunks("They were good [no tool]."),
                chat_chunks(
                    "- The user asked how the Celtics did; the answer said they were good."
                ),
            ]
        )
    )
    place = workspace(built_lab)
    with Lab(built_lab) as lab:
        lab.workspaces.update(place, notes="My own note.")
    asked(built_lab, QUESTION, place)
    summary = api.summarize(place, project_root=built_lab.project_root, today=date(2026, 10, 10))
    assert summary.startswith("- The user asked how the Celtics did")
    with Lab(built_lab) as lab:
        kept = lab.workspaces.get(place)
        follows = lab.workspaces.history(place)
    assert kept.notes is not None and kept.notes.startswith("My own note.\n\nSummary of earlier")
    assert "(written by the assistant; not evidence)" in kept.notes
    assert kept.conversation == 2 and follows == (), "the next question follows the notes"
    with pytest.raises(api.SummaryError, match="nothing to summarize"):
        api.summarize(place, project_root=built_lab.project_root)


def test_a_summary_needs_the_model(scripted, built_lab: Settings) -> None:
    scripted(ScriptedOllama(down=True))
    with pytest.raises(api.SummaryError, match="Ollama is not running"):
        api.summarize(workspace(built_lab), project_root=built_lab.project_root)


def test_the_context_says_where_the_season_and_the_data_stand(built_readonly: Settings) -> None:
    with Lab(built_readonly) as lab:
        context = api.context_for(lab, QUESTION, date(2026, 10, 9))
    assert context.calendar.startswith("2026-27 league year; none of its games played yet")
    assert context.data.startswith("data build 1 of 2026-10-01; team statistics 1996-97 to 2025-26")
    assert "; the models project 2026-27;" in context.data
    assert context.data.endswith("no contract file.")
    assert (context.season, context.mode) == ("2025-26", Mode.QUICK)


def test_status_says_whether_web_search_is_set_up(project: Path) -> None:
    assert not check(project, ScriptedOllama()).web_search
    (project / ".env").write_text("FOL_OLLAMA_API_KEY=not-a-real-key\n", encoding="utf-8")
    assert check(project, ScriptedOllama()).web_search


def test_a_refresh_by_hand_reports_each_source(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    from front_office.pipelines.current import CurrentRefresh, SourceRefresh

    asked = []

    def fake(settings, *, sources, force):  # type: ignore[no-untyped-def]
        asked.append((tuple(sources), force))
        return CurrentRefresh((SourceRefresh("games", "none", 0, "no 2026-27 games played yet"),))

    monkeypatch.setattr(api, "fetch_current", fake)
    assert api.refresh_current(project, force=True) == (
        api.Refreshed("games", "none", "no 2026-27 games played yet"),
    )
    assert asked == [(("games", "transactions", "injuries", "news"), True)], "the news too (A7)"


# --- an approved roster proposal ---------------------------------------------------------------


def test_an_approved_proposal_is_saved_once(priced_template: Path, tmp_path: Path) -> None:
    """A5: the page's button reaches the save through the facade; a second press finds it.
    A6: each press is logged in the workspace, and a decline is too."""
    home = tmp_path / "home"
    shutil.copytree(priced_template, home)
    request = t.OptimizeRoster(budget_mode="custom", budget_millions=150)
    with Lab(load_settings(home)) as lab:
        first, second, *_ = LAB_HANDLERS["optimize_roster"](lab, request).proposals
        place = lab.workspaces.create("Proposals").workspace_id
    saved = api.save_proposal(first, "Approved", workspace_id=place, project_root=home)
    assert saved.created and saved.name == "Approved"
    again = api.save_proposal(first, "Approved again", workspace_id=place, project_root=home)
    assert not again.created and again.roster_id == saved.roster_id
    api.decline_proposal(second.fingerprint, workspace_id=place, project_root=home)
    with Lab(load_settings(home)) as lab:
        members = lab.rosters.players(saved.roster_id)
        log = [entry.action for entry in lab.workspaces.approvals(place)]
    assert set(members["player_id"]) == set(first.player_ids)
    assert log == ["saved", "already_saved", "declined"]


def test_a_season_named_in_a_follow_up_is_the_one_meant(scripted, built_lab: Settings) -> None:
    """A6: a follow-up naming a season is about that season, whatever the workspace or the
    sidebar look at; the season they look at is still said, as the sidebar's."""
    model = scripted(
        ScriptedOllama(chats=[chat_chunks("First [no tool]."), chat_chunks("Then [no tool].")])
    )
    place = workspace(built_lab)
    with Lab(built_lab) as lab:
        lab.workspaces.update(place, focus=Focus(season="2025-26", team_id=BOS))
    asked(built_lab, QUESTION, place)
    asked(built_lab, api.Question("And in 2012-13?", season="2025-26", team_id=BOS), place)
    system = model.chat_payloads[-1]["messages"][0]["content"]
    assert '"2012-13": season 2012-13' in system
    assert "Sidebar: season 2025-26" in system
