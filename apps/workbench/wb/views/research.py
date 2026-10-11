"""AI Research: ask the lab in plain words, keep the research in workspaces, and see what
every answer rests on.

A local model answers from the lab's tools (decision 0018): the lab's data, its fitted
models and its own documents, what has happened since the build, and pages on the web.
Every figure in an answer was checked against the results before it is shown, and
``wb.answers`` draws each answer with what it rests on.

The research is kept in named workspaces (A6), on this computer, apart from the lab's data
so that no build touches it: every question asked in a workspace and the answer it got,
answers bookmarked as findings, rosters proposed and what the user did with each, and the
user's notes. A follow-up reads only the conversation under way in its own workspace. An
old answer says when the data or the model has changed since and can be asked again; it is
never rewritten. A workspace can be renamed, focused on a season, team or roster, exported,
cleared, put away or deleted.

A question runs in the background (``assistant.api.Job``): the page shows its steps as
they come, and can stop it, keeping what was gathered by then.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

import streamlit as st

import front_office.assistant.api as api
from front_office.domain.assistant import Mode, NameCandidate
from front_office.domain.research import (
    RESEARCH_PAGE,
    ExperimentRecord,
    Finding,
    Focus,
    SavedTurn,
    Workspace,
)
from front_office.services import CurrentSource, WorkspaceError, WorkspaceService
from wb import answers, components, data, formats, state
from wb.components import ASSUMPTION, DERIVED, ESTIMATE, MEASURED, MODELED, REPORTED
from wb.state import Filters

JOB = state.AI_JOB
WORKSPACE = state.AI_WORKSPACE
PARKED = state.AI_PARKED
UNKEPT = state.AI_UNKEPT
MODE = "ai_mode"
REFRESHED = "ai_refreshed"
SENT = "ai_forms_sent"
"""How many times a form that starts again empty has been sent, by form: part of its
widgets' keys. A form that shows what is stored has the stored values in its keys instead
(``_stamp``). Either way a form starts again as new widgets: a key only forgotten leaves the
browser showing, and sending back, what was typed - the notes as they were before a summary,
say (A6 browser pass)."""
NOTICE = "ai_notice"
"""What the last action did, said once at the top of the next run."""
EARLIER = "ai_show_earlier"
PROGRESS_SECONDS = 1.0
"""How often a question under way is looked in on."""
TITLE_LENGTH = 60

SUBTITLE = (
    "Ask a question in your own words. An AI model running on this computer answers from the "
    "lab's data, models and documents, the latest league news, and the web. Every number it "
    "gives is checked against those sources before you see it. Your questions and answers are "
    "kept in the workspace you choose, on this computer; nothing is saved to the Team Builder "
    "unless you press a save button."
)
PROMPT = "Ask about players, teams, seasons, forecasts, recent games, injuries, trades or news"
MODES = {Mode.QUICK.value: "Quick", Mode.DEEP.value: "Deep"}
MODE_HELP = (
    "Quick: for one fact or one comparison - up to 3 lookups and about 90 seconds. Deep: for "
    "a longer look at several sources - up to 12 lookups and 5 minutes, thinking it through "
    "first."
)
WORKSPACE_HELP = (
    "A workspace keeps one piece of research: its questions and answers, findings, proposed "
    "rosters, experiment proposals and notes. A follow-up question reads only this "
    "workspace's conversation."
)
NOTES_HELP = (
    "Your notes, and summaries the assistant wrote when you asked. The assistant reads them "
    "as background, never as evidence: no figure in them is taken as checked."
)
READINESS = {
    api.AssistantState.READY: ("Ready", ":material/check_circle:", "green"),
    api.AssistantState.OFFLINE: ("Offline", ":material/power_off:", "red"),
    api.AssistantState.NO_MODEL: ("No model", ":material/download:", "orange"),
    api.AssistantState.MISCONFIGURED: ("Not set up", ":material/error:", "red"),
}
WEB_HELP = (
    "Web search uses your own Ollama account: put FOL_OLLAMA_API_KEY=your key in the "
    "project's .env file. Links you paste into a question are read either way."
)
SOURCES = {
    "games": "Games",
    "transactions": "Transactions",
    "injuries": "Injury report",
    "news": "News",
}
EXAMPLES = (
    "What was the Celtics' net rating in 2025-26, and where did it rank?",
    "Compare Jalen Brunson and Jaylen Brown this season.",
    "How often have teams that won 55 to 60 games won the championship?",
    "What would a team with a +5 net rating expect in the playoffs?",
    "Have the Knicks made any moves since the start of October?",
    "Search the web for reporting on the Knicks' preseason.",
    "Propose three rosters for next season under a $150M budget.",
    "Suggest an experiment that might make the player projections better.",
)
SIDEBAR = "Sidebar's"


def render() -> None:
    filters = state.current()
    _apply_parked()
    _finish()
    status = data.assistant_status(filters.build)
    components.header(
        "AI Research",
        SUBTITLE,
        kinds=[MEASURED, DERIVED, ESTIMATE, MODELED, ASSUMPTION, REPORTED],
    )
    _status(status)
    research = data.research()
    job: api.Job | None = st.session_state.get(JOB)
    workspace = _workspace_bar(research, filters, ready=status.is_ready, busy=job is not None)
    notice = st.session_state.pop(NOTICE, None)
    if notice:
        components.tagged(("Done", ":material/check_circle:", "green"), answers.escaped(notice))
    roster_names = _roster_names()
    _shelf(research, workspace, roster_names)
    turns = research.turns(workspace.workspace_id)
    current = [turn for turn in turns if turn.conversation == workspace.conversation]
    earlier = [turn for turn in turns if turn.conversation != workspace.conversation]
    _controls(research, workspace, busy=job is not None, started=bool(current))
    records = {record.fingerprint: record for record in research.proposals(workspace.workspace_id)}
    kept = {record.fingerprint: record for record in research.experiments(workspace.workspace_id)}
    stamp = research.stamp()
    can_ask = status.is_ready and job is None
    if earlier and st.toggle(
        f"Show earlier conversations ({len(earlier)} questions)",
        key=EARLIER,
        help="Questions from before the conversation under way. A follow-up does not read them.",
    ):
        for turn in earlier:
            _turn(turn, research, can_ask=can_ask, records=records, kept=kept, names=roster_names, stamp=stamp)  # fmt: skip
        st.divider()
    if not current and job is None:
        _welcome(status, workspace)
    for turn in current:
        _turn(turn, research, can_ask=can_ask, records=records, kept=kept, names=roster_names, stamp=stamp)  # fmt: skip
    for turn in st.session_state.get(UNKEPT, []):
        if turn.workspace_id == workspace.workspace_id:
            _turn(turn, research, can_ask=False, records=records, kept=kept, names=roster_names, stamp=stamp)  # fmt: skip
    if job is not None:
        _progress()
    asked = st.chat_input(PROMPT, key="ai_question", disabled=not can_ask)
    if asked and asked.strip():
        _start(_question(asked.strip(), filters, workspace), workspace.workspace_id)


def _question(text: str, filters: Filters, workspace: Workspace) -> api.Question:
    """A question from this page: about the workspace's focus where it has one, and the
    sidebar's choices for the rest."""
    sidebar = Focus(
        season=filters.season,
        season_type=filters.season_type,
        team_id=filters.team_id,
        player_id=filters.player_id,
    )
    focus = workspace.focus.over(sidebar)
    return api.Question(
        text,
        season=focus.season or filters.season,
        season_type=focus.season_type or filters.season_type,
        team_id=focus.team_id,
        player_id=focus.player_id,
        roster_id=focus.roster_id,
        mode=Mode(st.session_state.get(MODE, Mode.QUICK.value)),
    )


