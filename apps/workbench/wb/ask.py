"""Ask AI about this: a question from any page, about what the page shows (decision 0018, A6).

The roadmap's contextual assistant. A page's *Ask AI about this* button opens a dialog that
says what a question will be about - the team, player, season or roster on screen - and
asks it in the workspace open on the AI Research page. The page's choice travels with the
question alone: nothing here changes the sidebar. The answer comes back in the dialog in
short - its kind, its words, its notes - and the rows, charts, evidence and any rosters to
review are in the workspace, one click away. One question runs at a time, wherever it was
asked: the dialog and the AI Research page show the same one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

import front_office.assistant.api as api
from front_office.domain.assistant import Mode
from front_office.domain.research import SavedTurn, Workspace
from front_office.services import WorkspaceService, WorkspaceUnreadable
from wb import answers, components, data, state

RESEARCH: Any = None
"""The AI Research page, handed over by the app for the dialog's *Open in AI Research*."""
QUESTION = "ai_ask_question"
MODE = "ai_ask_mode"
DONE = "ai_ask_done"
"""The answer the dialog last waited for."""
POLL_SECONDS = 1.0
MODES = {Mode.QUICK.value: "Quick", Mode.DEEP.value: "Deep"}


@dataclass(frozen=True, slots=True)
class About:
    """What a page shows, as a question asked from it is about."""

    page: str
    """The page's name, as its tab reads."""
    label: str
    """What it shows, in words: "Boston Celtics, 2025-26 regular season"."""
    season: str
    season_type: str = "regular"
    team_id: int | None = None
    player_id: int | None = None
    roster_id: int | None = None


def from_filters(
    page: str,
    filters: state.Filters,
    *,
    roster_id: int | None = None,
    roster_name: str | None = None,
) -> About:
    """What a page shows when it shows what the sidebar chose - the season and phase, the
    team and the player - and a roster when the page shows one."""
    parts = []
    if filters.player_id is not None:
        players = data.player_options(filters.build, filters.season)
        if filters.player_id in players.index:
            parts.append(str(players.at[filters.player_id, "player_name"]))
    if filters.team_id is not None:
        teams = data.team_labels(filters.build)
        if filters.team_id in teams.index:
            parts.append(str(teams.at[filters.team_id, "full_name"]))
    if roster_id is not None:
        parts.append(f"the roster “{roster_name}”" if roster_name else f"roster {roster_id}")
    parts.append(f"{filters.season} {state.PHASES[filters.season_type].lower()}")
    return About(
        page=page,
        label=", ".join(parts),
        season=filters.season,
        season_type=filters.season_type,
        team_id=filters.team_id,
        player_id=filters.player_id,
        roster_id=roster_id,
    )


def button(about: About, *, key: str = "ai_ask") -> None:
    """The page's *Ask AI about this* button."""
    if st.button(
        "Ask AI about this",
        key=key,
        icon=":material/smart_toy:",
        help=f"Ask the AI assistant about {about.label}. The answer is kept in the workspace "
        "open on the AI Research page; the sidebar does not change.",
    ):
        st.session_state.pop(DONE, None)
        st.session_state.pop(QUESTION, None)
        _dialog(about)


def body(about: About) -> None:
    """What the dialog holds. A plain function, so that a test can draw it inline: a dialog
    reruns alone in a browser, which ``AppTest`` cannot follow."""
    research = data.research()
    try:
        workspace = _open_workspace(research)
    except WorkspaceUnreadable as error:
        components.empty(
            "Your saved research cannot be opened",
            answers.escaped(
                f"The file that keeps your workspaces cannot be read ({error.reason}), so a "
                "question has nowhere to be kept. AI Research can set it aside and start a new "
                "one; nothing is deleted."
            ),
            icon=":material/error:",
        )
        if RESEARCH is not None:
            st.page_link(RESEARCH, label="Open AI Research", icon=":material/open_in_new:")
        return
    st.caption(
        answers.escaped(
            f"About {about.label}. Asked in the workspace “{workspace.name}”; the sidebar does "
            "not change."
        )
    )
    status = data.assistant_status(state.current().build)
    if not status.is_ready:
        components.empty(
            "The assistant cannot answer yet", status.message, icon=":material/power_off:"
        )
        return
    job: api.Job | None = st.session_state.get(state.AI_JOB)
    busy = job is not None and not job.done
    if st.session_state.get(MODE) not in MODES:
        st.session_state[MODE] = Mode.QUICK.value
    # Started through the session state, so that a dialog opened again starts empty in the
    # browser too: a key only forgotten leaves it showing the last question.
    st.session_state.setdefault(QUESTION, "")
    text = st.text_area(
        "Your question",
        key=QUESTION,
        placeholder="For example: how does this compare with last season?",
        disabled=busy,
    )
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        st.segmented_control(
            "Mode", list(MODES), format_func=MODES.get, key=MODE, required=True, disabled=busy
        )
        if (
            st.button("Ask", key="ai_ask_go", type="primary", icon=":material/send:", disabled=busy)
            and text.strip()
        ):
            question = api.Question(
                text.strip(),
                season=about.season,
                season_type=about.season_type,
                team_id=about.team_id,
                player_id=about.player_id,
                roster_id=about.roster_id,
                mode=Mode(st.session_state[MODE]),
                asked_from=about.page,
                about=about.label,
            )
            st.session_state[state.AI_JOB] = api.start(question, workspace.workspace_id)
            st.session_state.pop(DONE, None)
    _answer()


_dialog = st.dialog("Ask AI about this", width="large")(body)


@st.fragment(run_every=POLL_SECONDS)
def _answer() -> None:
    """The question under way, looked in on each second, then its answer in short."""
    job: api.Job | None = st.session_state.get(state.AI_JOB)
    if job is not None and job.done:
        turn = job.turn()
        if job.saved is None:
            st.session_state.setdefault(state.AI_UNKEPT, []).append(turn)
        st.session_state[state.AI_JOB] = None
        st.session_state[DONE] = turn
        job = None
    if job is not None:
        mode = MODES[job.question.mode.value]
        with st.status(f"{mode} answer under way: {job.seconds:.0f} s", expanded=True):
            steps = job.steps
            if not steps:
                st.caption("Reading the question...")
            for step in steps:
                st.markdown(answers.step_line(step))
        if not job.stopping and st.button("Stop", key="ai_ask_stop", icon=":material/stop_circle:"):
            job.stop()
        return
    done: SavedTurn | None = st.session_state.get(DONE)
    if done is None:
        return
    st.divider()
    if done.answer is None:
        components.tagged(
            ("No answer", ":material/error:", "red"),
            answers.escaped(done.error or "Nothing came back."),
        )
    else:
        answers.outcome(done.answer)
        st.markdown(answers.prose(done.answer.text))
        answers.notes(done.answer)
        st.caption(
            "The rows, charts and sources behind it - and any rosters or experiments to review - "
            "are with it in AI Research."
        )
    if RESEARCH is not None:
        # A link, not a button that switches pages: this fragment runs again every second,
        # and a run of it arriving just after ``st.switch_page`` left AI Research blank
        # (A6 browser pass). Whichever way the user goes there next, it opens on the
        # workspace the answer is in.
        st.session_state[state.AI_PARKED] = done.workspace_id
        st.page_link(RESEARCH, label="Open in AI Research", icon=":material/open_in_new:")


def _open_workspace(research: WorkspaceService) -> Workspace:
    """The workspace open on the AI Research page, or the one it would open on."""
    chosen = st.session_state.get(state.AI_WORKSPACE)
    for workspace in research.list():
        if workspace.workspace_id == chosen:
            return workspace
    return research.default()
