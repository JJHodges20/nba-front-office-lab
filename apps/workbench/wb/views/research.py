"""AI Research: ask the lab in plain words, and see what every answer rests on.

A local model answers from the lab's tools (decision 0018): the lab's data, what has
happened since the build, and pages on the web. Every figure in an answer was checked
against the results before it is shown. Under each answer the page draws what it rests on:
each result's rows, a chart where the tool chose one, and the evidence - sources, dates,
the build. The conversation lasts as long as this browser tab, and nothing is saved.

A question runs in the background (``assistant.api.Job``): the page shows its steps as
they come, and can stop it, keeping what was gathered by then.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import front_office.assistant.api as api
from front_office.domain.assistant import (
    Answer,
    Chart,
    Evidence,
    EvidenceKind,
    Mode,
    NameCandidate,
    Outcome,
    ResultStatus,
    Step,
    ToolResult,
)
from front_office.domain.metrics import MetricSpec
from front_office.services import METRIC_CATALOGS, CurrentSource
from wb import charts, components, data, formats, state
from wb.components import DERIVED, ESTIMATE, MEASURED, REPORTED
from wb.theme import Palette

TURNS = "ai_turns"
JOB = "ai_job"
MODE = "ai_mode"
REFRESHED = "ai_refreshed"
PROGRESS_SECONDS = 1.0
"""How often a question under way is looked in on."""
TAB_LABEL = 38
"""Characters of a result's title on its tab."""

SUBTITLE = (
    "Ask in plain words. A model on this machine answers from the lab's data, what has "
    "happened since the last build, and pages on the web; every figure it gives is checked "
    "against those results before it is shown. The conversation lasts until this tab is "
    "closed or reloaded, and nothing is saved."
)
PROMPT = "Ask about players, teams, seasons, recent games, injuries, moves or reporting"
MODES = {Mode.QUICK.value: "Quick", Mode.DEEP.value: "Deep"}
MODE_HELP = (
    "Quick: one fact or one comparison - up to 3 tool calls and 90 seconds. Deep: several "
    "sources or a longer look - up to 12 calls and 5 minutes, with the model thinking first."
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
SOURCES = {"games": "Games", "transactions": "Transactions", "injuries": "Injury report"}
OUTCOMES = {
    Outcome.SUPPORTED: (
        "Supported",
        ":material/verified:",
        "green",
        "Answered from the results; every figure checked.",
    ),
    Outcome.QUALIFIED: (
        "Qualified",
        ":material/info:",
        "orange",
        "Partly answered: what is missing, limited, stale or estimated is said.",
    ),
    Outcome.INSUFFICIENT: (
        "Not enough to answer",
        ":material/help:",
        "gray",
        "Nothing in the results answers it. What is missing is said; nothing is invented.",
    ),
    Outcome.CLARIFY: (
        "Question back",
        ":material/contact_support:",
        "blue",
        "A name in the question has several readings: choose the one you mean.",
    ),
    Outcome.DECLINED: (
        "Declined",
        ":material/block:",
        "gray",
        "Something the assistant does not do: run SQL or code, open files, save or change "
        "anything, refit a model.",
    ),
}
STEPS = {
    "clarify": ":material/contact_support:",
    "model": ":material/psychology:",
    "tool": ":material/build:",
    "repair": ":material/healing:",
    "check": ":material/rule:",
}
EVIDENCE = {
    EvidenceKind.LAB: "The lab's data",
    EvidenceKind.MODEL: "A fitted model",
    EvidenceKind.CONTRACTS: "Your contract file",
    EvidenceKind.CURRENT: "Current information",
    EvidenceKind.WEB: "The web",
}
EXAMPLES = (
    "What was the Celtics' net rating in 2025-26, and where did it rank?",
    "Compare Jalen Brunson and Jaylen Brown this season.",
    "How often have teams that won 55 to 60 games won the championship?",
    "Have the Knicks made any moves since the start of October?",
    "Search the web for reporting on the Knicks' preseason.",
)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
SPECIAL = re.compile(r"([\\`*_\[\]()#+!|~<>$-])")


def render() -> None:
    filters = state.current()
    _finish()
    status = data.assistant_status(filters.build)
    components.header("AI Research", SUBTITLE, kinds=[MEASURED, DERIVED, ESTIMATE, REPORTED])
    _status(status)
    turns: list[api.Turn] = st.session_state.setdefault(TURNS, [])
    job: api.Job | None = st.session_state.get(JOB)
    _controls(turns, busy=job is not None)
    if not turns and job is None:
        _welcome(status)
    for number, turn in enumerate(turns):
        _turn(number, turn, can_ask=status.is_ready and job is None)
    if job is not None:
        _progress()
    asked = st.chat_input(
        PROMPT, key="ai_question", disabled=not status.is_ready or job is not None
    )
    if asked and asked.strip():
        question = api.Question(
            asked.strip(),
            season=filters.season,
            season_type=filters.season_type,
            team_id=filters.team_id,
            player_id=filters.player_id,
            mode=Mode(st.session_state.get(MODE, Mode.QUICK.value)),
        )
        _start(question)


def _start(question: api.Question) -> None:
    st.session_state[JOB] = api.start(question, st.session_state.get(TURNS, []))
    st.rerun()


def _finish() -> None:
    """A question finished in the background joins the conversation."""
    job: api.Job | None = st.session_state.get(JOB)
    if job is not None and job.done:
        st.session_state.setdefault(TURNS, []).append(job.turn())
        st.session_state[JOB] = None


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
        st.caption(f"{name}: {refreshed.status} - {_escaped(refreshed.detail)}")


def _source_state(source: CurrentSource) -> str:
    if source.stored_at is None:
        return "never fetched" if source.state == "absent" else "failing"
    return f"as of {formats.moment(source.stored_at)}"


def _controls(turns: list[api.Turn], *, busy: bool) -> None:
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
            disabled=busy or not turns,
            help="Start again; the answers so far are cleared from this page.",
        ):
            st.session_state[TURNS] = []
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