def _start(question: api.Question, workspace_id: int) -> None:
    st.session_state[JOB] = api.start(question, workspace_id)
    st.rerun()


def _finish() -> None:
    """A question finished in the background is kept in its workspace by the job; one that
    could not be kept is shown for the session."""
    job: api.Job | None = st.session_state.get(JOB)
    if job is not None and job.done:
        if job.saved is None:
            st.session_state.setdefault(UNKEPT, []).append(job.turn())
        st.session_state[JOB] = None


def _apply_parked() -> None:
    """What an action decided after the widgets it changes were drawn, applied before they
    are drawn again."""
    if PARKED in st.session_state:
        st.session_state[WORKSPACE] = st.session_state.pop(PARKED)


def _sent(form: str) -> int:
    """How many times ``form`` has been sent this session (``SENT``)."""
    return st.session_state.get(SENT, {}).get(form, 0)


def _stamp(*stored: object) -> str:
    """What a form shows, as a few characters for its widgets' keys (``SENT``)."""
    return hashlib.sha256(repr(stored).encode("utf-8")).hexdigest()[:10]


def _after(notice: str, *, show: int | None = None, sent: str | None = None) -> None:
    """Say what was done at the top of the next run, open workspace ``show``, and start
    form ``sent`` again empty."""
    st.session_state[NOTICE] = notice
    if show is not None:
        st.session_state[PARKED] = show
    if sent is not None:
        counts = st.session_state.setdefault(SENT, {})
        counts[sent] = counts.get(sent, 0) + 1
    st.rerun()


