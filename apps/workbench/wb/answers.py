"""One answer of the AI assistant as the workbench draws it, wherever it is asked.

The AI Research page draws every kept turn with these, and the *Ask AI about this* dialog
draws the answer it waited for. Nothing here is computed: the kind of answer, the text, the
notes, the rosters proposed, each result's rows and the chart its tool chose, the evidence
and the steps all come with the answer (decision 0018). Model text goes through
:func:`prose` - a dollar sign is not a formula, an image is not fetched - and anything else
from outside the lab through :func:`escaped`.

Every key a widget takes is built from the ``key`` the caller gives: a kept turn's id, so
that a widget keeps its state as the page reruns and never clashes with another turn's.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import front_office.assistant.api as api
from front_office.domain.assistant import (
    Answer,
    Chart,
    Evidence,
    EvidenceKind,
    NameCandidate,
    Outcome,
    ResultStatus,
    Step,
    ToolResult,
)
from front_office.domain.experiments import ExperimentPlan, ExperimentProposal
from front_office.domain.metrics import MetricSpec
from front_office.domain.proposals import RosterProposal
from front_office.domain.research import ExperimentRecord, ProposalRecord
from front_office.domain.tables.rosters import ROSTER_SLOTS
from front_office.services import METRIC_CATALOGS, ProposalSaved
from wb import charts, components, formats
from wb.components import Figure
from wb.theme import Palette

SAVES = "ai_saves"
"""What pressing a proposal's save button last did, by the proposal's fingerprint."""
BENCH = ROSTER_SLOTS[-1]
TAB_LABEL = 38
"""Characters of a result's title on its tab."""