def _welcome(status: api.AssistantStatus) -> None:
    examples = "\n".join(f"- {_escaped(example)}" for example in EXAMPLES)
    body = (
        "Names, seasons and teams are read from the question, and the sidebar's season and "
        "team stand in where it names none. A name that could be several players is asked "
        "about before anything runs.\n\nFor example:\n" + examples
    )
    with st.container(border=True):
        st.markdown(":material/forum: **Ask a question**")
        st.markdown(body)


# --- the conversation --------------------------------------------------------------------------


def _turn(number: int, turn: api.Turn, *, can_ask: bool) -> None:
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(_prose(turn.question.text))
        st.caption(_asked_about(turn.question))
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        if turn.answer is None:
            components.tagged(
                ("No answer", ":material/error:", "red"),
                _escaped(turn.error or "Nothing came back."),
            )
            return
        answer = turn.answer
        word, icon, color, meaning = OUTCOMES[answer.outcome]
        with st.container(horizontal=True, gap="small"):
            st.badge(word, icon=icon, color=color, help=meaning)
            kinds = sorted(
                {kind for result in answer.results if result.usable for kind in result.kinds}
                & set(components.PROVENANCE)
            )
            components.provenance(kinds)
        st.markdown(_prose(answer.text))
        if answer.outcome is Outcome.CLARIFY:
            _options(number, turn, can_ask=can_ask)
        for note in answer.warnings:
            components.tagged(("Note", ":material/info:", "gray"), _escaped(note))
        _results(number, answer)
        _evidence(answer)
        _workings(turn)


def _asked_about(question: api.Question) -> str:
    phase = state.PHASES.get(question.season_type, question.season_type)
    return f"{MODES[question.mode.value]} · sidebar: {question.season} {phase.lower()}"


def _options(number: int, turn: api.Turn, *, can_ask: bool) -> None:
    assert turn.answer is not None
    st.caption("Choose the one you mean, and the question is asked again with it.")
    with st.container(horizontal=True, gap="small"):
        for position, option in enumerate(turn.answer.options):
            if st.button(
                option.name,
                key=f"ai_option_{number}_{position}",
                disabled=not can_ask,
                help=_option_help(option),
            ):
                _start(replace(turn.question, resolved=(*turn.question.resolved, option)))


def _option_help(option: NameCandidate) -> str:
    kind = {"player": "The player", "team": "The team", "season": "The season"}[option.kind]
    return f'{kind} {option.name}, for "{option.text}".'


