"""Roster Optimizer: several strong rosters under a budget.

The user sets a payroll budget, a roster size, the roles and the positions a roster has
to cover, and anyone to lock in or leave out; the optimizer returns several distinct
rosters that project best under all of it. What it maximises is the value model's
projection of the players added up - the sum of the parts, with the model's own error -
and nothing more, because nothing more earned its place
(``docs/decisions/0012-roster-fit.md``). Several rosters are shown, not one, because any
one "best" rests on assumptions.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from front_office.domain.cap_rules import PayrollLine
from front_office.domain.optimizer import MAX_PLAYERS, BudgetMode, OptimizerRequest
from front_office.services import OptimizerError, OptimizerReport, OptimizerStatus, RosterPlan
from wb import components, data, formats, state
from wb.components import ASSUMPTION, DERIVED, EMPTY_CELL, MODELED, Figure

REQUEST = "opt_request"
SAVED = "opt_saved"
MILLION = 1_000_000
LINE_MODES = (
    BudgetMode.SALARY_CAP,
    BudgetMode.LUXURY_TAX,
    BudgetMode.FIRST_APRON,
    BudgetMode.SECOND_APRON,
)
AGES = (18, 42)
BY_TITLE = {mode.title: mode for mode in BudgetMode}
IDENTITY = {
    "player_name": st.column_config.Column("Player", width="medium", pinned=True),
    "team": st.column_config.Column("Team", help="The team the player is under contract to."),
    "position": "Pos",
    "age": "Age",
}


def render() -> None:
    filters = state.current()
    status = data.optimizer_status(filters.build)
    components.header(
        "Roster Optimizer",
        "Several strong rosters under a budget, from the value model's projections for "
        + (status.payroll_season or "the season ahead")
        + ". Estimates, and several rather than one, because the weights behind any one "
        "best roster are assumptions.",
        kinds=[MODELED, DERIVED, ASSUMPTION],
    )
    if not status.is_available:
        _unavailable(status)
        return
    defaults = data.optimizer_defaults(filters.build)
    pool = data.optimizer_pool(filters.build)
    st.caption(
        f"{status.pool} players have both a projection for {status.payroll_season} and a "
        f"salary for it on file: the pool. Roles and positions are the players' in "
        f"{status.stats_season}. {status.projected - status.pool} projected players have no "
        "salary on file and cannot be placed."
    )
    request = _form(status, defaults, pool)
    if request is None:
        return
    _results(filters, status, request)


def _unavailable(status: OptimizerStatus) -> None:
    body = status.reason or "The optimizer cannot run."
    if status.priced == 0 and status.payroll_season:
        body += " Salaries come from a contract file you import: fol contracts import FILE."
    components.empty("The optimizer needs more than it has", body, icon=":material/tune:")


# --- the request --------------------------------------------------------------------------


def _form(
    status: OptimizerStatus, defaults: OptimizerRequest, pool: pd.DataFrame
) -> OptimizerRequest | None:
    """The requirements as a form; the request last submitted, or ``None`` before one."""
    modes = [*LINE_MODES, BudgetMode.CUSTOM] if status.has_rules else [BudgetMode.CUSTOM]
    archetypes = data.lab().fit.archetypes()
    names = (pool["player_name"] + " · " + pool["team"].fillna("no team")).to_dict()
    with st.form("optimizer", border=True):
        st.markdown("**Payroll**")
        left, right = st.columns([2, 1])
        with left:
            title = st.segmented_control(
                "Budget",
                [mode.title for mode in modes],
                default=defaults.budget_mode.title,
                required=True,
                key="opt_mode",
                help="The line the payroll may not exceed. The lines are the season's cap rules.",
            )
            mode = BY_TITLE.get(title, defaults.budget_mode)
        with right:
            budget = st.number_input(
                "Owner's budget ($M)",
                min_value=1.0,
                max_value=1000.0,
                value=float((defaults.budget or _starting_budget(status)) / MILLION),
                step=1.0,
                key="opt_budget",
                help="Used when the budget is the owner's.",
            )
        floor = st.checkbox(
            "Also reach the minimum team salary",
            value=False,
            key="opt_floor",
            disabled=not status.has_rules,
            help="A team under the floor pays the difference anyway.",
        )

        st.markdown("**Roster**")
        size = st.slider(
            "Players",
            5,
            MAX_PLAYERS,
            (defaults.min_players, defaults.max_players),
            key="opt_size",
            help="Standard contracts the roster holds. The season's rules say what a team carries.",
        )
        st.caption(
            "At least this many players who fill each role, by the rules on the Player Value page:"
        )
        role_counts = {}
        columns = st.columns(4)
        for number, archetype in enumerate(archetypes):
            with columns[number % 4]:
                role_counts[archetype.key] = st.number_input(
                    archetype.name,
                    min_value=0,
                    max_value=MAX_PLAYERS,
                    value=int(defaults.roles.get(archetype.key, 0)),
                    key=f"opt_role_{archetype.key}",
                )
        st.caption("At least this many by position group:")
        groups = st.columns(3)
        with groups[0]:
            guards = st.number_input(
                "Guards", 0, MAX_PLAYERS, int(defaults.guards), key="opt_guards"
            )
        with groups[1]:
            wings = st.number_input("Wings", 0, MAX_PLAYERS, int(defaults.wings), key="opt_wings")
        with groups[2]:
            bigs = st.number_input("Big men", 0, MAX_PLAYERS, int(defaults.bigs), key="opt_bigs")

        st.markdown("**Players**")
        locked = st.multiselect(
            "Lock in", list(names), format_func=names.get, key="opt_locked",
            help="Every roster holds these players, whatever the limits below.",
        )  # fmt: skip
        excluded = st.multiselect(
            "Leave out", list(names), format_func=names.get, key="opt_excluded"
        )
        limits = st.columns(3)
        with limits[0]:
            ages = st.slider("Age", AGES[0], AGES[1], AGES, key="opt_ages")
        with limits[1]:
            max_salary = st.number_input(
                "Highest salary ($M, 0 for none)", 0.0, 500.0, 0.0, step=1.0, key="opt_max_salary"
            )
        with limits[2]:
            min_rating = st.number_input(
                "Least projected rating (blank for none)",
                value=None,
                step=0.5,
                key="opt_min_rating",
                help="Relative to the league, in points of net rating. The rosters shown "
                "ignore it if nothing reaches it, and say so.",
            )

        st.markdown("**Answers**")
        answers = st.columns(2)
        with answers[0]:
            solutions = st.slider(
                "Rosters to find", 1, 8, int(defaults.solutions), key="opt_solutions"
            )
        with answers[1]:
            distinct = st.slider(
                "Each differs from the others by at least", 1, 6, int(defaults.distinct_by),
                key="opt_distinct", help="Players that cannot be shared between two rosters.",
            )  # fmt: skip
        submitted = st.form_submit_button("Find rosters", type="primary", icon=":material/tune:")

    if submitted:
        try:
            st.session_state[REQUEST] = OptimizerRequest(
                payroll_season=status.payroll_season or "",
                stats_season=status.stats_season or "",
                budget_mode=mode,
                budget=int(round(budget * MILLION)) if mode is BudgetMode.CUSTOM else None,
                enforce_minimum_salary=bool(floor and status.has_rules),
                min_players=int(size[0]),
                max_players=int(size[1]),
                roles={key: int(count) for key, count in role_counts.items() if count > 0},
                guards=int(guards),
                wings=int(wings),
                bigs=int(bigs),
                min_rating=None if min_rating is None else float(min_rating),
                max_salary=None if not max_salary else int(round(max_salary * MILLION)),
                min_age=None if ages[0] <= AGES[0] else int(ages[0]),
                max_age=None if ages[1] >= AGES[1] else int(ages[1]),
                locked=tuple(int(player) for player in locked),
                excluded=tuple(int(player) for player in excluded),
                solutions=int(solutions),
                distinct_by=int(distinct),
            )
            st.session_state.pop(SAVED, None)
        except ValidationError as error:
            st.error("; ".join(item["msg"] for item in error.errors()), icon=":material/error:")
            return None
    return st.session_state.get(REQUEST)


def _starting_budget(status: OptimizerStatus) -> int:
    rules = data.lab().rules(status.payroll_season or "")
    return int(rules.thresholds.salary_cap) if rules is not None else 100 * MILLION


# --- the rosters ---------------------------------------------------------------------------


def _results(filters, status: OptimizerStatus, request: OptimizerRequest) -> None:  # type: ignore[no-untyped-def]
    try:
        report = data.optimizer_solve(filters.build, request)
    except OptimizerError as error:
        components.empty("The request cannot be run", str(error), icon=":material/error:")
        return
    if not report.found:
        components.empty(
            "No roster meets these requirements",
            " ".join(report.outcome.reasons)
            or "Nothing satisfies them together within the budget.",
            icon=":material/search_off:",
        )
        return
    st.subheader(f"{len(report.plans)} rosters under {formats.money_compact(report.budget)}")
    error = formats.MISSING if report.error is None else f"±{report.error:.1f}"
    said = (
        f"From {report.pool_size} players, each roster below projects best under the "
        f"requirements once the rosters before it are set aside: no two share more than all "
        f"but {request.distinct_by} of their players. The rating is the sum of the parts - the "
        f"value model's projections added up for the minutes projected, with replacement "
        f"players filling the rest - and the model misses a real team by {error} points on "
        "seasons it had not seen. Salaries are from your contract file. Nothing here is a "
        "recommendation."
    )
    if report.outcome.status == "time_limit":
        said += " The solver ran out of time on at least one roster, which may not be the best."
    st.caption(said)
    for reason in report.outcome.reasons:
        components.tagged(("Note", ":material/info:", "orange"), reason[0].upper() + reason[1:])

    _comparison(report)
    tabs = st.tabs(
        [f"Roster {plan.number}" for plan in report.plans], key="opt_tab", on_change="rerun"
    )
    for tab, plan in zip(tabs, report.plans, strict=True):
        with tab:
            _plan(report, plan)


def _comparison(report: OptimizerReport) -> None:
    rows = []
    for plan in report.plans:
        solution = plan.solution
        row = {
            "Roster": f"Roster {plan.number}",
            "Projected rating": solution.rating,
            "Payroll": solution.payroll,
            "Room": plan.room,
            "Players": solution.players,
            "Minutes": solution.minutes_covered,
            **{f"{key}": count for key, count in solution.roles.items()},
            "Guards": solution.guards,
            "Wings": solution.wings,
            "Big men": solution.bigs,
            "vs Roster 1": ""
            if plan.number == 1
            else f"{len(plan.added)} in, {len(plan.removed)} out",
        }
        rows.append(row)
    table = pd.DataFrame(rows)
    archetypes = {item.key: item.name for item in data.lab().fit.archetypes()}
    st.dataframe(
        table.style.format(
            {
                "Projected rating": "{:+.1f}".format,
                "Payroll": formats.money_compact,
                "Room": formats.money_compact,
                "Minutes": formats.share,
            }
        ),
        hide_index=True,
        height=components.table_height(len(table)),
        row_height=components.ROW,
        column_config={
            "Projected rating": st.column_config.Column(
                help="Net rating relative to the league, as the parts add up."
            ),
            "Minutes": st.column_config.Column(
                help="The players' projected minutes as a share of a season's."
            ),
            **{
                key: st.column_config.Column(name)
                for key, name in archetypes.items()
                if key in table.columns
            },
        },
    )


def _plan(report: OptimizerReport, plan: RosterPlan) -> None:
    solution = plan.solution
    payroll = plan.payroll
    items = [
        Figure(
            "Projected rating",
            f"{solution.rating:+.1f}",
            f"the parts add up to {solution.rating_unscaled:+.1f}"
            if solution.rating < solution.rating_unscaled - 0.05
            else "relative to the league",
            help="The sum of the parts, scaled down where the players' minutes add up to more "
            "than a season.",
        ),
        Figure(
            "Payroll",
            formats.money_compact(solution.payroll),
            f"{formats.money_compact(plan.room)} under the budget",
        ),
        Figure(
            "Minutes",
            formats.share(solution.minutes_covered, 0),
            "of a season's, as projected",
            help="Above 100% everyone plays a little less than projected.",
        ),
    ]
    if payroll is not None:
        cap = payroll.position(PayrollLine.SALARY_CAP)
        items.append(
            Figure(
                "Share of cap",
                formats.share(payroll.cap_share),
                "Under the cap" if cap.room >= 0 else f"Over by {formats.money_compact(-cap.room)}",
                help=formats.LINES_EXPLAINED,
            )
        )
    components.figures(items)
    if plan.number > 1:
        st.caption(
            f"Against Roster 1: in {_listed(plan.added)}; out {_listed(plan.removed)}."
            if plan.added or plan.removed
            else "The same players as Roster 1."
        )
    catalog = data.lab().value.metrics
    shown = plan.players
    st.dataframe(
        formats.styled(
            shown,
            catalog,
            {
                "salary": formats.money,
                "years_remaining": formats.number,
                "projection_reliability": formats.share,
            },
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={
            **IDENTITY,
            "salary": st.column_config.Column(
                "Salary", help=f"In {report.request.payroll_season}, from your contract file."
            ),
            "years_remaining": st.column_config.Column("Years left"),
            **components.metric_columns(
                catalog,
                ["projected_impact", "projected_share", "projected_wins", "projection_reliability"],
            ),
            "role": st.column_config.Column("Main role"),
            "roles": st.column_config.Column("Roles filled", width="medium"),
        },
    )
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            shown.reset_index(), f"optimizer_roster_{plan.number}", key=f"opt_csv_{plan.number}"
        )
        with st.popover("Save as a Team Builder roster", icon=":material/save:"):
            name = st.text_input(
                "Name",
                value=f"Optimized roster {plan.number}",
                max_chars=80,
                key=f"opt_name_{plan.number}",
            )
            if st.button("Save", key=f"opt_save_{plan.number}", type="primary"):
                try:
                    roster = data.optimizer_save(shown.index.tolist(), name, report.request)
                except Exception as error:  # noqa: BLE001 - whatever the builder refuses is shown
                    st.error(str(error), icon=":material/error:")
                else:
                    st.session_state[SAVED] = (plan.number, name, roster)
    saved = st.session_state.get(SAVED)
    if saved and saved[0] == plan.number:
        st.success(
            f"Saved as “{saved[1]}”. The Team Builder has it.", icon=":material/check_circle:"
        )


def _listed(names) -> str:  # type: ignore[no-untyped-def]
    names = list(names)
    if not names:
        return "nobody"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]