# --- where things stand ----------------------------------------------------------------------


def _status(status: api.AssistantStatus) -> None:
    word, icon, color = READINESS[status.state]
    with st.container(horizontal=True, gap="small"):
        st.badge(f"Assistant: {word.lower()}", icon=icon, color=color, help=status.message)
        st.badge(
            "Web search: set up" if status.web_search else "Web search: not set up",
            icon=":material/travel_explore:",
            color="green" if status.web_search else "gray",
            help=WEB_HELP,
        )
        for source in data.current_sources():
            name = SOURCES.get(source.source, source.source)
            components.state_badge(source.state, f"{name}: {_source_state(source)}")
    if not status.is_ready:
        components.empty("The assistant cannot answer yet", status.message, icon=icon)
    for refreshed in st.session_state.get(REFRESHED, ()):
        name = SOURCES.get(refreshed.source, refreshed.source)
        st.caption(f"{name}: {refreshed.status} - {answers.escaped(refreshed.detail)}")


def _source_state(source: CurrentSource) -> str:
    if source.stored_at is None:
        return "never fetched" if source.state == "absent" else "failing"
    return f"as of {formats.moment(source.stored_at)}"


# --- the workspace ----------------------------------------------------------------------------


def _workspace_bar(
    research: WorkspaceService, filters: Filters, *, ready: bool, busy: bool
) -> Workspace:
    listed = list(research.list()) or [research.default()]
    by_id = {workspace.workspace_id: workspace for workspace in listed}
    if st.session_state.get(WORKSPACE) not in by_id:
        st.session_state[WORKSPACE] = listed[0].workspace_id
    with st.container(horizontal=True, gap="small", vertical_alignment="bottom"):
        chosen = st.selectbox(
            "Workspace",
            list(by_id),
            format_func=lambda key: by_id[key].name,
            key=WORKSPACE,
            help=WORKSPACE_HELP,
            disabled=busy,
        )
        workspace = by_id[chosen]
        _new_workspace(research, busy=busy)
        _settings(research, workspace, filters, ready=ready, busy=busy)
        _export(research, workspace)
        _put_away(research, workspace, busy=busy)
    st.caption(_about(workspace, filters))
    return workspace


def _new_workspace(research: WorkspaceService, *, busy: bool) -> None:
    sent = _sent("new_workspace")
    with st.popover("New workspace", icon=":material/add:", disabled=busy):
        name = st.text_input("Name", max_chars=60, key=f"ai_new_workspace_name_{sent}")
        goal = st.text_area(
            "What you are working on (optional)",
            max_chars=400,
            key=f"ai_new_workspace_goal_{sent}",
        )
        if st.button("Create workspace", key="ai_new_workspace_create", type="primary"):
            try:
                made = research.create(name, goal=goal or None)
            except WorkspaceError as error:
                st.error(str(error), icon=":material/error:")
            else:
                _after(f"Created “{made.name}”.", show=made.workspace_id, sent="new_workspace")