@st.fragment(run_every=PROGRESS_SECONDS)
def _progress() -> None:
    """The question under way: its steps as they come, and a way to stop it."""
    job: api.Job | None = st.session_state.get(JOB)
    if job is None:
        return
    if job.done:
        st.rerun()  # the whole page, which takes the finished answer in
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(_prose(job.question.text))
        st.caption(_asked_about(job.question))
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        mode = MODES[job.question.mode.value]
        with st.status(f"{mode} answer under way: {job.seconds:.0f} s", expanded=True):
            steps = job.steps
            if not steps:
                st.caption("Reading the question...")
            for step in steps:
                st.markdown(_step_line(step))
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


def _step_line(step: Step) -> str:
    took = f" ({step.seconds:.1f} s)" if step.seconds >= 0.1 else ""
    return f"{STEPS.get(step.kind, ':material/circle:')} {_escaped(_step_words(step))}{took}"


def _step_words(step: Step) -> str:
    if step.kind == "model":
        return (
            "The model wrote the answer"
            if step.detail == "answered"
            else f"The model {step.detail}"
        )
    if step.kind == "tool":
        return f"Ran {step.detail}"
    if step.kind == "repair":
        return f"Sent back to the model: {step.detail}"
    if step.kind == "check":
        return f"Checked: {step.detail}"
    return step.detail


# --- what an answer rests on --------------------------------------------------------------------


def _results(number: int, answer: Answer) -> None:
    shown = [result for result in answer.results if _has_rows(result)]
    if not shown:
        return
    st.markdown("**What it rests on**")
    tabs = st.tabs([_tab_label(result) for result in shown])
    for tab, result in zip(tabs, shown, strict=True):
        with tab:
            if len(result.title) > TAB_LABEL:  # the tab could not say it in full
                st.caption(_escaped(result.title))
            for position, chart in enumerate(result.charts):
                _chart(chart, key=f"ai_chart_{number}_{result.result_id}_{position}")
            if result.table is not None and not result.table.empty:
                _rows(result.table, key=f"ai_table_{number}_{result.result_id}")
                components.export(
                    result.table,
                    f"{result.tool}_{result.result_id}",
                    key=f"ai_csv_{number}_{result.result_id}",
                    label="Rows (CSV)",
                )


def _rows(table: pd.DataFrame, *, key: str) -> None:
    """A result's rows as the workbench writes them: a metric under its label and in its
    format, any other column in words, the lab's internal ids left to the CSV."""
    shown = table[[column for column in table.columns if not str(column).endswith("_id")]]
    shown = shown.reset_index(drop=True)
    specs = {
        column: spec
        for column in shown.columns
        if (spec := _spec(str(column))) is not None
        and pd.api.types.is_numeric_dtype(shown[column])
        and not pd.api.types.is_bool_dtype(shown[column])
    }
    headings = {
        column: st.column_config.Column(
            specs[column].label if column in specs else _words(str(column)),
            help=f"{specs[column].name}. {specs[column].description}" if column in specs else None,
        )
        for column in shown.columns
    }
    plain = {
        column: _plain
        for column in shown.columns
        if column not in specs
        and pd.api.types.is_numeric_dtype(shown[column])
        and not pd.api.types.is_bool_dtype(shown[column])
    }
    styled = shown.style.format(
        {**plain, **{column: spec.format_value for column, spec in specs.items()}},
        na_rep=components.EMPTY_CELL,
    )
    st.dataframe(
        styled,
        hide_index=True,
        column_config=headings,
        placeholder=components.EMPTY_CELL,
        key=key,
    )


def _plain(value: object) -> str:
    """A figure no catalog describes, without a tail of zeros: 5, 0.793, 114.9."""
    if formats.is_missing(value):
        return components.EMPTY_CELL
    number = float(value)  # type: ignore[arg-type]
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.3f}".rstrip("0").rstrip(".")


def _words(column: str) -> str:
    text = column.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _has_rows(result: ToolResult) -> bool:
    if result.status not in (ResultStatus.OK, ResultStatus.EMPTY):
        return False
    return bool(result.charts) or (result.table is not None and not result.table.empty)


def _tab_label(result: ToolResult) -> str:
    title = result.title
    short = title if len(title) <= TAB_LABEL else title[: TAB_LABEL - 1].rstrip() + "…"
    return f"{result.result_id} · {short}"


