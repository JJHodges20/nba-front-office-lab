"""The AI Research page, with a scripted model: no Ollama, no network.

A question runs in a background thread; a test waits for it, then runs the page again to
see the answer, as the page's own polling would.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from streamlit.testing.v1 import AppTest

import front_office.assistant.api as api
from front_office.providers.ollama import OllamaProvider, OllamaUnavailable
from tests.helpers import BOS, BROWN, WHITE
from tests.ollama_fakes import ScriptedOllama, chat_chunks, tool_call
from tests.ui.conftest import drawn, texts
from wb.views import research

HISTORY = tool_call("team_stats", team_id=BOS, season="2025-26", view="history")


class Held(ScriptedOllama):
    """A model that answers only once let go: a question stays under way until then."""

    def __init__(self, gate: threading.Event, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.gate = gate

    def __call__(
        self, method: str, url: str, payload: Mapping[str, Any] | None, timeout: float
    ) -> Iterator[Mapping[str, Any]]:
        if urlsplit(url).path == "/api/chat":
            self.gate.wait(30)
        yield from super().__call__(method, url, payload, timeout)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Callable[[ScriptedOllama], ScriptedOllama]:
    """Put a scripted model behind the assistant: it is ready, and answers as scripted."""

    def use(ollama: ScriptedOllama) -> ScriptedOllama:
        monkeypatch.setattr(api, "connect", lambda host, timeout: OllamaProvider(transport=ollama))
        return ollama

    return use


def ask(app: AppTest, question: str) -> AppTest:
    """Ask, wait for the answer in the background, and draw the page again."""
    app.chat_input(key="ai_question").set_value(question).run()
    job = app.session_state["ai_job"]
    if job is not None:
        assert job.wait(30)
        app.run()
    assert not app.exception, [error.value for error in app.exception]
    return app


def test_offline_says_how_to_start_ollama_and_cannot_be_asked(page, plain_home: Path) -> None:
    app = page(plain_home, "research")
    said = texts(app)
    assert "Ollama is not running" in said and "Start the Ollama app" in said
    assert app.chat_input(key="ai_question").disabled
    assert "Ask a question" in said, "the page says what it is for even before it can answer"


def test_the_status_shows_web_search_and_each_current_source(page, plain_home: Path) -> None:
    said = texts(page(plain_home, "research"))
    assert "Web search: not set up" in said
    for source in ("Games", "Transactions", "Injury report"):
        assert f"{source}: never fetched" in said


def test_an_answer_shows_its_outcome_its_rows_its_chart_and_its_evidence(
    model, page, plain_home: Path
) -> None:
    model(
        ScriptedOllama(
            chats=[
                chat_chunks(tool_calls=[HISTORY]),
                chat_chunks("Their net rating was +8.3 in 2025-26 [r1]."),
            ]
        )
    )
    app = ask(page(plain_home, "research"), "How have the Celtics' seasons gone?")
    (turn,) = app.session_state["ai_turns"]
    assert turn.answer is not None and turn.answer.outcome.value == "supported"
    said = texts(app)
    assert "Their net rating was +8.3 in 2025-26 [r1]." in said
    assert "Supported" in said
    assert [tab.label for tab in app.tabs][0].startswith("r1 · Boston Celtics, every season")
    charts = drawn(app)
    assert "ai_chart_0_r1_0" in charts, "the tool chose a line of net rating by season"
    seasons = list(charts["ai_chart_0_r1_0"].data[0].x)
    assert seasons == sorted(seasons) and "2025-26" in seasons
    # AppTest files an expander that has an icon among the status blocks.
    folded = [block.label for block in app.status]
    assert "Evidence: 1 source" in folded and "How it was answered" in folded
    assert len(app.dataframe) >= 1


def test_a_scenario_shows_its_chances_before_and_after_and_the_model_files(
    model, page, plain_home: Path
) -> None:
    missing = tool_call(
        "simulate_scenario",
        subject="team",
        subject_id=BOS,
        player_assumptions=[{"player_id": WHITE, "games_missed": 30}],
    )
    model(
        ScriptedOllama(
            chats=[
                chat_chunks(tool_calls=[missing]),
                chat_chunks("With Derrick White missing 30 games the chances move [r1]."),
            ]
        )
    )
    app = ask(page(plain_home, "research"), "What if Derrick White misses 30 games?")
    (turn,) = app.session_state["ai_turns"]
    assert turn.answer is not None and turn.answer.outcome.value == "supported"
    said = texts(app)
    assert "Modeled" in said and "Your assumption" in said, "the header names both kinds"
    figure = drawn(app)["ai_chart_0_r1_0"]
    assert {trace.name for trace in figure.data} == {"Before", "After"}
    chances = [value for trace in figure.data for value in trace.x]
    assert all(0 <= value <= 1 for value in chances), "a chance's own axis, not a percentile's"
    assert figure.layout.xaxis.tickformat == ".0%"
    labels = {item.label for item in turn.answer.evidence}
    assert any(label.startswith("Simulator parameters, revision") for label in labels)


def test_a_name_with_two_readings_is_asked_about_and_the_choice_asks_again(
    model, page, plain_home: Path
) -> None:
    ollama = model(
        ScriptedOllama(
            chats=[
                chat_chunks(tool_calls=[tool_call("player_stats", player_id=BROWN, season="2025-26")]),
                chat_chunks("Here is Jaylen Brown's season [r1]."),
            ]
        )
    )  # fmt: skip
    app = ask(page(plain_home, "research"), "How did Brown shoot this season?")
    (asked,) = app.session_state["ai_turns"]
    assert asked.answer is not None and asked.answer.outcome.value == "clarify"
    assert ollama.chat_payloads == [], "the model is not asked until the name is settled"
    jaylen = next(
        position for position, option in enumerate(asked.answer.options) if option.id == BROWN
    )
    app.button(key=f"ai_option_0_{jaylen}").click().run()
    job = app.session_state["ai_job"]
    assert job is not None and job.wait(30)
    app.run()
    first, second = app.session_state["ai_turns"]
    assert second.answer is not None and second.answer.outcome.value != "clarify"
    system = ollama.chat_payloads[0]["messages"][0]["content"]
    assert f'"Brown": player Jaylen Brown (player_id {BROWN})' in system


def test_a_question_under_way_shows_its_steps_and_can_be_stopped(
    model, page, plain_home: Path
) -> None:
    gate = threading.Event()
    model(Held(gate, chats=[chat_chunks(tool_calls=[HISTORY])]))
    app = page(plain_home, "research")
    app.chat_input(key="ai_question").set_value("How have the Celtics' seasons gone?").run()
    job = app.session_state["ai_job"]
    assert job is not None and not job.done
    assert app.chat_input(key="ai_question").disabled, "one question at a time"
    app.button(key="ai_stop").click().run()
    assert job.stopping
    gate.set()
    assert job.wait(30)
    app.run()
    (turn,) = app.session_state["ai_turns"]
    assert turn.answer is not None
    assert turn.answer.text.startswith("Stopped before an answer")


def test_an_answer_that_never_came_says_why(model, page, plain_home: Path) -> None:
    model(ScriptedOllama(chats=[OllamaUnavailable("connection reset")]))
    app = ask(page(plain_home, "research"), "How have the Celtics' seasons gone?")
    (turn,) = app.session_state["ai_turns"]
    assert turn.answer is None and "connection reset" in (turn.error or "")
    assert "No answer" in texts(app)
    assert not app.error, "a failed question is said in the conversation, not as an error box"


def test_a_new_conversation_starts_again_and_a_refresh_reports(
    model, page, plain_home: Path
) -> None:
    model(ScriptedOllama(chats=[chat_chunks("Nothing to look up [no figures].")]))
    app = ask(page(plain_home, "research"), "Hello?")
    assert len(app.session_state["ai_turns"]) == 1
    app.button(key="ai_new").click().run()
    assert app.session_state["ai_turns"] == []
    app.button(key="ai_refresh").click().run()
    assert "Games: none - nothing is fetched in tests" in texts(app)


def test_a_dollar_is_shown_as_a_dollar_and_an_image_is_not_fetched() -> None:
    assert research._prose("Tatum earns $40M; Brown $30M.") == "Tatum earns \\$40M; Brown \\$30M."
    assert research._prose("See ![x](https://example.com/t.png) now") == "See (image left out) now"
    assert research._escaped("[r1] *bold* $5") == "\\[r1\\] \\*bold\\* \\$5"


def test_a_figure_no_catalog_describes_has_no_tail_of_zeros() -> None:
    # Live at A3: a benchmark's bands showed as 5.000000 and 0.793451.
    assert [research._plain(v) for v in (5.0, 0.793451, 114.9, 1610.0, float("nan"))] == [
        "5",
        "0.793",
        "114.9",
        "1,610",
        "—",
    ]