def _settings(
    research: WorkspaceService,
    workspace: Workspace,
    filters: Filters,
    *,
    ready: bool,
    busy: bool,
) -> None:
    key = workspace.workspace_id
    focus = workspace.focus
    shown = _stamp(
        workspace.name,
        workspace.goal,
        workspace.notes,
        focus.season,
        focus.season_type,
        focus.team_id,
        focus.roster_id,
    )
    with st.popover("Workspace", icon=":material/tune:", disabled=busy):
        st.caption(
            "Its name, what you are working on, and what its questions are about when they name "
            "nothing. Left to the sidebar, they follow the sidebar."
        )
        name = st.text_input(
            "Name", value=workspace.name, max_chars=60, key=f"ai_ws_name_{key}_{shown}"
        )
        goal = st.text_area(
            "What you are working on",
            value=workspace.goal or "",
            max_chars=400,
            key=f"ai_ws_goal_{key}_{shown}",
        )
        seasons = [None, *data.status().team_seasons]
        season = st.selectbox(
            "Season",
            seasons,
            index=_position(seasons, focus.season),
            format_func=lambda value: f"{SIDEBAR} season" if value is None else value,
            key=f"ai_ws_season_{key}_{shown}",
        )
        phases = [None, *state.PHASES]
        phase = st.selectbox(
            "Phase",
            phases,
            index=_position(phases, focus.season_type),
            format_func=lambda value: f"{SIDEBAR} phase" if value is None else state.PHASES[value],
            key=f"ai_ws_phase_{key}_{shown}",
        )
        teams = data.team_labels(filters.build)
        team_ids = [None, *sorted(teams.index, key=lambda team: teams.at[team, "full_name"])]
        team = st.selectbox(
            "Team",
            team_ids,
            index=_position(team_ids, focus.team_id),
            format_func=lambda value: (
                f"{SIDEBAR} team" if value is None else str(teams.at[value, "full_name"])
            ),
            key=f"ai_ws_team_{key}_{shown}",
        )
        rosters = _roster_names()
        roster_ids = [None, *rosters]
        roster = st.selectbox(
            "Team Builder roster",
            roster_ids,
            index=_position(roster_ids, focus.roster_id),
            format_func=lambda value: "None" if value is None else rosters[value],
            key=f"ai_ws_roster_{key}_{shown}",
            help="A roster the workspace's questions are about when they name none: its fit, "
            "its chances, a scenario for it.",
        )
        notes = st.text_area(
            "Notes",
            value=workspace.notes or "",
            height=160,
            key=f"ai_ws_notes_{key}_{shown}",
            help=NOTES_HELP,
        )
        if st.button("Save changes", key=f"ai_ws_save_{key}", type="primary"):
            try:
                saved = research.update(
                    key,
                    name=name,
                    goal=goal or None,
                    notes=notes or None,
                    focus=replace(
                        workspace.focus,
                        season=season,
                        season_type=phase,
                        team_id=None if team is None else int(team),
                        roster_id=None if roster is None else int(roster),
                    ),
                )
            except (WorkspaceError, ValueError) as error:
                st.error(str(error), icon=":material/error:")
            else:
                _after(f"Saved “{saved.name}”.")
        st.divider()
        st.caption(
            "Summarize: the assistant writes the conversation under way into the notes, marked "
            "as its summary, and a new conversation begins that reads the notes instead."
        )
        if st.button(
            "Summarize into the notes",
            key=f"ai_ws_summarize_{key}",
            icon=":material/summarize:",
            disabled=not ready,
        ):
            with st.spinner("Summarizing..."):
                try:
                    api.summarize(key)
                except api.SummaryError as error:
                    st.warning(str(error), icon=":material/warning:")
                else:
                    _after("The conversation is summarized in the notes.")


def _export(research: WorkspaceService, workspace: Workspace) -> None:
    slug = re.sub(r"[^0-9a-z]+", "_", workspace.name.lower()).strip("_") or "workspace"
    with st.popover("Export", icon=":material/download:"):
        st.caption(
            "Everything the workspace holds: as a document to read, or as data. Each answer "
            "says which data build and model it read."
        )
        st.download_button(
            "Document (Markdown)",
            research.export_markdown(workspace.workspace_id),
            file_name=f"{slug}.md",
            mime="text/markdown",
            key=f"ai_export_md_{workspace.workspace_id}",
            icon=":material/description:",
        )
        st.download_button(
            "Data (JSON)",
            research.export_json(workspace.workspace_id),
            file_name=f"{slug}.json",
            mime="application/json",
            key=f"ai_export_json_{workspace.workspace_id}",
            icon=":material/data_object:",
        )


