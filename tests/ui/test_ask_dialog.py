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