OUTCOMES = {
    Outcome.SUPPORTED: (
        "Supported",
        ":material/verified:",
        "green",
        "Answered from the lab's results; every number was checked.",
    ),
    Outcome.QUALIFIED: (
        "Partly answered",
        ":material/info:",
        "orange",
        "Part of the question could not be answered, or comes with a caveat: the notes say which.",
    ),
    Outcome.INSUFFICIENT: (
        "Not enough to answer",
        ":material/help:",
        "gray",
        "The lab's results do not answer this. The answer says what is missing and makes "
        "nothing up.",
    ),
    Outcome.CLARIFY: (
        "Question back",
        ":material/contact_support:",
        "blue",
        "A name could mean more than one player, team or season, or nothing said who is "
        "meant: pick or name the one you mean.",
    ),
    Outcome.DECLINED: (
        "Declined",
        ":material/block:",
        "gray",
        "Something the assistant does not do: run code or database queries, open files, save "
        "or change anything, or refit a model.",
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
    EvidenceKind.DOCS: "The lab's documents",
}
PROPOSALS = (
    "Example rosters the optimizer found for this question: options to compare, not a "
    "recommendation. The lab has not checked whether the trades or signings to get them are "
    "allowed. Nothing is saved until you press Save approved roster under one."
)
SAVE_HELP = (
    "Saves this roster for the Team Builder. Before saving, the lab checks that its data, its "
    "player value model and the salaries are the same as when the roster was proposed."
)
DECLINE_HELP = "Set this option aside: it stays in the workspace's proposals, marked declined."
RATING_HELP = (
    "Each player's forecast added up for the minutes they are expected to play, relative to "
    "the league. For whole teams these forecasts have typically been off by the amount shown."
)
EXPERIMENTS = (
    "Drafted because you asked: experiments for one of the lab's models, to review. The idea "
    "is the assistant's and has not been tested; the test beside it is the lab's, from the "
    "model's file and its decision. Keeping one changes no model, setting or data."
)
KEEP_HELP = (
    "Keeps this proposal in the workspace's list of experiment proposals, to come back to. "
    "No model, setting or data changes."
)
IDEA_TAG = ("The assistant's idea", ":material/lightbulb:", "orange")
TEST_TAG = components.PROVENANCE[components.MODELED][:3]
"""The lab's test is the model's own record: tagged as every modeled figure is."""
PROPOSAL_METRICS = ("projected_impact", "projected_share", "projected_wins")
"""The value model's forecasts in a proposal's players table, labelled by their catalog."""
PROPOSAL_COLUMNS = {
    "player_name": st.column_config.Column("Player", width="medium", pinned=True),
    "team": st.column_config.Column("Team", help="The team the player is under contract to."),
    "position": st.column_config.Column("Pos"),
    "slot": st.column_config.Column(
        "On the roster",
        help="Where the save puts the player: starters are picked from the nine who play the "
        "most, each at a position they are listed at where the roster allows.",
    ),
    "salary": st.column_config.Column(
        "Salary", help="For the season ahead, from your contract file."
    ),
}
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
SPECIAL = re.compile(r"([\\`*_\[\]()#+!|~<>$-])")

Choose = Callable[[NameCandidate], None]


def draw(
    answer: Answer,
    *,
    key: str,
    steps: tuple[Step, ...] = (),
    seconds: float = 0.0,
    can_ask: bool = True,
    choose: Choose | None = None,
    workspace_id: int | None = None,
    records: Mapping[str, ProposalRecord] | None = None,
    roster_names: Mapping[int, str] | None = None,
    turn_id: int | None = None,
    kept: Mapping[str, ExperimentRecord] | None = None,
) -> None:
    """The whole answer: its kind, its text, the readings to choose from, its notes, the
    rosters and experiments it proposed, what it rests on, and how it was answered."""
    outcome(answer)
    st.markdown(prose(answer.text))
    if answer.outcome is Outcome.CLARIFY and answer.options and choose is not None:
        options(answer, key=key, can_ask=can_ask, choose=choose)
    notes(answer)
    if workspace_id is not None:
        proposals(
            answer,
            key=key,
            workspace_id=workspace_id,
            records=records or {},
            roster_names=roster_names or {},
        )
    experiments(answer, key=key, workspace_id=workspace_id, turn_id=turn_id, kept=kept or {})
    results(answer, key=key)
    evidence(answer)
    workings(answer, steps=steps, seconds=seconds)


def outcome(answer: Answer) -> None:
    word, icon, color, meaning = OUTCOMES[answer.outcome]
    with st.container(horizontal=True, gap="small"):
        st.badge(word, icon=icon, color=color, help=meaning)
        kinds = sorted(
            {kind for result in answer.results if result.usable for kind in result.kinds}
            & set(components.PROVENANCE)
        )
        components.provenance(kinds)


def notes(answer: Answer) -> None:
    for note in answer.warnings:
        components.tagged(("Note", ":material/info:", "gray"), escaped(note))


def options(answer: Answer, *, key: str, can_ask: bool, choose: Choose) -> None:
    st.caption("Choose the one you mean, and the question is asked again with it.")
    with st.container(horizontal=True, gap="small"):
        for position, option in enumerate(answer.options):
            if st.button(
                option.name,
                key=f"ai_option_{key}_{position}",
                disabled=not can_ask,
                help=_option_help(option),
            ):
                choose(option)


def _option_help(option: NameCandidate) -> str:
    kind = {"player": "The player", "team": "The team", "season": "The season"}[option.kind]
    return f'{kind} {option.name}, for "{option.text}".'


def step_line(step: Step) -> str:
    took = f" ({step.seconds:.1f} s)" if step.seconds >= 0.1 else ""
    return f"{STEPS.get(step.kind, ':material/circle:')} {escaped(_step_words(step))}{took}"


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


# --- roster proposals -----------------------------------------------------------------------------


def proposals(
    answer: Answer,
    *,
    key: str,
    workspace_id: int,
    records: Mapping[str, ProposalRecord],
    roster_names: Mapping[int, str],
) -> None:
    """The rosters the optimizer proposed, each with what it rests on and a button to save
    it - the user's click, never the model's (A5) - or to decline it, and what was done
    with it in this workspace (A6)."""
    found = [result for result in answer.results if result.usable and result.proposals]
    if not found:
        return
    st.markdown("**Rosters to review**")
    st.caption(PROPOSALS)
    for result in found:
        if len(found) > 1:  # each run labels its own options from A
            st.caption(f"From {result.result_id}: {escaped(result.title)}")
        first = result.proposals[0]
        for position, proposal in enumerate(result.proposals):
            proposal_card(
                proposal,
                first,
                key=f"{key}_{result.result_id}_{position}",
                workspace_id=workspace_id,
                record=records.get(proposal.fingerprint),
                roster_names=roster_names,
            )


def proposal_card(
    proposal: RosterProposal,
    first: RosterProposal,
    *,
    key: str,
    workspace_id: int,
    record: ProposalRecord | None,
    roster_names: Mapping[int, str],
) -> None:
    with st.container(border=True):
        heading = f"**{escaped(proposal.label)}** · {proposal.payroll_season}"
        if record is not None and record.status == "saved":
            heading += " · saved"
        elif record is not None and record.status == "declined":
            heading += " · declined"
        st.markdown(heading)
        components.figures(
            [
                Figure(
                    "Payroll",
                    formats.money_compact(proposal.payroll),
                    f"budget {formats.money_compact(proposal.budget)}",
                    help=f"{proposal.budget_label}: the line the payroll may not go over.",
                ),
                Figure(
                    "Left to spend",
                    formats.money_compact(proposal.room),
                    "under the budget",
                ),
                Figure(
                    "Projected net rating",
                    f"{proposal.rating:+.1f}",
                    None if proposal.error is None else f"give or take {proposal.error:.1f}",
                    help=RATING_HELP,
                ),
            ]
        )
        if proposal is not first:
            st.caption(
                f"Compared with {escaped(first.label)}: in {_listed(proposal.added)}; "
                f"out {_listed(proposal.removed)}."
            )
        st.caption(_basis(proposal))
        players = pd.DataFrame([player.model_dump() for player in proposal.players])
        players["slot"] = players["slot"].map(_slot)
        shown = players[[*PROPOSAL_COLUMNS, *PROPOSAL_METRICS]]
        catalog = METRIC_CATALOGS["Player value"]
        st.dataframe(
            formats.styled(shown, catalog, {"salary": formats.money}),
            hide_index=True,
            placeholder=components.EMPTY_CELL,
            height=components.table_height(len(shown)),
            row_height=components.ROW,
            column_config={
                **PROPOSAL_COLUMNS,
                **components.metric_columns(catalog, PROPOSAL_METRICS),
            },
            key=f"ai_proposal_table_{key}",
        )
        status = None if record is None else record.status
        with st.container(horizontal=True, vertical_alignment="center"):
            if status != "saved":
                with st.popover("Save approved roster", icon=":material/save:"):
                    st.caption(SAVE_HELP)
                    name = st.text_input(
                        "Roster name",
                        value=f"AI Research {proposal.label}, {proposal.payroll_season}",
                        max_chars=80,
                        key=f"ai_proposal_name_{key}",
                    )
                    if st.button(
                        "Save approved roster", key=f"ai_proposal_save_{key}", type="primary"
                    ):
                        st.session_state.setdefault(SAVES, {})[proposal.fingerprint] = (
                            api.save_proposal(proposal, name, workspace_id=workspace_id)
                        )
                        # Drawn again, so that the workspace's list says what waits: the
                        # same proposal is drawn there and under its answer (A6).
                        st.rerun()
            if status is None or status == "draft":
                if st.button(
                    "Decline",
                    key=f"ai_proposal_decline_{key}",
                    icon=":material/block:",
                    help=DECLINE_HELP,
                ):
                    api.decline_proposal(proposal.fingerprint, workspace_id=workspace_id)
                    st.rerun()
        pressed = st.session_state.get(SAVES, {}).get(proposal.fingerprint)
        if pressed is not None:
            _saved(pressed)
        elif record is not None and record.status == "saved" and record.roster_id is not None:
            name = roster_names.get(record.roster_id)
            st.caption(
                f"Saved for the Team Builder as “{escaped(name)}”."
                if name
                else "Saved for the Team Builder; that roster has since been deleted there."
            )
        elif record is not None and record.status == "declined":
            st.caption("Declined. It can still be saved: press Save approved roster.")


def _saved(saved: ProposalSaved) -> None:
    if saved.created:
        st.success(
            f"Saved as “{escaped(str(saved.name))}”. The Team Builder has it.",
            icon=":material/check_circle:",
        )
    elif saved.saved:
        st.info(
            f"Already saved as “{escaped(str(saved.name))}”. It was not saved a second time.",
            icon=":material/info:",
        )
    else:
        st.warning(
            "Not saved. "
            + " ".join(escaped(reason) for reason in saved.refused)
            + " Ask the question again for rosters made from the lab as it is now.",
            icon=":material/warning:",
        )


# --- experiment proposals (A8) -------------------------------------------------------------------


def experiments(
    answer: Answer,
    *,
    key: str,
    workspace_id: int | None,
    turn_id: int | None,
    kept: Mapping[str, ExperimentRecord],
) -> None:
    """The experiments the assistant drafted because the user asked, each with the lab's
    test beside the idea, a button to keep it in the workspace and a document to download.
    Keeping one changes nothing else (A8)."""
    found = [result for result in answer.results if result.usable and result.experiments]
    if not found:
        return
    st.markdown("**Experiments to review**")
    st.caption(EXPERIMENTS)
    for result in found:
        for position, proposal in enumerate(result.experiments):
            experiment_card(
                proposal,
                key=f"{key}_{result.result_id}_{position}",
                workspace_id=workspace_id,
                turn_id=turn_id,
                record=kept.get(proposal.fingerprint),
            )


def experiment_card(
    proposal: ExperimentProposal,
    *,
    key: str,
    workspace_id: int | None = None,
    turn_id: int | None = None,
    record: ExperimentRecord | None = None,
) -> None:
    """One experiment proposal: the assistant's idea, then the lab's test, kept apart."""
    idea, plan = proposal.idea, proposal.plan
    with st.container(border=True):
        heading = f":material/science: **{escaped(idea.title)}** · {escaped(plan.label)}"
        if record is not None:
            heading += " · kept"
        st.markdown(heading)
        components.tagged(IDEA_TAG, "Not tested: what the assistant supposes, in its words.")
        st.markdown(
            f"**What was noticed.** {escaped(idea.observation)}\n\n"
            f"**The hypothesis.** {escaped(idea.hypothesis)}\n\n"
            f"**The change to test.** {escaped(idea.change)}\n\n"
            "**How it could fail.**\n\n"
            + "\n".join(f"- {escaped(item)}" for item in idea.failure_modes)
        )
        components.tagged(TEST_TAG, escaped(_tested(plan)))
        if plan.missing:
            st.caption(escaped(plan.missing))
        if plan.baseline:
            beat = pd.DataFrame(
                {
                    "What a change must beat or keep": [measure.label for measure in plan.baseline],
                    "Now": [
                        measure.text + (f" ({measure.interval})" if measure.interval else "")
                        for measure in plan.baseline
                    ],
                }
            )
            st.dataframe(
                beat,
                hide_index=True,
                height=components.table_height(len(beat)),
                row_height=components.ROW,
                key=f"ai_experiment_table_{key}",
            )
        with st.expander("How a change would be tested", icon=":material/rule:"):
            st.markdown(
                f"**How seasons are split.** {escaped(plan.split)}\n\n"
                f"**What is measured.** {escaped(plan.metric)}\n\n"
                f"**How sure.** {escaped(plan.uncertainty)}\n\n"
                f"**When it would be kept.** {escaped(plan.acceptance)}\n\n"
                "**Leakage to rule out.**\n\n"
                + "\n".join(f"- {escaped(item)}" for item in plan.leakage)
                + "\n\n**Steps for the milestone that would build it.**\n\n"
                + "\n".join(
                    f"{number}. {escaped(step)}" for number, step in enumerate(plan.steps, 1)
                )
            )
        if plan.tried:
            with st.expander("What was tried before", icon=":material/history:"):
                for section in plan.tried:
                    st.caption(escaped(f"{section.path}: {section.heading}"))
                    st.markdown(prose(section.text))
        with st.container(horizontal=True, vertical_alignment="center"):
            if workspace_id is not None and record is None:
                if st.button(
                    "Keep in the workspace",
                    key=f"ai_experiment_keep_{key}",
                    icon=":material/bookmark_add:",
                    type="primary",
                    help=KEEP_HELP,
                ):
                    api.keep_experiment(proposal, workspace_id=workspace_id, turn_id=turn_id)
                    st.rerun()
            st.download_button(
                "Download",
                data=proposal.document(),
                file_name=f"experiment-{_filename(idea.title)}.md",
                mime="text/markdown",
                key=f"ai_experiment_download_{key}",
                icon=":material/download:",
                help="The proposal as a document (Markdown), to read or share.",
            )
        if record is not None:
            st.caption(f"Kept in this workspace {formats.moment(record.created_at)}.")


def _tested(plan: ExperimentPlan) -> str:
    """Where the lab's part comes from, in a line."""
    source = plan.label
    if plan.revision is not None:
        source += f", revision {plan.revision}"
    if plan.model_file:
        source += f" ({plan.model_file})"
    line = f"The lab's test, from the {source} and {plan.decision}."
    if plan.tested_on:
        line += f" Tested on: {plan.tested_on}"
    return line


def _basis(proposal: RosterProposal) -> str:
    basis = proposal.basis
    asked = "; ".join(proposal.requirements)
    contract = (
        f"your contract file as of {formats.day(basis.contract_as_of)}"
        if basis.contract_as_of is not None
        else "your contract file"
    )
    model = f"the player value model ({basis.value_model})" if basis.value_model else "no model"
    build = f", data build {basis.build_id}" if basis.build_id is not None else ""
    return escaped(f"Asked for: {asked}. Salaries from {contract}; forecasts from {model}{build}.")


def _slot(slot: str) -> str:
    return "Bench" if slot == BENCH else f"Starts at {slot}"


def _listed(names: tuple[str, ...]) -> str:
    if not names:
        return "nobody"
    shown = [escaped(name) for name in names]
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + " and " + shown[-1]


# --- what an answer rests on -----------------------------------------------------------------------


def results(answer: Answer, *, key: str) -> None:
    shown = [result for result in answer.results if _has_rows(result)]
    if not shown:
        return
    st.markdown("**Where this answer comes from**")
    tabs = st.tabs([_tab_label(result) for result in shown])
    for tab, result in zip(tabs, shown, strict=True):
        with tab:
            if len(result.title) > TAB_LABEL:  # the tab could not say it in full
                st.caption(escaped(result.title))
            for position, chart in enumerate(result.charts):
                _chart(chart, key=f"ai_chart_{key}_{result.result_id}_{position}")
            if result.table is not None and not result.table.empty:
                _rows(result.table, key=f"ai_table_{key}_{result.result_id}")
                components.export(
                    result.table,
                    f"{result.tool}_{result.result_id}",
                    key=f"ai_csv_{key}_{result.result_id}",
                    label="Rows (CSV)",
                )


def _rows(table: pd.DataFrame, *, key: str) -> None:
    """A result's rows as the workbench writes them: a metric under its label and in its
    format, any other column in words, a time as a time, the lab's internal ids and keys left
    to the CSV."""
    shown = table[shown_columns(table.columns)].reset_index(drop=True)
    for column in shown.columns:
        times = times_from_text(shown[column])
        if times is not None:
            shown[column] = times
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
    plain_columns = {
        column: plain
        for column in shown.columns
        if column not in specs
        and pd.api.types.is_numeric_dtype(shown[column])
        and not pd.api.types.is_bool_dtype(shown[column])
    }
    time_columns = {
        column: moments(shown[column])
        for column in shown.columns
        if pd.api.types.is_datetime64_any_dtype(shown[column])
    }
    styled = shown.style.format(
        {
            **plain_columns,
            **time_columns,
            **{column: spec.format_value for column, spec in specs.items()},
        },
        na_rep=components.EMPTY_CELL,
    )
    st.dataframe(
        styled,
        hide_index=True,
        column_config=headings,
        placeholder=components.EMPTY_CELL,
        key=key,
    )


def plain(value: object) -> str:
    """A figure no catalog describes, without a tail of zeros: 5, 0.793, 114.9."""
    if formats.is_missing(value):
        return components.EMPTY_CELL
    number = float(value)  # type: ignore[arg-type]
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.3f}".rstrip("0").rstrip(".")