def _put_away(research: WorkspaceService, workspace: Workspace, *, busy: bool) -> None:
    key = workspace.workspace_id
    with st.popover("Archive or delete", icon=":material/inventory_2:", disabled=busy):
        if st.button("Archive this workspace", key=f"ai_ws_archive_{key}"):
            research.update(key, archived=True)
            _after(f"Archived “{workspace.name}”. Restore it here any time.")
        archived = research.list(archived=True)
        if archived:
            st.caption("Archived workspaces")
            for kept in archived:
                if st.button(f"Restore “{kept.name}”", key=f"ai_ws_restore_{kept.workspace_id}"):
                    research.update(kept.workspace_id, archived=False)
                    _after(f"Restored “{kept.name}”.", show=kept.workspace_id)
        st.divider()
        clear = st.checkbox(
            "Forget this workspace's questions and answers (notes, findings and proposed "
            "rosters stay)",
            # Clearing begins a new conversation, and with it an unticked box.
            key=f"ai_ws_clear_ok_{key}_{workspace.conversation}",
        )
        if st.button("Clear history", key=f"ai_ws_clear_{key}", disabled=not clear):
            gone = research.clear_history(key)
            _after(f"Cleared {gone} question{'s' if gone != 1 else ''} from “{workspace.name}”.")
        delete = st.checkbox(
            "Delete this workspace and everything in it (rosters saved from it stay in the Team "
            "Builder)",
            key=f"ai_ws_delete_ok_{key}",
        )
        if st.button(
            "Delete workspace", key=f"ai_ws_delete_{key}", type="primary", disabled=not delete
        ):
            research.delete(key)
            _after(f"Deleted “{workspace.name}”.")


def _about(workspace: Workspace, filters: Filters) -> str:
    """What the workspace is for, and what its questions are about when they name nothing."""
    focus = workspace.focus
    parts = []
    season = focus.season or filters.season
    phase = state.PHASES.get(focus.season_type or filters.season_type, "")
    parts.append(
        f"{season} {phase.lower()}" + ("" if focus.season or focus.season_type else " (sidebar)")
    )
    if focus.team_id is not None:
        parts.append(_team_name(filters, focus.team_id))
    elif filters.team_id is not None:
        parts.append(f"{_team_name(filters, filters.team_id)} (sidebar)")
    if focus.roster_id is not None:
        parts.append(f"roster “{_roster_names().get(focus.roster_id, 'deleted')}”")
    said = "Questions that name nothing are about: " + " · ".join(parts) + "."
    if workspace.goal:
        said = f"{workspace.goal} - {said}"
    return answers.escaped(said)


def _team_name(filters: Filters, team_id: int) -> str:
    teams = data.team_labels(filters.build)
    return str(teams.at[team_id, "full_name"]) if team_id in teams.index else f"team {team_id}"


def _roster_names() -> dict[int, str]:
    rosters = data.rosters()
    return {int(row["roster_id"]): str(row["name"]) for _, row in rosters.iterrows()}


def _position(options: list, value: object) -> int:
    """Where the stored choice is in the list; the first, the sidebar's, when it is gone."""
    return options.index(value) if value in options else 0


# --- what the workspace keeps -----------------------------------------------------------------


def _shelf(research: WorkspaceService, workspace: Workspace, names: dict[int, str]) -> None:
    findings = research.findings(workspace.workspace_id)
    held = research.proposals(workspace.workspace_id)
    waiting = sum(record.status == "draft" for record in held)
    with st.expander(f"Findings ({len(findings)})", icon=":material/bookmark:"):
        if not findings:
            st.caption(
                "None yet. To keep an answer worth keeping, press Save as finding under it: a "
                "copy stays here even if the history is cleared."
            )
        for finding in findings:
            _finding(research, finding)
    label = f"Proposed rosters ({len(held)}" + (f", {waiting} waiting)" if waiting else ")")
    with st.expander(label, icon=":material/groups:"):
        if not held:
            st.caption(
                "None yet. Ask for rosters under a budget, and the options are kept here until "
                "you save or decline each."
            )
        for record in held:
            answers.proposal_card(
                record.proposal,
                record.proposal,
                key=f"w{workspace.workspace_id}_{record.fingerprint}",
                workspace_id=workspace.workspace_id,
                record=record,
                roster_names=names,
            )
    kept = research.experiments(workspace.workspace_id)
    with st.expander(f"Experiment proposals ({len(kept)})", icon=":material/science:"):
        if not kept:
            st.caption(
                "None yet. Ask for an experiment that might improve one of the lab's models, "
                "and press Keep in the workspace under a proposal you want to come back to. "
                "Keeping one changes no model."
            )
        for experiment in kept:
            _experiment(research, experiment)