def _chart(chart: Chart, *, key: str) -> None:
    spec = _spec(chart.metric)
    tickformat = chart.tickformat or (formats.tickformat(spec) if spec is not None else "")
    title = ("≈ " if chart.estimate else "") + chart.title
    st.markdown(f"**{_escaped(title)}**")
    try:
        figure = _figure(chart, components.colors(), tickformat)
    except ValueError as reason:  # a house rule it would break: too many series to tell apart
        st.caption(f"Not drawn: {_escaped(str(reason))}. Every figure is in the rows below.")
        return
    components.chart(figure, chart.frame, key=key, filename=_filename(chart.title))


def _figure(chart: Chart, palette: Palette, tickformat: str) -> go.Figure:
    frame = chart.frame
    if chart.kind == "line":
        return charts.line(
            frame,
            x=chart.x,
            y=chart.y,
            text=chart.text,
            palette=palette,
            y_title=chart.y_title,
            tickformat=tickformat,
            reference=chart.reference,
            reference_label=chart.reference_label,
            categorical_x=True,
        )
    if chart.kind == "bars":
        return charts.diverging_bars(
            frame,
            value=chart.y,
            label=chart.x,
            text=chart.text,
            palette=palette,
            value_title=chart.y_title,
            tickformat=tickformat,
        )
    if chart.kind == "intervals":
        assert chart.low is not None and chart.high is not None
        return charts.interval_rows(
            frame,
            label=chart.x,
            value=chart.y,
            low=chart.low,
            high=chart.high,
            text=chart.text,
            palette=palette,
            value_title=chart.y_title,
            tickformat=tickformat,
            axis_range=chart.y_range,
        )
    if chart.kind == "percentiles":
        return charts.percentile_bars(
            frame, percentile=chart.y, label=chart.x, text=chart.text, palette=palette
        )
    assert chart.who is not None
    return charts.comparison_dots(
        frame, metric=chart.x, who=chart.who, percentile=chart.y, text=chart.text, palette=palette
    )


def _spec(metric: str | None) -> MetricSpec | None:
    if metric is None:
        return None
    return next(
        (catalog[metric] for catalog in METRIC_CATALOGS.values() if metric in catalog), None
    )


def _filename(title: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", title.lower()).strip("_")[:60] or "chart"


def _evidence(answer: Answer) -> None:
    items = answer.evidence
    if not items:
        return
    label = f"Evidence: {len(items)} source{'s' if len(items) != 1 else ''}"
    with st.expander(label, icon=":material/fact_check:"):
        for item in items:
            st.markdown(_evidence_line(item))


def _evidence_line(item: Evidence) -> str:
    parts = [f"**{EVIDENCE[item.kind]}**", _escaped(item.label)]
    if item.location:
        location = item.location
        is_link = location.startswith(("http://", "https://")) and not re.search(
            r"[\s<>]", location
        )
        parts.append(f"<{location}>" if is_link else f"`{location.replace('`', '')}`")
    dates = []
    if item.published_at is not None:
        dates.append(f"published {formats.moment(item.published_at)}")
    if item.effective_at is not None:
        dates.append(f"dated {formats.day(item.effective_at)}")
    if item.retrieved_at is not None:
        dates.append(f"fetched {formats.moment(item.retrieved_at)}")
    if dates:
        parts.append(", ".join(dates))
    return " · ".join(parts)


def _workings(turn: api.Turn) -> None:
    answer = turn.answer
    assert answer is not None
    with st.expander("How it was answered", icon=":material/route:"):
        for step in turn.steps or answer.steps:
            st.markdown(_step_line(step))
        made = f"Model {answer.model}" if answer.model else "No model was asked"
        st.caption(f"{made} · rules {answer.policy} · {turn.seconds:.1f} s")
        if answer.removed:
            st.caption(
                "Figures taken out because no result holds them: "
                + _escaped(", ".join(answer.removed))
            )


# --- text from outside the lab -------------------------------------------------------------------


def _prose(text: str) -> str:
    """The model's or the user's words as markdown that shows what they say: a dollar sign
    is a dollar sign rather than the start of a formula, and an image is not fetched."""
    return IMAGE.sub("(image left out)", text).replace("$", "\\$")


def _escaped(text: str) -> str:
    """Text shown exactly as written: a page's title, a source's name, a step."""
    return SPECIAL.sub(r"\\\1", text)