ISO_MOMENT = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?")


def times_from_text(column: pd.Series) -> pd.Series | None:
    """A column of times a kept answer holds as ISO text - its JSON has no other way - as
    times again, or ``None`` when it is not one."""
    values = column.dropna()
    textual = pd.api.types.is_string_dtype(column) or pd.api.types.is_object_dtype(column)
    if not textual or values.empty:
        return None
    if not all(isinstance(value, str) and ISO_MOMENT.fullmatch(value) for value in values):
        return None
    return pd.to_datetime(column, format="ISO8601")


def moments(column: pd.Series) -> Callable[[object], str]:
    """How a column of times is written: the day alone where every time is midnight, else
    the day and the time in UTC, as the lab keeps them. Live at A7 a news item's time showed
    as 2026-10-10T23:47:27."""
    times = pd.to_datetime(column.dropna())
    timed = bool(((times.dt.hour != 0) | (times.dt.minute != 0)).any())
    pattern = "%Y-%m-%d %H:%M UTC" if timed else "%Y-%m-%d"

    def written(value: object) -> str:
        if formats.is_missing(value):
            return components.EMPTY_CELL
        return pd.Timestamp(value).strftime(pattern)  # type: ignore[arg-type]

    return written


INTERNAL = ("_id", "_key")
SHOWN_IDS = {"source_id": "Source"}
"""Ids a reader needs: at A7 news answers sent the user to "the source ID s2", which no
table or evidence line showed."""


