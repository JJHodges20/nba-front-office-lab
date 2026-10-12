"""Contract Explorer: who is owed what, and where each payroll stands against the cap."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import front_office.assistant.api as api
from front_office.domain.cap_rules import PayrollLine
from front_office.domain.contract_review import ContractPreview
from wb import charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, MEASURED, Figure
from wb.state import Filters

STATUSES = {"All": None, "Under contract": "active", "Dead money": "dead_money"}
TYPES = formats.CONTRACT_TYPES
STATUS_WORDS = formats.CONTRACT_STATUSES
CAP_ROWS = {
    "status": "Status",
    "minimum_team_salary": "Minimum team salary",
    "salary_cap": "Salary cap",
    "luxury_tax": "Luxury tax line",
    "first_apron": "First apron",
    "second_apron": "Second apron",
    "non_taxpayer_mid_level": "Non-taxpayer mid-level exception",
    "taxpayer_mid_level": "Taxpayer mid-level exception",
    "room_mid_level": "Room mid-level exception",
    "bi_annual": "Bi-annual exception",
    "max_salary_0_to_6_years": "Maximum salary, 0-6 years of service",
    "max_salary_7_to_9_years": "Maximum salary, 7-9 years of service",
    "max_salary_10_plus_years": "Maximum salary, 10+ years of service",
    "max_standard_contracts": "Standard contracts, most",
    "min_standard_contracts": "Standard contracts, fewest",
    "max_two_way_contracts": "Two-way contracts, most",
}
COUNT_ROWS = ("max_standard_contracts", "min_standard_contracts", "max_two_way_contracts")
REVIEW = "contracts_review"
"""The last file checked against the one in use, for the session."""


def render() -> None:
    filters = state.current()
    components.header(
        "Contract Explorer",
        "Who is owed what, and where each payroll stands against the cap.",
        kinds=[MEASURED, DERIVED],
    )
    seasons = data.contract_seasons(filters.build)
    if not seasons:
        _no_contracts()
        st.subheader("Cap rules")
        _cap_rules(filters)
        st.subheader("Check a file before importing it")
        _review()
        return

    default = filters.payroll_season if filters.payroll_season in seasons else seasons[0]
    season = st.selectbox(
        "Payroll season",
        seasons,
        index=seasons.index(default),
        key="contracts_season",
        width=220,
        help="The season whose salaries are shown. Each is measured against that season's cap.",
    )
    sources = data.contract_sources(filters.build)
    stated = "; ".join(
        f"{source['source_label']}, current as of {formats.day(source['as_of_date'])}"
        for source in sources.to_dict("records")
    )
    st.caption(f"Salaries as supplied in your contract file. Source as stated at import: {stated}.")

    summary = data.contract_summary(filters.build, season)
    components.figures(
        [
            Figure("Contracts", formats.number(summary.contracts), f"{summary.players} players"),
            Figure(
                "Teams covered",
                f"{summary.teams} of {len(data.team_labels(filters.build))}",
                "Every team is in the file"
                if summary.teams == len(data.team_labels(filters.build))
                else "The rest: payroll unknown",
                help="A team absent from the contract file has an unknown payroll, not an "
                "empty one.",
            ),
            Figure(
                "Salaries owed",
                formats.money_compact(summary.total_salary),
                "All contracts",
                help="Every salary in the file for this season: standard, two-way and dead money.",
            ),
            Figure(
                "Dead money",
                formats.money_compact(summary.dead_money),
                "Owed to waived players",
                help="Salary a team still owes a player it no longer has. It counts against "
                "the cap.",
            ),
        ]
    )
    if summary.unassigned:
        st.caption(
            f"{summary.unassigned} salary row(s) in the file name no team and are in no payroll."
        )

    payrolls, listing, rules, review = st.tabs(
        ["Team payrolls", "Contracts", "Cap rules", "Check a new file"]
    )
    with payrolls:
        _payrolls(filters, season)
    with listing:
        _listing(filters, season)
    with rules:
        _cap_rules(filters)
    with review:
        _review()


def _review() -> None:
    """The contract-update review (A7): a file checked against the one in use, before the
    user decides to import it. Nothing here imports or stores anything."""
    st.caption(
        "Check a contract file before importing it - a newer copy of the dataset you use, or "
        "another source's. It is read exactly as an import would read it and compared with the "
        "file in use, season by season. Nothing is stored: importing stays your own command, "
        "once you have checked that the source may be used."
    )
    with st.form("contracts_review_form", border=False):
        upload = st.file_uploader(
            "Contract file (CSV, UTF-8)", type=["csv"], key="contracts_review_file"
        )
        with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
            source = st.text_input(
                "Where the figures came from",
                key="contracts_review_source",
                help="As an import would record it: the site or dataset, and its terms.",
            )
            as_of = st.date_input("Figures current as of", key="contracts_review_as_of", width=200)
        asked = st.form_submit_button("Compare with the file in use", type="primary")
    if asked:
        if upload is None or not source.strip():
            components.alert("warning", "Choose a file, and say where its figures came from.")
        else:
            try:
                st.session_state[REVIEW] = api.review_contract_file(
                    upload.getvalue(), upload.name, source_label=source, as_of=as_of
                )
            except api.ContractReviewError as error:
                st.session_state.pop(REVIEW, None)
                components.alert("error", f"Not read: {error}")
    preview: ContractPreview | None = st.session_state.get(REVIEW)
    if preview is not None:
        _preview(preview)


def _preview(preview: ContractPreview) -> None:
    components.figures(
        [
            Figure(
                "Rows read",
                formats.number(preview.rows_read),
                f"{formats.number(preview.players)} players",
            ),
            Figure("New", formats.number(preview.count("new")), "only in this file"),
            Figure("Changed", formats.number(preview.count("changed")), "salary or terms"),
            Figure("Gone", formats.number(preview.count("gone")), "only in the one in use"),
            Figure("The same", formats.number(preview.unchanged), "in both files"),
        ],
        per_row=5,
    )
    used = preview.in_use
    st.caption(
        f"{preview.file_name} ({preview.source_label}), as of {formats.day(preview.as_of)}, "
        + (
            "against no file: none is in use yet."
            if used is None
            else f"against {used.file_name} ({used.source_label}), as of {formats.day(used.as_of)}."
        )
    )
    for flag in preview.flags:
        components.tagged(("Check", ":material/warning:", "orange"), flag)
    if preview.changes:
        rows = pd.DataFrame(
            [
                {
                    "Season": change.season,
                    "Player": change.player,
                    "Team": change.team or EMPTY_CELL,
                    "In use": formats.money(change.in_use),
                    "In this file": formats.money(change.candidate),
                    "Change": ("+" if change.difference >= 0 else "-")
                    + formats.money(abs(change.difference)),
                    "Also": change.detail or EMPTY_CELL,
                }
                for change in preview.changes
            ]
        )
        st.dataframe(
            rows,
            hide_index=True,
            height=components.table_height(min(len(rows), 15)),
            row_height=components.ROW,
        )
    if preview.unmatched:
        with st.expander(f"Rows an import would leave out ({len(preview.unmatched)})"):
            st.markdown("\n".join(f"- {line}" for line in preview.unmatched))
    st.markdown("**Nothing was imported.** Once the source is checked, from the file's folder:")
    st.code(f"{preview.command}\nfol build", language="powershell")


def _no_contracts() -> None:
    components.empty(
        "No contract data yet",
        "The lab does not collect salaries itself: no free source permits it. Supply them in a "
        "file and every salary, payroll and cap share in the workbench fills in.",
        icon=":material/request_quote:",
    )
    st.markdown("**How to add contracts**")
    st.code(
        "fol contracts template                      # a file listing every rostered player\n"
        'fol contracts import FILE --source "..."    # validate it and store it\n'
        "fol build                                   # rebuild the database",
        language="powershell",
    )
    st.caption(
        "Fill the template's salary columns from a source you are entitled to use, and say "
        "which in --source: it is stored with the data and shown wherever a salary is. "
        "The file format is described in docs/CONTRACT_DATA.md."
    )


def _payrolls(filters: Filters, season: str) -> None:
    payrolls = data.team_payrolls(filters.build, season)
    if payrolls.empty:
        components.empty("No team payrolls", "No salary in this season is attached to a team.")
        return
    rules = data.cap_rules(filters.build)
    lines = rules[rules["season"] == season]
    thresholds = {}
    if lines.empty:
        st.caption(f"No cap rules are configured for {season}, so no cap lines are drawn.")
    else:
        thresholds = {
            formats.LINE_LABELS[line]: float(lines.iloc[0][line.value]) for line in PayrollLine
        }
    plotted = payrolls.assign(
        active_text=payrolls["active_salary"].map(formats.money),
        dead_text=payrolls["dead_money"].map(formats.money),
    )
    figure = charts.stacked_bars(
        plotted,
        label="team",
        parts={"active_salary": "Under contract", "dead_money": "Dead money"},
        text={"active_salary": "active_text", "dead_money": "dead_text"},
        thresholds=thresholds,
        highlight=[filters.team_id] if filters.team_id in payrolls.index else [],
        palette=components.colors(),
        value_title=f"Team salary, {season}",
        tickformat="$~s",
    )
    st.caption(
        "Team salary is what counts against the cap: standard contracts and dead money. "
        f"Two-way contracts sit outside it. {formats.LINES_EXPLAINED}"
    )
    table = pd.DataFrame(
        {
            "Team": payrolls["team_name"],
            "Team salary": payrolls["team_salary"].map(formats.money),
            "Dead money": payrolls["dead_money"].map(formats.money),
            "Standard contracts": payrolls["standard_contracts"],
            "Two-way": payrolls["two_way_contracts"],
            "Share of cap": payrolls["cap_share"].map(formats.share),
            "Room under cap": payrolls["room_salary_cap"].map(formats.money),
            "Room under tax": payrolls["room_luxury_tax"].map(formats.money),
            "Highest line exceeded": payrolls["highest_line_exceeded"].map(_line_title),
        }
    )
    components.chart(figure, table, key="payrolls", filename=f"team_payrolls_{season}")


def _line_title(value: object) -> str:
    return "None" if formats.is_missing(value) else PayrollLine(value).title


def _listing(filters: Filters, season: str) -> None:
    table = data.contract_table(filters.build, season)
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        status = st.segmented_control(
            "Status", list(STATUSES), default="All", required=True, key="contracts_status"
        )
        kinds = st.pills(
            "Contract type",
            list(TYPES),
            format_func=TYPES.get,
            selection_mode="multi",
            default=list(TYPES),
            key="contracts_types",
        )
    shown = table
    if filters.team_id is not None:
        shown = shown[shown["team_id"] == filters.team_id]
    if STATUSES[status] is not None:
        shown = shown[shown["status"] == STATUSES[status]]
    shown = shown[shown["contract_type"].isin(kinds)]
    if shown.empty:
        components.empty("No contracts match", "Loosen the filters, or clear the team filter.")
        return
    columns = [
        "player_name",
        "position",
        "team",
        "salary",
        "salary_cap_pct",
        "years_remaining",
        "option",
        "guarantee",
        "contract_type",
        "status",
        "last_season",
        "total_salary",
    ]
    chosen = st.dataframe(
        shown[columns].style.format(
            {
                "salary": formats.money,
                "total_salary": formats.money,
                "salary_cap_pct": formats.share,
                "contract_type": TYPES.get,
                "status": STATUS_WORDS.get,
                "option": formats.words,
                "guarantee": formats.words,
            },
            na_rep=formats.MISSING,
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key("contracts_table"),
        height=components.table_height(min(len(shown), 18)),
        row_height=components.ROW,
        column_config={
            "player_name": st.column_config.Column("Player", width="medium", pinned=True),
            "position": "Pos",
            "team": st.column_config.Column("Team", help="The team that owes the salary."),
            "salary": st.column_config.Column("Salary", help=f"Salary in {season}."),
            "salary_cap_pct": st.column_config.Column(
                "Cap %",
                help=f"Salary as a share of the {season} cap: the unit for comparing "
                "contracts across seasons. Derived.",
            ),
            "years_remaining": st.column_config.Column(
                "Yrs left", help="Seasons left after this one."
            ),
            "option": "Option",
            "guarantee": "Guarantee",
            "contract_type": "Type",
            "status": "Status",
            "last_season": "Through",
            "total_salary": st.column_config.Column(
                "Contract total", help="Sum of the seasons the file lists."
            ),
        },
    )
    picked = chosen.selection.rows
    if picked:
        state.choose(player_id=int(shown.iloc[picked[0]]["player_id"]))
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(shown, f"contracts_{season}", key="contracts_csv")
        st.caption(
            f"{len(shown)} contracts. Select a row to make that player the subject of the "
            "Player Explorer."
        )


def _cap_rules(filters: Filters) -> None:
    rules = data.cap_rules(filters.build)
    if rules.empty:
        components.empty("No cap rules configured", "Add a file to configs/seasons.")
        return
    st.caption(
        "Thresholds, exceptions and roster limits by season, from configs/seasons. Each figure "
        "was verified against the source listed below."
    )
    by_season = rules.set_index("season")
    table = pd.DataFrame(
        {
            season: [
                _rule_text(by_season.at[season, key], is_count=key in COUNT_ROWS or key == "status")
                for key in CAP_ROWS
            ]
            for season in by_season.index
        },
        index=list(CAP_ROWS.values()),
    )
    st.dataframe(
        table.rename_axis("Rule").reset_index(),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(table)),
        row_height=components.ROW,
        column_config={"Rule": st.column_config.Column(width="large", pinned=True)},
    )
    with st.expander("Sources", icon=":material/link:"):
        for season in by_season.index:
            links = by_season.at[season, "source_urls"].splitlines()
            st.markdown(f"**{season}**  \n" + "  \n".join(links))


def _rule_text(value: object, *, is_count: bool) -> str:
    if formats.is_missing(value):
        return formats.MISSING
    return str(value) if is_count else formats.money(value)
