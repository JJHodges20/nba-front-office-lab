"""The AI Research page, with a scripted model: no Ollama, no network.

A question runs in a background thread; a test waits for it, then runs the page again to
see the answer, as the page's own polling would. Every question is kept in a workspace in
the project's research store (A6), so each test works on a private copy of a project.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from streamlit.testing.v1 import AppTest

import front_office.assistant.api as api
from front_office.config import load_settings
from front_office.domain.assistant import Answer, Mode, Outcome
from front_office.domain.research import Focus, SavedTurn
from front_office.pipelines.build import BuildReport
from front_office.providers.ollama import OllamaProvider, OllamaUnavailable
from front_office.services import Lab
from tests.helpers import BOS, BROWN, NYK, WHITE
from tests.ollama_fakes import ScriptedOllama, chat_chunks, tool_call
from tests.ui.conftest import drawn, texts
from wb import answers

HISTORY = tool_call("team_stats", team_id=BOS, season="2025-26", view="history")
NOTHING = chat_chunks("Nothing to look up [no figures].")


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
def home(built_template: tuple[Path, BuildReport], tmp_path: Path) -> Path:
    """A private copy of the built project, without contracts: its research is its own."""
    target = tmp_path / "home"
    shutil.copytree(built_template[0], target)
    return target


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
    return settled(app)


def settled(app: AppTest) -> AppTest:
    """The page once the question under way is answered. A scripted model can answer before
    the run that started it ends, which then takes the answer in itself."""
    job = app.session_state["ai_job"]
    if job is not None:
        assert job.wait(30)
        app.run()
    assert not app.exception, [error.value for error in app.exception]
    return app


def kept(home: Path, workspace_id: int | None = None) -> tuple[SavedTurn, ...]:
    """The turns a workspace keeps: the first one's, unless another is named."""
    with Lab(load_settings(home)) as lab:
        workspaces = lab.workspaces
        chosen = workspace_id or workspaces.list(archived=None)[-1].workspace_id
        return workspaces.turns(chosen)


def opened_workspace(app: AppTest) -> int:
    return int(app.session_state["ai_workspace"])


def keyed(widgets: Any, prefix: str) -> Any:
    """The one widget whose key begins with ``prefix``. A form's keys end with what it shows,
    or with how many times it was sent, so that it starts again as new widgets: a browser
    keeps what was typed into a widget whose key was only forgotten (A6)."""
    (found,) = [widget for widget in widgets if widget.key and widget.key.startswith(prefix)]
    return found


# --- where things stand --------------------------------------------------------------------------


def test_offline_says_how_to_start_ollama_and_cannot_be_asked(page, home: Path) -> None:
    app = page(home, "research")
    said = texts(app)
    assert "Ollama is not running" in said and "Start the Ollama app" in said
    assert app.chat_input(key="ai_question").disabled
    assert "Ask a question in “My research”" in said, "a workspace is made to start in"


def test_the_status_shows_web_search_and_each_current_source(page, home: Path) -> None:
    said = texts(page(home, "research"))
    assert "Web search: not set up" in said
    for source in ("Games", "Transactions", "Injury report"):
        assert f"{source}: never fetched" in said


# --- answers -------------------------------------------------------------------------------------


def test_an_answer_shows_its_outcome_its_rows_its_chart_and_its_evidence(
    model, page, home: Path
) -> None:
    model(
        ScriptedOllama(
            chats=[
                chat_chunks(tool_calls=[HISTORY]),
                chat_chunks("Their net rating was +8.3 in 2025-26 [r1]."),
            ]
        )
    )
    app = ask(page(home, "research"), "How have the Celtics' seasons gone?")
    (turn,) = kept(home)
    assert turn.answer is not None and turn.answer.outcome.value == "supported"
    said = texts(app)
    assert "Their net rating was +8.3 in 2025-26 [r1]." in said
    assert "Supported" in said
    assert [tab.label for tab in app.tabs][0].startswith("r1 · Boston Celtics, every season")
    charts = drawn(app)
    key = f"ai_chart_t{turn.turn_id}_r1_0"
    assert key in charts, "the tool chose a line of net rating by season"
    seasons = list(charts[key].data[0].x)
    assert seasons == sorted(seasons) and "2025-26" in seasons
    # AppTest files an expander that has an icon among the status blocks.
    folded = [block.label for block in app.status]
    assert "Evidence: 1 source" in folded and "How it was answered" in folded
    assert len(app.dataframe) >= 1