def shown_columns(columns: Iterable[object]) -> list[object]:
    """A result's columns a reader sees: not the lab's internal ids and keys - a
    transaction's key showed at A7 - but a source's id, by which an answer names it."""
    return [
        column for column in columns if column in SHOWN_IDS or not str(column).endswith(INTERNAL)
    ]


def _words(column: str) -> str:
    if column in SHOWN_IDS:
        return SHOWN_IDS[column]
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
    st.markdown(f"**{escaped(title)}**")
    try:
        figure = _figure(chart, components.colors(), tickformat)
    except ValueError as reason:  # a house rule it would break: too many series to tell apart
        st.caption(f"Not drawn: {escaped(str(reason))}. Every figure is in the rows below.")
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
            reference=chart.reference,
            reference_label=chart.reference_label,
            axis_range=chart.y_range,
        )
    if chart.kind == "percentiles":
        # A tool names the axis when higher is not better - a roster's fit measures (A4).
        titled = {"axis_title": chart.y_title} if chart.y_title else {}
        return charts.percentile_bars(
            frame, percentile=chart.y, label=chart.x, text=chart.text, palette=palette, **titled
        )
    assert chart.who is not None
    if chart.y_range is None:
        return charts.comparison_dots(
            frame,
            metric=chart.x,
            who=chart.who,
            percentile=chart.y,
            text=chart.text,
            palette=palette,
        )
    # Not a percentile but a share with natural ends - a chance before and after a change.
    low, high = chart.y_range
    margin = (high - low) * 0.02
    return charts.comparison_dots(
        frame,
        metric=chart.x,
        who=chart.who,
        percentile=chart.y,
        text=chart.text,
        palette=palette,
        axis_title=chart.y_title,
        axis_range=(low - margin, high + margin),
        tickvals=None,
        tickformat=tickformat,
        reference=chart.reference,
    )