def _finding(research: WorkspaceService, finding: Finding) -> None:
    key = finding.finding_id
    with st.container(border=True):
        st.markdown(f"**{answers.escaped(finding.title)}**")
        asked = f"Asked {formats.moment(finding.asked_at)}: {finding.question}"
        if finding.build_id is not None:
            asked += f" · data build {finding.build_id}"
        st.caption(answers.escaped(asked))
        if finding.note:
            st.markdown(f"*{answers.escaped(finding.note)}*")
        if finding.answer_text:
            st.markdown(answers.prose(finding.answer_text))
        if finding.evidence:
            st.caption(answers.escaped("Rests on: " + "; ".join(finding.evidence.splitlines())))
        with st.container(horizontal=True, gap="small"):
            with st.popover("Edit", icon=":material/edit:"):
                shown = _stamp(finding.title, finding.note)
                title = st.text_input(
                    "Title",
                    value=finding.title,
                    max_chars=TITLE_LENGTH,
                    key=f"ai_f_title_{key}_{shown}",
                )
                note = st.text_area(
                    "Note", value=finding.note or "", key=f"ai_f_note_{key}_{shown}"
                )
                if st.button("Save", key=f"ai_f_save_{key}", type="primary"):
                    try:
                        research.update_finding(key, title=title, note=note or None)
                    except WorkspaceError as error:
                        st.error(str(error), icon=":material/error:")
                    else:
                        _after("Finding saved.")
            if st.button("Delete", key=f"ai_f_delete_{key}", icon=":material/delete:"):
                research.delete_finding(key)
                _after("Finding deleted.")


def _experiment(research: WorkspaceService, record: ExperimentRecord) -> None:
    key = record.experiment_id
    answers.experiment_card(record.proposal, key=f"kept_{key}", record=record)
    if record.note:
        st.markdown(f"*{answers.escaped(record.note)}*")
    with st.container(horizontal=True, gap="small"):
        with st.popover("Note", icon=":material/edit:"):
            shown = _stamp(record.note)
            note = st.text_area("Note", value=record.note or "", key=f"ai_x_note_{key}_{shown}")
            if st.button("Save", key=f"ai_x_save_{key}", type="primary"):
                research.annotate_experiment(key, note or None)
                _after("Note saved.")
        if st.button("Delete", key=f"ai_x_delete_{key}", icon=":material/delete:"):
            research.delete_experiment(key)
            _after("Experiment proposal deleted.")


def _controls(
    research: WorkspaceService, workspace: Workspace, *, busy: bool, started: bool
) -> None:
    if st.session_state.get(MODE) not in MODES:
        st.session_state[MODE] = Mode.QUICK.value
    with st.container(horizontal=True, gap="medium", vertical_alignment="bottom"):
        st.segmented_control(
            "Mode", list(MODES), format_func=MODES.get, key=MODE, required=True, help=MODE_HELP
        )
        if st.button(
            "New conversation",
            key="ai_new",
            icon=":material/add_comment:",
            disabled=busy or not started,
            help="Start afresh: the next question follows no earlier one. Earlier questions stay "
            "in the workspace.",
        ):
            research.new_conversation(workspace.workspace_id)
            st.session_state.pop(REFRESHED, None)
            st.rerun()
        if st.button(
            "Fetch current information",
            key="ai_refresh",
            icon=":material/sync:",
            disabled=busy,
            help="Fetch what is due of this season's games, the league's transactions and its "
            "injury report. Questions fetch what they need anyway.",
        ):
            with st.spinner("Fetching what is due..."):
                st.session_state[REFRESHED] = api.refresh_current()
            st.rerun()


def _welcome(status: api.AssistantStatus, workspace: Workspace) -> None:
    examples = "\n".join(f"- {answers.escaped(example)}" for example in EXAMPLES)
    body = (
        "The assistant reads names, seasons and teams from your question; where you name none, "
        "it uses this workspace's focus or the sidebar's season and team. If a name could mean "
        "more than one player, it asks which one first. A follow-up question reads the "
        "conversation under way in this workspace, and nothing else.\n\nFor example:\n" + examples
    )
    with st.container(border=True):
        st.markdown(f":material/forum: **Ask a question in “{answers.escaped(workspace.name)}”**")
        st.markdown(body)


# --- the conversation --------------------------------------------------------------------------


