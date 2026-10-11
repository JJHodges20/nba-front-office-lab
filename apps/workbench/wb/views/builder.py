"""Team Builder: assemble a roster by hand, see what it costs and what its players add up to.

Nothing here ranks or recommends. A roster is the user's assumption, priced against a
season's cap and described from its players' real seasons.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.cap_rules import PayrollLine
from front_office.domain.metrics import MetricCatalog
from front_office.domain.tables.rosters import ROSTER_SLOTS
from front_office.services import RosterError, RosterNotFound, RosterSummary
from wb import ask, charts, components, data, formats, state
from wb.components import ASSUMPTION, DERIVED, EMPTY_CELL, MEASURED, Figure
from wb.state import Filters

SELECTED = "builder_roster"
CREATED = "builder_roster_created"
IN_ORDER = ("In order", ":material/check_circle:", "green")
NOTE = ("Note", ":material/info:", "orange")
BENCH = ROSTER_SLOTS[-1]
SOURCES = {"contract": "Contract file", "assumed": "Your assumption"}
NO_SALARY = "No salary"
EDITABLE = ("slot", "assumed_salary", "remove")
STATS = ("minutes_per_game", "pts_per_game", "ts_pct")


def render() -> None:
    filters = state.current()
    components.header(
        "Team Builder",
        "Assemble a roster by hand: what it costs, and what its players add up to.",
        kinds=[ASSUMPTION, MEASURED, DERIVED],
    )
    rosters = data.rosters()
    if rosters.empty:
        components.empty(
            "No rosters yet",
            "Create one, then add players to it. Rosters are yours: rebuilding the league "
            "data never touches them.",
            icon=":material/construction:",
        )
        form, _ = st.columns([2, 3])
        with form, st.container(border=True):
            _create_form(filters, key="first")
        return

    roster_id = _choose(filters, rosters)
    try:
        summary = data.roster_summary(roster_id)
    except RosterNotFound:
        st.session_state.pop(SELECTED, None)
        st.rerun()
    roster = summary.roster
    ask.button(
        ask.from_filters(
            "Team Builder", filters, roster_id=roster_id, roster_name=str(roster["name"])
        )
    )
    st.caption(
        f"Players are described by their {roster['stats_season']} regular season and priced "
        f"against the {roster['payroll_season']} cap. Both are your choice: change them under "
        "Manage. The lab prices and describes a roster; it does not rank or recommend players."
    )

    _headlines(summary)
    _payroll(summary)
    _checks(summary)

    players, indicators = st.tabs(["Players", "What the roster adds up to"])
    with players:
        _add_player(filters, summary)
        _players(summary)
    with indicators:
        _indicators(summary)


# --- choosing and managing rosters --------------------------------------------------------


def _choose(filters: Filters, rosters: pd.DataFrame) -> int:
    ids = rosters["roster_id"].tolist()
    names = rosters.set_index("roster_id")["name"]
    counts = rosters.set_index("roster_id")["players"]
    # A roster just created becomes the one on screen. The roster select has been drawn
    # by the time the form creates it, and a widget's value cannot be changed after
    # that, so the choice is parked and applied here on the next run.
    if CREATED in st.session_state:
        st.session_state[SELECTED] = st.session_state.pop(CREATED)
    if st.session_state.get(SELECTED) not in ids:
        st.session_state[SELECTED] = ids[0]
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        roster_id = st.selectbox(
            "Roster",
            ids,
            format_func=lambda value: f"{names[value]} ({counts[value]} players)",
            key=SELECTED,
            width=360,
        )
        with st.popover("New roster", icon=":material/add:"):
            _create_form(filters, key="new")
        with st.popover("Manage", icon=":material/settings:"):
            _manage(filters, rosters.set_index("roster_id").loc[roster_id])
    return int(roster_id)


def _season_choices(filters: Filters) -> tuple[list[str], list[str]]:
    stats = list(data.player_seasons_played(filters.build))
    payroll = data.cap_rules(filters.build)["season"].tolist()
    return stats, payroll


def _create_form(filters: Filters, *, key: str) -> None:
    stats, payroll = _season_choices(filters)
    if not stats or not payroll:
        st.caption("A roster needs a season with player statistics and a season with cap rules.")
        return
    default_payroll = filters.payroll_season if filters.payroll_season in payroll else payroll[0]
    with st.form(f"create_roster_{key}", border=False):
        name = st.text_input("Name", placeholder="For example: Cap-space plan A", max_chars=80)
        stats_season = st.selectbox(
            "Statistics from", stats, help="The season whose numbers describe the players."
        )
        payroll_season = st.selectbox(
            "Priced against",
            payroll,
            index=payroll.index(default_payroll),
            help="The season whose salaries and cap lines the roster is measured against.",
        )
        if st.form_submit_button("Create roster", type="primary", icon=":material/add:"):
            try:
                created = data.lab().builder.create(
                    name, stats_season=stats_season, payroll_season=payroll_season
                )
            except RosterError as error:
                st.error(str(error), icon=":material/error:")
            else:
                st.session_state[CREATED] = created
                st.rerun()


def _manage(filters: Filters, roster: pd.Series) -> None:
    stats, payroll = _season_choices(filters)
    roster_id = int(roster.name)
    with st.form(f"manage_roster_{roster_id}", border=False):
        name = st.text_input("Name", value=roster["name"], max_chars=80)
        stats_season = st.selectbox(
            "Statistics from",
            stats,
            index=stats.index(roster["stats_season"]) if roster["stats_season"] in stats else 0,
        )
        payroll_season = st.selectbox(
            "Priced against",
            payroll,
            index=payroll.index(roster["payroll_season"])
            if roster["payroll_season"] in payroll
            else 0,
        )
        notes = st.text_area(
            "Notes", value="" if formats.is_missing(roster["notes"]) else roster["notes"]
        )
        if st.form_submit_button("Save changes", icon=":material/save:"):
            try:
                data.lab().builder.update(
                    roster_id,
                    name=name,
                    stats_season=stats_season,
                    payroll_season=payroll_season,
                    notes=notes,
                )
            except RosterError as error:
                st.error(str(error), icon=":material/error:")
            else:
                st.rerun()
    st.divider()
    confirmed = st.checkbox("I want to delete this roster", key=f"confirm_delete_{roster_id}")
    if st.button(
        "Delete roster",
        icon=":material/delete:",
        disabled=not confirmed,
        key=f"delete_{roster_id}",
    ):
        data.lab().builder.delete(roster_id)
        st.session_state.pop(SELECTED, None)
        st.rerun()


# --- what the roster costs ------------------------------------------------------------------


def _headlines(summary: RosterSummary) -> None:
    roster, payroll, rules = summary.roster, summary.payroll, summary.rules
    notes = []
    if summary.assumed:
        notes.append(f"{summary.assumed} assumed")
    if summary.unpriced:
        notes.append(f"{summary.unpriced} without a salary")
    items = [
        Figure(
            "Players",
            formats.number(len(summary.players)),
            None
            if rules is None
            else f"Teams carry {rules.roster.min_standard_contracts} to "
            f"{rules.roster.max_standard_contracts}",
            help="Standard contracts a team carries in season. Two-way contracts are separate.",
        ),
        Figure(
            "Payroll",
            formats.money_compact(summary.payroll_total),
            ", ".join(notes) if notes else "All from the contract file",
            help="The sum of the salaries that are known. A player without a salary adds "
            "nothing, so the total is understated until every player has one.",
        ),
    ]
    if payroll is None:
        items.append(
            Figure(
                "Share of cap",
                formats.MISSING,
                f"No cap rules for {roster['payroll_season']}",
            )
        )
    else:
        cap = payroll.position(PayrollLine.SALARY_CAP)
        tax = payroll.position(PayrollLine.LUXURY_TAX)
        exceeded = payroll.highest_line_exceeded
        items += [
            Figure(
                "Share of cap",
                formats.share(payroll.cap_share),
                f"of {formats.money_compact(cap.amount)}",
                help=f"Payroll as a share of the {roster['payroll_season']} salary cap.",
            ),
            Figure("Cap room", _room(cap.room), "Under the cap" if cap.room >= 0 else "Over it"),
            Figure("Tax room", _room(tax.room), "Under the tax" if tax.room >= 0 else "Over it"),
            Figure(
                "Line crossed",
                "None" if exceeded is None else formats.LINE_LABELS[exceeded],
                "Below the floor" if payroll.is_below_minimum else "Above the floor",
                help=formats.LINES_EXPLAINED,
            ),
        ]
    # Two rows of three: "Over by $12.3M" and "2 assumed, 1 without a salary" need the width.
    components.figures(items, per_row=3)


def _room(room: int) -> str:
    return formats.money_compact(room) if room >= 0 else f"Over by {formats.money_compact(-room)}"


def _payroll(summary: RosterSummary) -> None:
    if summary.payroll is None:
        return
    thresholds = {
        formats.LINE_LABELS[position.line]: float(position.amount)
        for position in summary.payroll.positions
    }
    figure = charts.meter(
        value=float(summary.payroll_total),
        value_text=f"Payroll {formats.money(summary.payroll_total)}",
        thresholds=thresholds,
        palette=components.colors(),
        tickformat="$~s",
        estimated=summary.unpriced > 0,
    )
    table = pd.DataFrame(
        {
            "Line": [position.line.title for position in summary.payroll.positions],
            "Amount": [formats.money(position.amount) for position in summary.payroll.positions],
            "Room": [_room(position.room) for position in summary.payroll.positions],
        }
    )
    components.chart(
        figure, table, key="builder_meter", filename=f"payroll_{summary.roster['roster_id']}"
    )
    if summary.unpriced:
        st.caption(
            "The bar is gray because some players have no salary: the payroll shown is a floor."
        )


def _checks(summary: RosterSummary) -> None:
    for check in summary.checks:
        components.tagged(IN_ORDER if check.passed else NOTE, check.message)


# --- the players ------------------------------------------------------------------------------


def _add_player(filters: Filters, summary: RosterSummary) -> None:
    roster = summary.roster
    options = data.player_options(filters.build, roster["stats_season"])
    available = options[~options.index.isin(summary.players.index)].sort_values("player_name")
    with st.form(f"add_player_{roster['roster_id']}", border=True, clear_on_submit=True):
        player, slot, salary, button = st.columns([4, 2, 3, 2], vertical_alignment="bottom")
        player_id = player.selectbox(
            "Add a player",
            available.index.tolist(),
            index=None,
            placeholder=f"Search the {roster['stats_season']} players",
            format_func=lambda value: (
                f"{available.at[value, 'player_name']} · {available.at[value, 'team']}"
            ),
        )
        chosen_slot = slot.selectbox("Slot", ROSTER_SLOTS, index=len(ROSTER_SLOTS) - 1)
        assumed = salary.number_input(
            "Assumed salary (optional)",
            min_value=0,
            value=None,
            step=500_000,
            placeholder="Use the contract file",
            help="A salary of your own for this player. Leave it empty to use the contract "
            "file's figure.",
        )
        if button.form_submit_button("Add", type="primary", icon=":material/person_add:"):
            if player_id is None:
                st.error("Choose a player first.", icon=":material/error:")
            else:
                _apply(
                    lambda: data.lab().builder.add_player(
                        roster["roster_id"],
                        int(player_id),
                        slot=chosen_slot,
                        assumed_salary=None if assumed is None else int(assumed),
                    )
                )


def _apply(change) -> None:  # type: ignore[no-untyped-def]
    """Make a change to the roster and redraw, or say why it was refused."""
    try:
        change()
    except RosterError as error:
        st.error(str(error), icon=":material/error:")
    else:
        st.rerun()


def _players(summary: RosterSummary) -> None:
    players, roster = summary.players, summary.roster
    if players.empty:
        components.empty("No players yet", "Add the first one above.", icon=":material/group_add:")
        return
    catalog = data.lab().players.metrics
    editable = roster_table(players, catalog)
    fixed = [column for column in editable.columns if column not in EDITABLE]
    edited = st.data_editor(
        editable,
        hide_index=True,
        placeholder=EMPTY_CELL,
        disabled=fixed,
        key=f"roster_editor_{roster['roster_id']}_{roster['updated_at']}",
        height=components.table_height(len(editable)),
        row_height=components.ROW,
        column_config={
            "slot": st.column_config.SelectboxColumn(
                "Slot",
                options=list(ROSTER_SLOTS),
                required=True,
                width=90,
                help="A starting position or the bench. A starting slot holds one player: "
                "whoever held it moves to the bench.",
            ),
            "player_name": st.column_config.Column("Player", width=165),
            "position": st.column_config.Column("Pos", width=60),
            "age": st.column_config.Column(
                "Age", width=55, help=f"Age in {roster['stats_season']}."
            ),
            **{
                key: st.column_config.Column(
                    catalog[key].label, width=65, help=catalog[key].description
                )
                for key in STATS
            },
            "salary": st.column_config.Column(
                "Salary", width=110, help=f"The salary counted, for {roster['payroll_season']}."
            ),
            "salary_source": st.column_config.Column(
                "Salary from", width=125, help="The contract file, or a figure you entered."
            ),
            "assumed_salary": st.column_config.NumberColumn(
                "Your assumed salary",
                width=160,
                min_value=0,
                step=500_000,
                format="dollar",
                help="Type a salary to override the contract file. Clear it to go back.",
            ),
            "remove": st.column_config.CheckboxColumn(
                "Remove", width=85, help="Tick to drop the player."
            ),
        },
    )
    _save_edits(int(roster["roster_id"]), editable, edited)
    st.caption(
        "Change a slot or an assumed salary directly in the table. Statistics are from "
        f"{roster['stats_season']}; salaries tagged as your assumption are yours, not the "
        "contract file's."
    )
    components.export(players.reset_index(), f"roster_{roster['roster_id']}", key="roster_csv")


def roster_table(players: pd.DataFrame, catalog: MetricCatalog) -> pd.DataFrame:
    """The roster as the table shows it: who, what they did, what they cost, and from where.

    Only the columns in :data:`EDITABLE` can be changed in the table. Where a salary
    comes from is spelled out on every row, so an assumption can never pass for a
    figure from the contract file.
    """
    return pd.DataFrame(
        {
            "slot": players["slot"],
            "player_name": players["player_name"],
            "position": players["position"],
            "age": players["age"],
            **{key: players[key].map(catalog[key].format_value) for key in STATS},
            "salary": players["salary"].map(formats.money),
            "salary_source": players["salary_source"].map(SOURCES.get).fillna(NO_SALARY),
            "assumed_salary": players["assumed_salary"].astype("Float64"),
            "remove": False,
        },
        index=players.index,
    )


def _save_edits(roster_id: int, before: pd.DataFrame, after: pd.DataFrame) -> None:
    """Carry what was changed in the table over to the stored roster."""
    builder = data.lab().builder
    changes = []
    for player_id in before.index:
        old, new = before.loc[player_id], after.loc[player_id]
        if bool(new["remove"]):
            changes.append(lambda player=player_id: builder.remove_player(roster_id, int(player)))
            continue
        if new["slot"] != old["slot"]:
            changes.append(
                lambda player=player_id, slot=new["slot"]: builder.move_player(
                    roster_id, int(player), slot
                )
            )
        was = None if formats.is_missing(old["assumed_salary"]) else int(old["assumed_salary"])
        now = None if formats.is_missing(new["assumed_salary"]) else int(new["assumed_salary"])
        if was != now:
            changes.append(
                lambda player=player_id, salary=now: builder.assume_salary(
                    roster_id, int(player), salary
                )
            )
    if not changes:
        return

    def apply_all() -> None:
        for change in changes:
            change()

    _apply(apply_all)


# --- what it adds up to ------------------------------------------------------------------------


def _indicators(summary: RosterSummary) -> None:
    catalog, roster = summary.metrics, summary.roster
    st.caption(
        f"What these players produced in {roster['stats_season']}, pooled as if they were one "
        "player, beside the same figure for the whole league. This describes the players "
        "on the teams they actually played for. It is not a projection of how they would "
        "play together, which depends on roles, minutes and fit."
    )
    rows = [
        {
            "Group": spec.category,
            "Indicator": spec.name,
            "Roster": spec.format_value(summary.indicators[spec.key]),
            "League": spec.format_value(summary.league[spec.key]),
            "What it is": spec.description,
        }
        for spec in catalog
    ]
    table = pd.DataFrame(rows)
    st.dataframe(
        table,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(table)),
        row_height=components.ROW,
        column_config={
            "League": st.column_config.Column(
                help="Every player's totals pooled. Missing for facts about a roster's "
                "make-up, which have no league value."
            ),
            "What it is": st.column_config.Column(width="large"),
        },
    )
    components.export(table, f"roster_indicators_{roster['roster_id']}", key="indicators_csv")
