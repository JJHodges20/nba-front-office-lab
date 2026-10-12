"""Ask AI about this (A6): a question from another page, about what that page shows, kept
in the workspace open on the AI Research page - and the sidebar left as it was."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import front_office.assistant.api as api
from front_office.config import load_settings
from front_office.pipelines.build import BuildReport
from front_office.providers.ollama import OllamaProvider
from front_office.services import Lab
from tests.helpers import BOS, TATUM
from tests.ollama_fakes import ScriptedOllama, chat_chunks
from tests.ui.conftest import texts
from wb import answers, state


@pytest.fixture
def home(built_template: tuple[Path, BuildReport], tmp_path: Path) -> Path:
    target = tmp_path / "home"
    shutil.copytree(built_template[0], target)
    return target


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Callable[[ScriptedOllama], ScriptedOllama]:
    def use(ollama: ScriptedOllama) -> ScriptedOllama:
        monkeypatch.setattr(api, "connect", lambda host, timeout: OllamaProvider(transport=ollama))
        return ollama

    return use


def test_the_page_says_what_a_question_from_it_is_about(page, home: Path) -> None:
    app = page(home, "teams", **{state.TEAM: BOS})
    button = app.button(key="ai_ask")
    assert button.label == "Ask AI about this"
    assert "Boston Celtics, 2025-26 regular season" in str(button.help)


def test_the_dialog_opens_on_what_the_page_shows(model, page, home: Path) -> None:
    model(ScriptedOllama())
    app = page(home, "teams", **{state.TEAM: BOS, state.PLAYER: TATUM})
    app.button(key="ai_ask").click().run()
    assert answers.escaped("About Jayson Tatum, Boston Celtics, 2025-26 regular season") in texts(
        app
    )
    assert app.text_area(key="ai_ask_question").label == "Your question"


def test_with_ollama_offline_the_dialog_says_so_and_cannot_ask(page, home: Path) -> None:
    """A9 audit: every page test runs with Ollama offline (``tests/ui/conftest.py``); the
    dialog says how to start it and offers nothing to press."""
    app = page(home, "teams", **{state.TEAM: BOS})
    app.button(key="ai_ask").click().run()
    said = texts(app)
    assert "The assistant cannot answer yet" in said and "Start the Ollama app" in said
    assert not [button for button in app.button if button.key == "ai_ask_go"]


def draw_body(page: str) -> None:
    """The dialog's body drawn inline, under the sidebar, as a page would open it."""
    from wb import ask, data, state

    filters = state.sidebar(data.status())
    ask.body(ask.from_filters(page, filters))


def test_a_question_from_a_page_is_about_what_it_shows_and_kept(model, open_at, home: Path) -> None:
    ollama = model(ScriptedOllama(chats=[chat_chunks("They were good [no figures].")]))
    open_at(home)
    app = AppTest.from_function(draw_body, kwargs={"page": "Team Explorer"})
    app.session_state[state.TEAM] = BOS
    app.session_state[state.PLAYER] = TATUM
    app.run()
    app.text_area(key="ai_ask_question").set_value("How good was their defense?")
    app.button(key="ai_ask_go").click().run()
    job = app.session_state[state.AI_JOB]
    if job is not None:
        assert job.wait(30)
        app.run()
    assert "They were good" in texts(app), "the answer, in short, in the dialog"
    with Lab(load_settings(home)) as lab:
        (workspace,) = lab.workspaces.list()
        (turn,) = lab.workspaces.turns(workspace.workspace_id)
    assert (turn.question, turn.asked_from) == ("How good was their defense?", "Team Explorer")
    assert turn.about == "Jayson Tatum, Boston Celtics, 2025-26 regular season"
    assert (turn.focus.team_id, turn.focus.player_id) == (BOS, TATUM)
    system = ollama.chat_payloads[0]["messages"][0]["content"]
    assert f"team id {BOS}" in system or f"team_id {BOS}" in system
    assert app.session_state[state.TEAM] == BOS, "the sidebar is as it was"


def test_a_damaged_research_file_is_said_and_the_pages_still_draw(page, home: Path) -> None:
    """A9: with the research file unreadable, every other page draws as before, and the
    dialog says why nothing can be asked and where it is put right."""
    research = load_settings(home).research_path
    research.parent.mkdir(parents=True, exist_ok=True)
    research.write_bytes(b"not a database " * 300)
    page(home, "teams", **{state.TEAM: BOS})
    app = AppTest.from_function(draw_body, kwargs={"page": "Team Explorer"})
    app.run()
    assert not app.exception, [error.value for error in app.exception]
    assert "Your saved research cannot be opened" in texts(app)
    assert not [area for area in app.text_area if area.key == "ai_ask_question"]