def _spec(metric: str | None) -> MetricSpec | None:
    if metric is None:
        return None
    return next(
        (catalog[metric] for catalog in METRIC_CATALOGS.values() if metric in catalog), None
    )


def _filename(title: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", title.lower()).strip("_")[:60] or "chart"


def evidence(answer: Answer) -> None:
    items = answer.evidence
    if not items:
        return
    label = f"Evidence: {len(items)} source{'s' if len(items) != 1 else ''}"
    with st.expander(label, icon=":material/fact_check:"):
        for item in items:
            st.markdown(evidence_line(item))


def evidence_line(item: Evidence) -> str:
    parts = [f"**{EVIDENCE[item.kind]}**", escaped(item.label)]
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


def workings(answer: Answer, *, steps: tuple[Step, ...] = (), seconds: float = 0.0) -> None:
    with st.expander("How it was answered", icon=":material/route:"):
        for step in steps or answer.steps:
            st.markdown(step_line(step))
        made = f"Model {answer.model}" if answer.model else "No model was asked"
        st.caption(f"{made} · rules {answer.policy} · {seconds or answer.seconds:.1f} s")
        if answer.removed:
            st.caption(
                "Figures taken out because no result holds them: "
                + escaped(", ".join(answer.removed))
            )


# --- text from outside the lab -----------------------------------------------------------------------


def prose(text: str) -> str:
    """The model's or the user's words as markdown that shows what they say: a dollar sign
    is a dollar sign rather than the start of a formula, and an image is not fetched - one
    written inline is left out, and any other (``![x][r]`` with ``[r]: <address>`` further
    on, A9) is shown as the characters it is."""
    return IMAGE.sub("(image left out)", text).replace("![", "!\\[").replace("$", "\\$")


def escaped(text: str) -> str:
    """Text shown exactly as written: a page's title, a source's name, a step."""
    return SPECIAL.sub(r"\\\1", text)