def _turn(
    turn: SavedTurn,
    research: WorkspaceService,
    *,
    can_ask: bool,
    records: dict,
    kept: dict,
    names: dict[int, str],
    stamp: tuple[int | None, str | None],
) -> None:
    key = f"t{turn.turn_id}" if turn.turn_id is not None else f"u{id(turn)}"
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(answers.prose(turn.question))
        st.caption(answers.escaped(_asked(turn)))
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        if turn.answer is None:
            components.tagged(
                ("No answer", ":material/error:", "red"),
                answers.escaped(turn.error or "Nothing came back."),
            )
        else:

            def choose(option: NameCandidate) -> None:
                again = api.Question.again(turn)
                _start(replace(again, resolved=(*again.resolved, option)), turn.workspace_id)

            answers.draw(
                turn.answer,
                key=key,
                steps=turn.steps,
                seconds=turn.seconds,
                can_ask=can_ask,
                choose=choose,
                workspace_id=turn.workspace_id,
                records=records,
                roster_names=names,
                turn_id=turn.turn_id,
                kept=kept,
            )
        if turn.turn_id is not None:
            _turn_actions(turn, research, key=key, can_ask=can_ask, stamp=stamp)


def _turn_actions(
    turn: SavedTurn,
    research: WorkspaceService,
    *,
    key: str,
    can_ask: bool,
    stamp: tuple[int | None, str | None],
) -> None:
    changed = research.changed_since(turn, stamp=stamp)
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        if turn.answer is not None:
            with st.popover("Save as finding", icon=":material/bookmark_add:"):
                sent = _sent(f"finding_{key}")
                title = st.text_input(
                    "Title",
                    value=turn.question[:TITLE_LENGTH],
                    max_chars=TITLE_LENGTH,
                    key=f"ai_find_title_{key}_{sent}",
                )
                note = st.text_area("Note (optional)", key=f"ai_find_note_{key}_{sent}")
                if st.button("Save finding", key=f"ai_find_save_{key}", type="primary"):
                    try:
                        research.save_finding(turn, title, note or None)
                    except WorkspaceError as error:
                        st.error(str(error), icon=":material/error:")
                    else:
                        _after(f"Saved “{title.strip()}” to the findings.", sent=f"finding_{key}")
        if changed and st.button(
            "Ask again with today's data",
            key=f"ai_again_{key}",
            icon=":material/refresh:",
            disabled=not can_ask,
            help="Asks the same question again; this answer stays as it was.",
        ):
            _start(api.Question.again(turn), turn.workspace_id)
    if changed:
        st.caption(answers.escaped(" ".join(changed)))


def _asked(turn: SavedTurn) -> str:
    """When and how a kept question was asked, and what it was about."""
    focus = turn.focus
    phase = state.PHASES.get(focus.season_type or "", focus.season_type or "")
    parts = [MODES[turn.mode.value], f"{focus.season} {phase.lower()}".strip()]
    if turn.asked_from != RESEARCH_PAGE:
        parts.append(
            f"asked from {turn.asked_from}" + (f" about {turn.about}" if turn.about else "")
        )
    parts.append(formats.moment(turn.asked_at))
    return " · ".join(part for part in parts if part)


@st.fragment(run_every=PROGRESS_SECONDS)
def _progress() -> None:
    """The question under way: its steps as they come, and a way to stop it."""
    job: api.Job | None = st.session_state.get(JOB)
    if job is None:
        return
    if job.done:
        st.rerun()  # the whole page, which takes the finished answer in
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(answers.prose(job.question.text))
        where = ""
        if st.session_state.get(WORKSPACE) != job.workspace_id:
            where = " · in another workspace"
        st.caption(answers.escaped(f"{MODES[job.question.mode.value]}{where}"))
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        mode = MODES[job.question.mode.value]
        with st.status(f"{mode} answer under way: {job.seconds:.0f} s", expanded=True):
            steps = job.steps
            if not steps:
                st.caption("Reading the question...")
            for step in steps:
                st.markdown(answers.step_line(step))
        if job.stopping:
            st.caption("Stopping at the next step; what was gathered by then is kept.")
        elif st.button(
            "Stop",
            key="ai_stop",
            icon=":material/stop_circle:",
            help="Stop at the next step and keep what was gathered. A step under way - the "
            "model writing - finishes first.",
        ):
            job.stop()
            st.rerun(scope="fragment")