def test_a_kept_answer_is_drawn_again_as_it_was(model, page, home: Path) -> None:
    """A6: the page draws a kept answer from the workspace, rows and chart included, in a
    later session as in the one that asked."""
    model(
        ScriptedOllama(chats=[chat_chunks(tool_calls=[HISTORY]), chat_chunks("It went well [r1].")])
    )
    ask(page(home, "research"), "How have the Celtics' seasons gone?")
    (turn,) = kept(home)
    later = page(home, "research")  # a new session: nothing of the first is held
    assert "It went well [r1]." in texts(later)
    assert f"ai_chart_t{turn.turn_id}_r1_0" in drawn(later)


def test_a_scenario_shows_its_chances_before_and_after_and_the_model_files(
    model, page, home: Path
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
    app = ask(page(home, "research"), "What if Derrick White misses 30 games?")
    (turn,) = kept(home)
    assert turn.answer is not None and turn.answer.outcome.value == "supported"
    said = texts(app)
    assert "Modeled" in said and "Your assumption" in said, "the header names both kinds"
    figure = drawn(app)[f"ai_chart_t{turn.turn_id}_r1_0"]
    assert {trace.name for trace in figure.data} == {"Before", "After"}
    chances = [value for trace in figure.data for value in trace.x]
    assert all(0 <= value <= 1 for value in chances), "a chance's own axis, not a percentile's"
    assert figure.layout.xaxis.tickformat == ".0%"
    labels = {item.label for item in turn.answer.evidence}
    assert any(label.startswith("Simulator parameters, revision") for label in labels)


def test_a_name_with_two_readings_is_asked_about_and_the_choice_asks_again(
    model, page, home: Path
) -> None:
    ollama = model(
        ScriptedOllama(
            chats=[
                chat_chunks(tool_calls=[tool_call("player_stats", player_id=BROWN, season="2025-26")]),
                chat_chunks("Here is Jaylen Brown's season [r1]."),
            ]
        )
    )  # fmt: skip
    app = ask(page(home, "research"), "How did Brown shoot this season?")
    (asked,) = kept(home)
    assert asked.answer is not None and asked.answer.outcome.value == "clarify"
    assert ollama.chat_payloads == [], "the model is not asked until the name is settled"
    jaylen = next(
        position for position, option in enumerate(asked.answer.options) if option.id == BROWN
    )
    settled(app.button(key=f"ai_option_t{asked.turn_id}_{jaylen}").click().run())
    first, second = kept(home)
    assert second.answer is not None and second.answer.outcome.value != "clarify"
    system = ollama.chat_payloads[0]["messages"][0]["content"]
    assert f'"Brown": player Jaylen Brown (player_id {BROWN})' in system


def test_a_pronoun_with_nothing_to_mean_is_asked_about(model, page, home: Path) -> None:
    """A6: in a workspace's first question, "he" with no one named or chosen is asked
    about rather than guessed."""
    ollama = model(ScriptedOllama())
    app = ask(page(home, "research"), "How did he do last season?")
    assert 'Who do you mean by "he"?' in texts(app)
    assert ollama.chat_payloads == []


def test_a_question_under_way_shows_its_steps_and_can_be_stopped(model, page, home: Path) -> None:
    gate = threading.Event()
    model(Held(gate, chats=[chat_chunks(tool_calls=[HISTORY])]))
    app = page(home, "research")
    app.chat_input(key="ai_question").set_value("How have the Celtics' seasons gone?").run()
    job = app.session_state["ai_job"]
    assert job is not None and not job.done
    assert app.chat_input(key="ai_question").disabled, "one question at a time"
    app.button(key="ai_stop").click().run()
    assert job.stopping
    gate.set()
    assert job.wait(30)
    app.run()
    (turn,) = kept(home)
    assert turn.answer is not None
    assert turn.answer.text.startswith("Stopped before an answer")


def test_an_answer_that_never_came_says_why(model, page, home: Path) -> None:
    model(ScriptedOllama(chats=[OllamaUnavailable("connection reset")]))
    app = ask(page(home, "research"), "How have the Celtics' seasons gone?")
    (turn,) = kept(home)
    assert turn.answer is None and "connection reset" in (turn.error or "")
    assert "No answer" in texts(app)
    assert not app.error, "a failed question is said in the conversation, not as an error box"


def test_a_new_conversation_starts_afresh_and_keeps_the_old_one(model, page, home: Path) -> None:
    model(ScriptedOllama(chats=[NOTHING]))
    app = ask(page(home, "research"), "Hello?")
    assert "Hello?" in texts(app)
    app.button(key="ai_new").click().run()
    assert "Hello?" not in texts(app), "the conversation under way is empty"
    (turn,) = kept(home)
    assert turn.question == "Hello?", "and the earlier one is kept"
    app.toggle(key="ai_show_earlier").set_value(True).run()
    assert "Hello?" in texts(app)
    app.button(key="ai_refresh").click().run()
    assert "Games: none - nothing is fetched in tests" in texts(app)


# --- workspaces ----------------------------------------------------------------------------------


def test_workspaces_keep_their_own_conversations(model, page, home: Path) -> None:
    """A6: no leak between workspaces, on screen or in what a follow-up reads."""
    ollama = model(ScriptedOllama(chats=[NOTHING, NOTHING]))
    app = ask(page(home, "research"), "About the Celtics?")
    first = opened_workspace(app)
    keyed(app.text_input, "ai_new_workspace_name_").set_value("Knicks")
    app.button(key="ai_new_workspace_create").click().run()
    second = opened_workspace(app)
    assert second != first and "Created “Knicks”." in texts(app)
    assert keyed(app.text_input, "ai_new_workspace_name_").value == "", "the form starts again"
    assert "About the Celtics?" not in texts(app)
    ask(app, "About the Knicks?")
    follow_up = ollama.chat_payloads[-1]["messages"]
    assert not any("Celtics" in str(message["content"]) for message in follow_up[1:])
    app.selectbox(key="ai_workspace").set_value(first).run()
    assert "About the Celtics?" in texts(app) and "About the Knicks?" not in texts(app)
    assert [t.question for t in kept(home, second)] == ["About the Knicks?"]


def test_a_workspace_focus_is_what_its_questions_are_about(model, page, home: Path) -> None:
    ollama = model(ScriptedOllama(chats=[NOTHING]))
    app = page(home, "research")
    workspace = opened_workspace(app)
    keyed(app.selectbox, f"ai_ws_team_{workspace}_").set_value(NYK)
    goal = keyed(app.text_area, f"ai_ws_goal_{workspace}_")
    goal.set_value("A Knicks rebuild")
    app.button(key=f"ai_ws_save_{workspace}").click().run()
    said = texts(app)
    assert "A Knicks rebuild" in said and "New York Knicks" in said
    shown = keyed(app.text_area, f"ai_ws_goal_{workspace}_")
    assert shown.key != goal.key and shown.value == "A Knicks rebuild", "drawn from what is kept"
    assert keyed(app.selectbox, f"ai_ws_team_{workspace}_").value == NYK
    ask(app, "How deep is the bench?")
    system = ollama.chat_payloads[0]["messages"][0]["content"]
    assert f"team id {NYK}" in system or f"team_id {NYK}" in system
    (turn,) = kept(home)
    assert turn.focus.team_id == NYK


def test_a_summary_goes_into_the_notes_and_a_later_save_keeps_it(model, page, home: Path) -> None:
    """A6 browser pass: the notes box kept what was typed before the summary, and the next
    Save changes wrote it back over the summary. The form is drawn again from what is kept."""
    model(ScriptedOllama(chats=[NOTHING, chat_chunks("- The user asked; nothing was found.")]))
    app = page(home, "research")
    workspace = opened_workspace(app)
    keyed(app.text_area, f"ai_ws_notes_{workspace}_").set_value("Mine.")
    app.button(key=f"ai_ws_save_{workspace}").click().run()
    ask(app, "Anything?")
    before = keyed(app.text_area, f"ai_ws_notes_{workspace}_")
    app.button(key=f"ai_ws_summarize_{workspace}").click().run()
    assert "The conversation is summarized in the notes." in texts(app)
    notes = keyed(app.text_area, f"ai_ws_notes_{workspace}_")
    assert notes.key != before.key
    assert notes.value.startswith("Mine.\n\nSummary of earlier questions")
    assert notes.value.endswith("- The user asked; nothing was found.")
    app.button(key=f"ai_ws_save_{workspace}").click().run()
    with Lab(load_settings(home)) as lab:
        assert lab.workspaces.get(workspace).notes == notes.value


def test_findings_are_saved_edited_and_deleted(model, page, home: Path) -> None:
    model(ScriptedOllama(chats=[NOTHING]))
    app = ask(page(home, "research"), "Worth keeping?")
    (turn,) = kept(home)
    key = f"t{turn.turn_id}"
    keyed(app.text_input, f"ai_find_title_{key}_").set_value("A finding")
    app.button(key=f"ai_find_save_{key}").click().run()
    assert "Saved “A finding” to the findings." in texts(app)
    assert any(block.label == "Findings (1)" for block in app.status)
    with Lab(load_settings(home)) as lab:
        (finding,) = lab.workspaces.findings(turn.workspace_id)
    keyed(app.text_input, f"ai_f_title_{finding.finding_id}_").set_value("Renamed")
    app.button(key=f"ai_f_save_{finding.finding_id}").click().run()
    assert "Renamed" in texts(app)
    app.button(key=f"ai_f_delete_{finding.finding_id}").click().run()
    assert any(block.label == "Findings (0)" for block in app.status)


def test_history_is_cleared_and_a_workspace_deleted_only_when_ticked(
    model, page, home: Path
) -> None:
    model(ScriptedOllama(chats=[NOTHING]))
    app = ask(page(home, "research"), "Soon forgotten?")
    workspace = opened_workspace(app)
    assert app.button(key=f"ai_ws_clear_{workspace}").disabled
    keyed(app.checkbox, f"ai_ws_clear_ok_{workspace}_").check().run()
    app.button(key=f"ai_ws_clear_{workspace}").click().run()
    assert kept(home, workspace) == () and "Cleared 1 question" in texts(app)
    assert not keyed(app.checkbox, f"ai_ws_clear_ok_{workspace}_").value, "unticked again"
    assert app.button(key=f"ai_ws_delete_{workspace}").disabled
    app.checkbox(key=f"ai_ws_delete_ok_{workspace}").check().run()
    app.button(key=f"ai_ws_delete_{workspace}").click().run()
    assert not app.exception
    with Lab(load_settings(home)) as lab:
        left = [w.workspace_id for w in lab.workspaces.list(archived=None)]
    assert workspace not in left and opened_workspace(app) in left, "another is opened"


def test_a_workspace_is_exported_as_a_document_and_as_data(model, page, home: Path) -> None:
    model(ScriptedOllama(chats=[NOTHING]))
    app = ask(page(home, "research"), "Exported?")
    workspace = opened_workspace(app)
    with Lab(load_settings(home)) as lab:
        markdown = lab.workspaces.export_markdown(workspace)
        document = json.loads(lab.workspaces.export_json(workspace))
    assert "### Exported?" in markdown
    assert [turn["question"] for turn in document["turns"]] == ["Exported?"]
    labels = {button.label for button in app.get("download_button")}
    assert {"Document (Markdown)", "Data (JSON)"} <= labels


def test_an_answer_from_older_data_can_be_asked_again(model, page, home: Path) -> None:
    """A6: an old answer says what changed since, and is asked again beside itself."""
    with Lab(load_settings(home)) as lab:
        workspace = lab.workspaces.default()
        lab.workspaces.record(
            SavedTurn(
                workspace_id=workspace.workspace_id,
                conversation=workspace.conversation,
                asked_at=workspace.created_at,
                question="From an older build?",
                mode=Mode.QUICK,
                focus=Focus(season="2025-26", season_type="regular"),
                asked_from="AI Research",
                answer=Answer("From an older build?", "Old words.", Outcome.SUPPORTED),
                build_id=999,
                value_model="r1",
            )
        )
    model(ScriptedOllama(chats=[NOTHING]))
    app = page(home, "research")
    (old,) = kept(home)
    said = texts(app)
    assert "has been rebuilt since" in said and "build 999 then" in said
    settled(app.button(key=f"ai_again_t{old.turn_id}").click().run())
    first, second = kept(home)
    assert first.answer is not None and first.answer.text == "Old words.", "kept as it was"
    assert second.question == "From an older build?" and second.build_id != 999


# --- roster proposals ----------------------------------------------------------------------------

ROSTERS = tool_call("optimize_roster", budget_mode="custom", budget_millions=150, options=3)


def test_proposed_rosters_are_saved_only_by_the_users_click(model, page, priced_home: Path) -> None:
    """A5: the options are shown with what they rest on; one is saved by its button, once.
    A6: another is declined, and the workspace keeps all three with what was done."""
    model(
        ScriptedOllama(
            chats=[
                chat_chunks(tool_calls=[ROSTERS]),
                chat_chunks("Here are three rosters under the budget [r1]."),
            ]
        )
    )
    app = ask(page(priced_home, "research"), "Propose three rosters under a $150M budget.")
    (turn,) = kept(priced_home)
    assert turn.answer is not None
    (result,) = turn.answer.results
    proposals = result.proposals
    assert len(proposals) == 3
    said = texts(app)
    assert "Rosters to review" in said and "Nothing is saved until you press" in said
    for proposal in proposals:
        assert f"**{proposal.label}** · 2026-27" in said
    tiles = [(metric.label, metric.value, metric.delta) for metric in app.metric]
    first = proposals[0]
    assert ("Projected net rating", f"{first.rating:+.1f}", f"give or take {first.error:.1f}") in (
        tiles
    )
    assert "Asked for: 14 to 15 players. Salaries from your contract file as of" in said
    assert f"in {proposals[1].added[0]}" in said, "an option is compared with Option A"
    assert any(block.label == "Proposed rosters (3, 3 waiting)" for block in app.status)

    key = f"t{turn.turn_id}_r1"
    with Lab(load_settings(priced_home)) as lab:
        assert lab.rosters.list().empty, "nothing is saved before the click"
    app.text_input(key=f"ai_proposal_name_{key}_1").set_value("Option B from the assistant")
    app.button(key=f"ai_proposal_save_{key}_1").click().run()
    assert not app.exception, [error.value for error in app.exception]
    assert any("Saved as" in item.value for item in app.success)
    assert any(block.label == "Proposed rosters (3, 2 waiting)" for block in app.status)
    with Lab(load_settings(priced_home)) as lab:
        rosters = lab.rosters.list()
        assert rosters["name"].tolist() == ["Option B from the assistant"]
        members = lab.rosters.players(int(rosters.iloc[0]["roster_id"]))
    assert set(members["player_id"]) == set(proposals[1].player_ids)

    app.button(key=f"ai_proposal_decline_{key}_2").click().run()
    with Lab(load_settings(priced_home)) as lab:
        records = {r.proposal.label: r.status for r in lab.workspaces.proposals(turn.workspace_id)}
        log = [entry.action for entry in lab.workspaces.approvals(turn.workspace_id)]
    assert records == {"Option A": "draft", "Option B": "saved", "Option C": "declined"}
    assert log == ["saved", "declined"]
    assert any(block.label == "Proposed rosters (3, 1 waiting)" for block in app.status)
    with Lab(load_settings(priced_home)) as lab:
        assert len(lab.rosters.list()) == 1, "a decline saves nothing"


# --- text from outside the lab -------------------------------------------------------------------


def test_a_dollar_is_shown_as_a_dollar_and_an_image_is_not_fetched() -> None:
    assert answers.prose("Tatum earns $40M; Brown $30M.") == "Tatum earns \\$40M; Brown \\$30M."
    assert answers.prose("See ![x](https://example.com/t.png) now") == "See (image left out) now"
    assert answers.escaped("[r1] *bold* $5") == "\\[r1\\] \\*bold\\* \\$5"


def test_a_figure_no_catalog_describes_has_no_tail_of_zeros() -> None:
    # Live at A3: a benchmark's bands showed as 5.000000 and 0.793451.
    assert [answers.plain(v) for v in (5.0, 0.793451, 114.9, 1610.0, float("nan"))] == [
        "5",
        "0.793",
        "114.9",
        "1,610",
        "—",
    ]
