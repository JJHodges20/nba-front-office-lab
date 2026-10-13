"""Scenario Simulator: what a change to a roster would do to its season.

A real team as it stands for the season ahead, or a roster built in the Team Builder;
players added and removed, games missed, development, minutes - the user's assumptions,
and the page says so - and thousands of seasons drawn for the roster before and after,
from parts the lab has tested. Everything shown is an estimate with an interval, never
a verdict, and the sidebar's phase and comparison window do not narrow this page.
"""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from front_office.domain.scenario import (
    FULL_SEASON_GAMES,
    MAX_DEVELOPMENT,
    Adjustment,
    Availability,
    Development,
    Scenario,
    SubjectKind,
)
from front_office.domain.simulator import SimulatorModel
from front_office.services import ScenarioReport, SimulatorStatus, probability_key
from front_office.services.simulator import ADDED, KEPT, REMOVED
from wb import ask, charts, components, data, formats, state
from wb.components import ASSUMPTION, EMPTY_CELL, MODELED, Figure
from wb.state import Filters

TABS = ("Before and after", "Players", "Profile", "The season ahead", "The evidence")
TAB = "sim_tab"
SUBJECTS = {SubjectKind.TEAM.value: "Team", SubjectKind.ROSTER.value: "Built roster"}
AVAILABILITY_TITLES = {item.value: item.title for item in Availability}
DEVELOPMENT_TITLES = {item.value: item.title for item in Development}
SUBJECT, TEAM, ROSTER = "sim_subject", "sim_team", "sim_roster"
ADD, REMOVE = "sim_add", "sim_remove"
AVAILABILITY, DEVELOPMENT, SIMULATIONS = "sim_availability", "sim_development", "sim_count"
EDITS = "sim_edits"
NAME, SAVE, SAVED = "sim_name", "sim_save", "sim_saved"
COUNTS = (2_000, 5_000, 10_000, 20_000)
FIT = "fol simulate fit --write"
SIDES = {"before": "Before", "after": "After"}
PLAYOFFS, TITLE = probability_key("made_playoffs"), probability_key("won_championship")
STATUS_WORDS = {KEPT: "Kept", ADDED: "Added", REMOVED: "Removed"}
EDITABLE = ("games_missed", "development", "share", "salary")


def render() -> None:
    filters = state.current()
    status = data.simulator_status(filters.build)
    components.header(
        "Scenario Simulator",
        "What a change to a roster would do to its season: thousands of seasons drawn, "
        "before and after, from the value model's projections and the postseason model. "
        "The roster and its assumptions are yours; what they come to is the model's.",
        kinds=[MODELED, ASSUMPTION],
    )
    ask.button(ask.from_filters("Scenario Simulator", filters))
    if not status.is_available:
        components.empty(
            "The simulator cannot run yet",
            f"{status.reason[0].upper()}{status.reason[1:]}" if status.reason else "",
            icon=":material/casino:",
        )
        return
    model = data.simulator_model(filters.build, status.revision)
    if model is None:
        components.empty("No simulator parameters on file", f"Measure them: {FIT}")
        return
    _notices(status)
    subject, key, name = _subject(filters, status)
    if subject is None or key is None:
        return
    scenario, base = _changes(filters, status, model, subject, key)
    report = _run(filters, status, scenario)
    compare, players, profile, league, evidence = st.tabs(list(TABS), key=TAB, on_change="rerun")
    with compare:
        _before_and_after(report, model)
    with players:
        _players(report, scenario, base, model)
        _save(scenario, name)
    with profile:
        _profile(report)
    with league:
        _league(filters, status, scenario)
    with evidence:
        _evidence(model)


def _notices(status: SimulatorStatus) -> None:
    if not status.is_current:
        components.tagged(
            components.OUT_OF_DATE,
            "The simulator's parameters were measured against value model "
            f"{status.value_model_version}; the database was built with "
            f"{status.applied_value_version}. Run: {FIT}",
        )


# --- the subject ----------------------------------------------------------------------------


def _subject(
    filters: Filters, status: SimulatorStatus
) -> tuple[SubjectKind | None, int | None, str]:
    rosters = data.rosters()
    options = [SubjectKind.TEAM.value, *([SubjectKind.ROSTER.value] if not rosters.empty else [])]
    subject = st.segmented_control(
        "Subject",
        options,
        format_func=SUBJECTS.get,
        default=SubjectKind.TEAM.value,
        required=True,
        key=SUBJECT,
    )
    if subject == SubjectKind.TEAM:
        teams = data.simulator_teams(filters.build, status.revision)
        if teams.empty:
            components.empty(
                "No team has a projected player",
                f"The value model projects nobody into {status.upcoming}.",
                icon=":material/groups:",
            )
            return None, None, ""
        ids = teams.index.tolist()
        default = filters.team_id if filters.team_id in ids else ids[0]
        if st.session_state.get(TEAM) not in ids:
            st.session_state[TEAM] = default
        team = st.selectbox(
            "Team",
            ids,
            format_func=lambda value: (
                f"{teams.at[value, 'full_name']} ({teams.at[value, 'players']} projected)"
            ),
            key=TEAM,
            width=420,
            help=f"A team as it stands for {status.upcoming}: the players whose current team "
            "it is, with the value model's projections. The sidebar's team is chosen first.",
        )
        return subject, int(team), str(teams.at[team, "full_name"])
    ids = rosters["roster_id"].tolist()
    names = rosters.set_index("roster_id")["name"]
    roster = st.selectbox(
        "Roster", ids, format_func=lambda value: names[value], key=ROSTER, width=420
    )
    return subject, int(roster), str(names[roster])


# --- the changes ----------------------------------------------------------------------------


def _changes(
    filters: Filters,
    status: SimulatorStatus,
    model: SimulatorModel,
    subject: SubjectKind,
    key: int,
) -> tuple[Scenario, pd.DataFrame]:
    """The scenario as the controls say, and the subject's players as they stand."""
    unchanged = Scenario(subject=subject, key=key, simulations=model.spec.simulations)
    base = _players_of(filters, status, unchanged)
    pool = data.simulator_pool(filters.build, status.revision)
    present = set(base.index)
    with st.container(border=True):
        st.markdown("**Changes**")
        one, two = st.columns(2)
        removed = one.multiselect(
            "Remove players",
            base.index.tolist(),
            format_func=lambda value: str(base.at[value, "player_name"]),
            key=REMOVE,
            help="Players let go or sent away. What they would bring back is added below.",
        )
        candidates = pool.index[~pool.index.isin(list(present))].tolist()
        added = two.multiselect(
            "Add players",
            candidates,
            format_func=lambda value: str(pool.at[value, "label"]),
            key=ADD,
            help="Signings, or the players coming back in a trade: anyone with a projection "
            f"for {status.upcoming}.",
        )
        # Lists, not rows of buttons: the choices' names do not fit half a narrow window, and
        # one was out of reach at 1024px (UI polish P3).
        three, four = st.columns(2)
        availability = three.selectbox(
            "Games missed",
            list(AVAILABILITY_TITLES),
            format_func=AVAILABILITY_TITLES.get,
            index=list(AVAILABILITY_TITLES).index(Availability.AS_PROJECTED.value),
            key=AVAILABILITY,
            help="\n\n".join(f"**{item.title}**: {item.description}" for item in Availability),
        )
        development = four.selectbox(
            "Development",
            list(DEVELOPMENT_TITLES),
            format_func=DEVELOPMENT_TITLES.get,
            index=list(DEVELOPMENT_TITLES).index(Development.EXPECTED.value),
            key=DEVELOPMENT,
            help="\n\n".join(f"**{item.title}**: {item.description}" for item in Development),
        )
        default = model.spec.simulations if model.spec.simulations in COUNTS else COUNTS[2]
        simulations = st.selectbox(
            "Seasons drawn",
            list(COUNTS),
            index=COUNTS.index(default),
            format_func=lambda value: f"{value:,}",
            key=SIMULATIONS,
            width=240,
            help="How many seasons to draw. More is steadier and slower.",
        )
    members = [p for p in base.index if p not in removed] + [p for p in added if p not in present]
    adjustments = _adjustments(members)
    scenario = Scenario(
        subject=subject,
        key=key,
        added=tuple(int(p) for p in added),
        removed=tuple(int(p) for p in removed),
        adjustments=adjustments,
        availability=availability,
        development=development,
        simulations=int(simulations),
    )
    return scenario, base


def _players_of(filters: Filters, status: SimulatorStatus, scenario: Scenario) -> pd.DataFrame:
    if scenario.subject == SubjectKind.TEAM:
        return data.simulator_team_players(filters.build, status.revision, scenario)
    return data.simulator_roster_players(
        filters.build, status.revision, data.roster_stamp(scenario.key), scenario
    )


def _editor_key(members: list[int]) -> str:
    """The per-player table's key: edits belong to one membership and reset with it."""
    digest = hashlib.sha256(",".join(str(p) for p in members).encode("utf-8")).hexdigest()[:10]
    return f"{EDITS}_{digest}"


def _adjustments(members: list[int]) -> dict[int, Adjustment]:
    """What the per-player table holds, read from the session before it is drawn again."""
    edits = st.session_state.get(_editor_key(members))
    if not isinstance(edits, dict):
        return {}
    out: dict[int, Adjustment] = {}
    for position, changes in edits.get("edited_rows", {}).items():
        try:
            player = members[int(position)]
        except (ValueError, IndexError):
            continue
        fields = {}
        for column in EDITABLE:
            value = changes.get(column)
            if value is None or value == "" or formats.is_missing(value):
                continue
            fields[column] = int(value) if column == "salary" else float(value)
        if fields:
            out[int(player)] = Adjustment(**fields)
    return out


def _run(filters: Filters, status: SimulatorStatus, scenario: Scenario) -> ScenarioReport:
    if scenario.subject == SubjectKind.TEAM:
        return data.simulator_team_run(
            filters.build, status.revision, status.postseason_revision, scenario
        )
    return data.simulator_roster_run(
        filters.build,
        status.revision,
        status.postseason_revision,
        data.roster_stamp(scenario.key),
        scenario,
    )


# --- before and after ----------------------------------------------------------------------


def _before_and_after(report: ScenarioReport, model: SimulatorModel) -> None:
    before, after = report.before, report.after
    confidence = f"{model.spec.wins_interval:.0%}"
    components.figures(
        [
            Figure(
                "Payroll",
                formats.money_compact(after.payroll),
                # How many are unpriced is said under the tiles: in the tile it was cut off
                # at 1366px (UI polish P6, audit finding F21).
                _was(formats.money_compact(before.payroll)),
                help="The salaries on file for the season ahead and any you assumed; "
                "understated while any player is unpriced.",
            ),
            Figure(
                "Projected net rating",
                f"{after.rating:+.1f}",
                _was(f"{before.rating:+.1f}"),
                help="The roster's strength relative to the league, averaged over the "
                "seasons drawn: five slots of replacement level plus what each player adds "
                "above it for the minutes drawn.",
            ),
            Figure(
                "Projected wins",
                f"{after.wins:.0f}",
                f"{after.wins_low:.0f} to {after.wins_high:.0f}; {_was(f'{before.wins:.0f}')}",
                help=f"Wins per 82 averaged over the seasons drawn, with the {confidence} "
                "interval of the seasons.",
            ),
            Figure(
                "Making the playoffs",
                formats.share(after.chance("made_playoffs")),
                _was(formats.share(before.chance("made_playoffs"))),
                help="The share of seasons drawn, under the postseason model's season steps.",
            ),
            Figure(
                "Winning the title",
                formats.share(after.chance("won_championship")),
                _was(formats.share(before.chance("won_championship"))),
                help="The same for the championship.",
            ),
        ]
    )
    unpriced = (
        f" The payroll leaves out {after.unpriced} player{'s' if after.unpriced != 1 else ''} "
        "with no salary on file, so it is understated."
        if after.unpriced
        else ""
    )
    if not report.is_changed:
        st.caption(
            f"**{report.name}** as it stands for {report.season}, drawn {after.seasons:,} "
            "times. Nothing is changed yet: remove or add players, or set the presets, and "
            "the figures above show before and after." + unpriced
        )
    else:
        st.caption(
            f"**{report.name}** for {report.season}, drawn {after.seasons:,} times as it "
            f"stands and {after.seasons:,} times with your changes"
            + _changes_said(report)
            + "."
            + unpriced
        )
    _comparison_table(report)
    _stages_chart(report)
    _wins_chart(report, model)
    _unprojected(report)


def _was(text: str) -> str:
    return f"was {text}"


def _changes_said(report: ScenarioReport) -> str:
    scenario = report.scenario
    names = report.players["player_name"]
    parts = []
    if scenario.added:
        parts.append(f"added {_listed([str(names.get(p, p)) for p in scenario.added])}")
    if scenario.removed:
        parts.append(f"removed {_listed([str(names.get(p, p)) for p in scenario.removed])}")
    if scenario.availability is not Availability.AS_PROJECTED:
        parts.append(f"games missed: {scenario.availability.title.lower()}")
    if scenario.development is not Development.EXPECTED:
        parts.append(f"development: {scenario.development.title.lower()}")
    touched = [p for p, item in scenario.adjustments.items() if not item.is_empty]
    if touched:
        parts.append(f"{len(touched)} player{'s' if len(touched) != 1 else ''} adjusted")
    return (": " + "; ".join(parts)) if parts else ""


def _comparison_table(report: ScenarioReport) -> None:
    frame = report.comparison
    shown = pd.DataFrame(
        {
            "Figure": frame["label"],
            "Before": [
                _formatted(v, f) for v, f in zip(frame["before"], frame["format"], strict=True)
            ],
            "After": [
                _formatted(v, f) for v, f in zip(frame["after"], frame["format"], strict=True)
            ],
            "Change": [
                _formatted(v, f, signed=True)
                for v, f in zip(frame["change"], frame["format"], strict=True)
            ],
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={"Figure": st.column_config.Column(width="medium")},
    )
    st.caption(
        "Every figure is the mean over the seasons drawn. Chances come from the postseason "
        "model's season steps, read for a team of the strength each season drew - the "
        "field is not in them, so they are the chances of a team like this entering any "
        "season."
    )


def _formatted(value: float, kind: str, *, signed: bool = False) -> str:
    if formats.is_missing(value):
        return formats.MISSING
    if kind == "money":
        text = formats.money_compact(abs(value)) if signed else formats.money_compact(value)
        return (f"{'+' if value >= 0 else '-'}{text}") if signed else text
    if kind == "percent":
        return f"{value * 100:+.1f} pts" if signed else formats.share(value)
    if kind == "signed" or signed:
        return f"{value:+.1f}"
    return f"{value:.1f}"


def _stages_chart(report: ScenarioReport) -> None:
    rows = []
    for side, outcome in (("before", report.before), ("after", report.after)):
        stages = outcome.stages
        for item in stages.itertuples(index=False):
            rows.append(
                {
                    "label": item.label,
                    "side": SIDES[side],
                    "probability": item.probability,
                    "text": f"{formats.share(item.probability)} (95% interval "
                    f"{formats.share(item.low, 0)} to {formats.share(item.high, 0)})",
                }
            )
    frame = pd.DataFrame(rows)
    st.markdown("**The chance of each stage, before and after**")
    figure = charts.comparison_dots(
        frame,
        metric="label",
        who="side",
        percentile="probability",
        text="text",
        palette=components.colors(),
        axis_title="Chance",
        axis_range=(-0.02, 1.02),
        tickvals=(0, 0.25, 0.5, 0.75, 1.0),
        tickformat=".0%",
        reference=None,
    )
    table = report.before.stages[["label", "probability", "low", "high"]].merge(
        report.after.stages[["label", "probability", "low", "high"]],
        on="label",
        suffixes=("_before", "_after"),
    )
    components.chart(
        figure,
        table.rename(columns={"label": "stage"}),
        key="sim_stages",
        filename=f"scenario_stages_{report.scenario.fingerprint}",
        formats=dict.fromkeys(
            (
                "probability_before",
                "low_before",
                "high_before",
                "probability_after",
                "low_after",
                "high_after",
            ),
            formats.share,
        ),
    )
    st.caption(
        "The share of seasons drawn that reached each stage. The table carries the 95% "
        "interval the postseason model's resampled steps give each chance."
    )


def _wins_chart(report: ScenarioReport, model: SimulatorModel) -> None:
    before, after = report.before.wins_distribution, report.after.wins_distribution
    frame = pd.DataFrame(
        {
            "wins": before["wins"],
            "before": before["share"],
            "after": after["share"].to_numpy(),
        }
    )
    frame["before_text"] = frame["before"].map(lambda v: formats.share(v))
    frame["after_text"] = frame["after"].map(lambda v: formats.share(v))
    st.markdown("**How the seasons drawn came out**")
    figure = charts.lines(
        frame,
        x="wins",
        series={"before": "Before", "after": "After"},
        text={"before": "before_text", "after": "after_text"},
        palette=components.colors(),
        y_title="Share of seasons drawn",
        tickformat=".0%",
        x_title="Wins per 82",
        x_dtick=10,
    )
    components.chart(
        figure,
        frame[["wins", "before", "after"]],
        key="sim_wins",
        filename=f"scenario_wins_{report.scenario.fingerprint}",
        formats={"before": formats.share, "after": formats.share},
    )
    st.caption(
        f"Wins per 82 in each season drawn. The spread is the value model's miss on a team "
        f"({model.strength_error:.1f} points of net rating once a season's own noise is "
        "taken out), the players' own spread, a season's noise "
        f"({model.season_noise:.1f}) and the residual wins carry ({model.wins_residual:.1f}); "
        "see The evidence."
    )


def _unprojected(report: ScenarioReport) -> None:
    missing = report.after.unprojected
    if missing:
        st.caption(
            f"Without a projection, counted as replacement players: {_listed(list(missing))}. "
            "The value model projects only players with a season on record."
        )


# --- the players ------------------------------------------------------------------------------


def _players(
    report: ScenarioReport, scenario: Scenario, base: pd.DataFrame, model: SimulatorModel
) -> None:
    players = report.players
    members = [int(p) for p in players.index[players["status"] != REMOVED]]
    st.caption(
        "Each player with the value model's projection for the season ahead, and the "
        "columns you can set: games missed out of 82, development in points of impact, a "
        "share of the team's minutes (one is every minute), a salary. A cell left empty "
        "takes the preset or the projection. Everything you type is your assumption."
    )
    editable = players[players["status"] != REMOVED].copy()
    if editable.empty:
        st.caption(
            "Nobody is left on the roster: add players, or take some off the removed "
            "list. Every slot is replacement level until then."
        )
        _roster_captions(report, players, model)
        return
    table = pd.DataFrame(
        {
            "player_name": editable["player_name"],
            "status": editable["status"].map(STATUS_WORDS),
            "projected_impact": editable["projected_impact"],
            "projected_share": editable["projected_share"],
            "projection_reliability": editable["projection_reliability"],
            "games_missed": editable["games_missed"].astype("Float64"),
            "development": editable["development"].astype("Float64"),
            "share": editable["share"].astype("Float64"),
            "salary": editable["salary"]
            .where(editable["salary_source"] == "assumed")
            .astype("Float64"),
            "contract_salary": editable["salary"].where(editable["salary_source"] == "contract"),
            "note": editable["note"],
        }
    )
    st.data_editor(
        table,
        key=_editor_key(members),
        hide_index=True,
        placeholder=EMPTY_CELL,
        disabled=[c for c in table.columns if c not in EDITABLE],
        height=components.table_height(min(len(table), 18)),
        row_height=components.ROW,
        column_config={
            "player_name": st.column_config.Column("Player", width="medium", pinned=True),
            "status": "Status",
            "projected_impact": st.column_config.NumberColumn("Projected IMP", format="%+.2f"),
            "projected_share": st.column_config.NumberColumn("Projected share", format="%.2f"),
            "projection_reliability": st.column_config.NumberColumn("Reliability", format="%.2f"),
            "games_missed": st.column_config.NumberColumn(
                "Games missed",
                min_value=0,
                max_value=FULL_SEASON_GAMES,
                step=1,
                help="Your assumption: games the player misses out of 82.",
            ),
            "development": st.column_config.NumberColumn(
                "Development",
                min_value=-MAX_DEVELOPMENT,
                max_value=MAX_DEVELOPMENT,
                step=0.1,
                format="%+.1f",
                help="Your assumption: points of impact above or below the projection.",
            ),
            "share": st.column_config.NumberColumn(
                "Share",
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                format="%.2f",
                help="Your assumption: the share of the team's minutes the player plays.",
            ),
            "salary": st.column_config.NumberColumn(
                "Assumed salary",
                min_value=0,
                step=100_000,
                format="$%d",
                help="Your assumption, in place of the contract file.",
            ),
            "contract_salary": st.column_config.NumberColumn("Contract salary", format="$%d"),
            "note": "Note",
        },  # fmt: skip
    )
    _roster_captions(report, players, model)


def _roster_captions(report: ScenarioReport, players: pd.DataFrame, model: SimulatorModel) -> None:
    removed = players[players["status"] == REMOVED]
    if not removed.empty:
        st.caption(f"Removed: {_listed(removed['player_name'].astype(str).tolist())}.")
    st.caption(
        f"Shares add up to {report.after.shares:.2f} of the five on the floor on average "
        f"({report.before.shares:.2f} before); what is not covered is replacement level, "
        "and more than five is scaled down. Typical rotation players miss "
        f"{model.missed.mean:.0%} of a season."
    )


def _save(scenario: Scenario, name: str) -> None:
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        roster_name = st.text_input(
            "Save as a roster", value=f"{name} scenario", key=NAME, width=360,
            help="The scenario's players, with any salary you assumed, as a Team Builder roster.",
        )  # fmt: skip
        if st.button("Save", key=SAVE, icon=":material/save:"):
            if not roster_name.strip():
                components.alert("error", "Give the roster a name first.")
            else:
                roster_id = data.simulator_save(scenario, roster_name.strip())
                st.session_state[SAVED] = roster_id
    saved = st.session_state.get(SAVED)
    if saved is not None:
        components.alert("success", f"Saved as roster {saved}. Open it in the Team Builder.")


# --- the profile -----------------------------------------------------------------------------


def _profile(report: ScenarioReport) -> None:
    profile = report.profile
    if profile.empty or profile["before"].isna().all():
        components.empty(
            "No profile to place",
            f"The fit measures need the players' statistics from {report.stats_season} and "
            "the season's team profiles.",
        )
        return
    st.caption(
        f"The roster's fit measures, as the Roster Fit page describes them, for what the "
        f"players showed in {report.stats_season}, each weighted by the share of the "
        "minutes the scenario gives them, and placed among that season's teams as a "
        "percentile. Description, not prediction: the evidence found no fit measure that "
        "predicts beyond the sum of the parts."
    )
    shown = profile.assign(
        direction=profile["higher_is_better"]
        .map({True: "higher is better", False: "lower is better"})
        .fillna("no better or worse"),
    )
    st.dataframe(
        shown[["area", "name", "before", "after", "change", "direction"]],
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 20)),
        row_height=components.ROW,
        column_config={
            "area": "Area",
            "name": st.column_config.Column("Measure", width="medium"),
            "before": st.column_config.NumberColumn("Before (percentile)", format="%.0f"),
            "after": st.column_config.NumberColumn("After (percentile)", format="%.0f"),
            "change": st.column_config.NumberColumn("Change", format="%+.0f"),
            "direction": "Direction",
        },
    )


# --- the season ahead ---------------------------------------------------------------------


def _league(filters: Filters, status: SimulatorStatus, scenario: Scenario) -> None:
    league = data.simulator_league(filters.build, status.revision, status.postseason_revision)
    if league.empty:
        components.empty("Nothing to draw", "No team has a projected player.")
        return
    st.caption(
        f"Every team as it stands for {status.upcoming}, with nothing assumed, drawn the same "
        "way: the players whose current team it is, each with the value model's projection, "
        "missing games as rotation players have. Each team is drawn alone - the field is not "
        "in it - so the chances need not add up across the league."
    )
    plotted = league.assign(
        text="<b>"
        + league["team_name"]
        + "</b><br>Projected wins "
        + league["wins"].map("{:.0f}".format)
        + " ("
        + league["wins_low"].map("{:.0f}".format)
        + " to "
        + league["wins_high"].map("{:.0f}".format)
        + ")<br>Rating "
        + league["rating"].map("{:+.1f}".format)
        + ", playoffs "
        + league[PLAYOFFS].map(formats.share)
        + ", title "
        + league[TITLE].map(formats.share),
    )
    figure = charts.interval_rows(
        plotted,
        label="team_name",
        value="wins",
        low="wins_low",
        high="wins_high",
        text="text",
        palette=components.colors(),
        value_title="Projected wins per 82, with the interval of the seasons drawn",
        tickformat=".0f",
    )
    shown = league[
        [
            "team_name",
            "conference",
            "players",
            "projected",
            "rating",
            "wins",
            "wins_low",
            "wins_high",
            PLAYOFFS,
            TITLE,
        ]
    ]
    components.chart(
        figure,
        shown,
        key="sim_league",
        filename=f"season_ahead_{status.upcoming}",
        formats={
            "rating": "{:+.1f}".format,
            "wins": "{:.1f}".format,
            "wins_low": "{:.1f}".format,
            "wins_high": "{:.1f}".format,
            PLAYOFFS: formats.share,
            TITLE: formats.share,
        },
    )
    mine = scenario.key if scenario.subject == SubjectKind.TEAM else None
    if mine is not None and mine in league.index:
        row = league.loc[mine]
        st.caption(
            f"**{row['team_name']}** is drawn at {row['wins']:.0f} wins and "
            f"{formats.share(row[TITLE])} for the title as it stands; the other tabs show "
            "what your changes do to that."
        )


# --- the evidence -------------------------------------------------------------------------


def _evidence(model: SimulatorModel) -> None:
    test = model.test
    st.markdown(
        "A simulated season draws every player's impact around the value model's "
        "projection, draws the games each misses, adds the parts up for the minutes drawn, "
        "adds the miss on a team's strength the value model's test leaves and a season's own "
        "noise, turns the rating into wins, and reads the postseason model's season steps. "
        "The value model and the postseason model were each tested on seasons they had not "
        "seen - see Player Value and Postseason Outlook. What is measured here:"
    )
    components.figures(
        [
            Figure(
                "Value model's miss",
                f"{model.value_error:.2f}",
                "minutes projected"
                if model.value_error_basis == "projected"
                else "minutes as played",
                help="How far its prediction of a team fell from what the season showed, out "
                "of sample (RMSE), with the minutes "
                + (
                    "projected, as a forecast has them."
                    if model.value_error_basis == "projected"
                    else "as the season played them."
                ),
            ),
            Figure(
                "A season's own noise",
                f"{model.season_noise:.2f}",
                f"last {model.spec.noise_seasons} seasons",
                help="How far a season's net rating strays from the team's strength, from the "
                "spread of its game margins.",
            ),
            Figure(
                "Miss on strength",
                f"{model.strength_error:.2f}",
                "what no season could fix",
                help="The value model's miss with a season's noise taken out: how far a "
                "projected rating is from a team's strength.",
            ),
            Figure(
                "Wins per point",
                f"{model.wins_per_point:.2f}",
                f"for {model.wins_season}",
                help="Wins per 82 that a point of net rating has been worth, fitted on the "
                "latest season and its neighbours.",
            ),
            Figure(
                "Residual wins",
                f"{model.wins_residual:.2f}",
                "around the rating",
                help="How far wins per 82 stray from what a season's net rating gives.",
            ),
        ],
        # Three a row: five across cut "what no season could fix" short (UI polish P6).
        per_row=3,
    )
    st.markdown("**The wins test**")
    coverage = pd.DataFrame(
        {
            "Interval": [f"{item.level:.0%}" for item in test.coverage],
            "Held the wins that happened": [item.share for item in test.coverage],
            "Cases": [item.cases for item in test.coverage],
        }
    )
    st.dataframe(
        coverage,
        hide_index=True,
        height=components.table_height(len(coverage)),
        row_height=components.ROW,
        column_config={
            "Held the wins that happened": st.column_config.NumberColumn(format="percent")
        },
    )
    st.caption(
        f"For each of the {test.team_seasons} team-seasons the value model predicted out of "
        f"sample ({test.first_test_season} to {test.last_test_season}), "
        f"{model.spec.test_simulations:,} seasons were drawn from the predicted rating and the "
        "wins that happened were set against them. The median season missed by "
        f"{test.mae:.1f} wins on average and {test.rmse:.1f} root mean square, against "
        f"{test.baseline_rmse:.1f} root mean square "
        "for giving every team an even record. An interval that holds the wins that happened "
        "about as often as it claims is one to lean on; more often is too wide, less often "
        "too narrow."
    )
    st.markdown("**How far projections have missed, by how well the player was known**")
    bands = pd.DataFrame(
        {
            "Projection reliability": [
                f"{b.lower:.2f} to {b.upper:.2f}" for b in model.development
            ],
            "Player-seasons": [b.players for b in model.development],
            "Typical direction": [b.mean_miss for b in model.development],
            "Typical size": [b.spread for b in model.development],
        }
    )
    st.dataframe(
        bands,
        hide_index=True,
        height=components.table_height(len(bands)),
        row_height=components.ROW,
        column_config={
            "Typical direction": st.column_config.NumberColumn(format="%+.2f"),
            "Typical size": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption(
        "Impact less projected impact, weighted by the minutes the player went on to play. "
        "The development presets step every player one typical size up or down; the seasons "
        "drawn spread each player by that size."
    )
    st.markdown("**Games missed by rotation players**")
    quantiles = pd.DataFrame(
        {
            "Quantile": [f"{q.level:.0%}" for q in model.missed.quantiles],
            "Share of the season missed": [q.value for q in model.missed.quantiles],
        }
    )
    st.dataframe(
        quantiles,
        hide_index=True,
        height=components.table_height(len(quantiles)),
        row_height=components.ROW,
        column_config={
            "Share of the season missed": st.column_config.NumberColumn(format="percent")
        },
    )
    st.caption(
        f"{model.missed.players:,} player-seasons of at least {model.spec.rotation_minutes:,} "
        f"minutes, mean {model.missed.mean:.1%}. A season draws each player's missed games "
        "from this distribution, shifted to where the preset or your figure puts them."
    )
    eras = pd.DataFrame(
        {
            "Era": [item.label for item in model.noise_by_era],
            "Seasons": [
                f"{item.first_season} to {item.last_season}" for item in model.noise_by_era
            ],
            "Team-seasons": [item.team_seasons for item in model.noise_by_era],
            "Noise": [item.noise for item in model.noise_by_era],
        }
    )
    if not eras.empty:
        st.markdown("**A season's noise by era**")
        st.dataframe(
            eras,
            hide_index=True,
            height=components.table_height(len(eras)),
            row_height=components.ROW,
            column_config={"Noise": st.column_config.NumberColumn(format="%.2f")},
        )
    with st.expander("What this cannot tell you", icon=":material/report:"):
        st.markdown(
            "- **The field is not in it.** Each roster is drawn alone, as a team of its "
            "strength entering any season; a trade that strengthens one team does not weaken "
            "the other here, and the chances of the thirty teams need not add up.\n"
            "- **A roster is the parts added up.** No fit measure was found to predict beyond "
            "that, so none is used; how the players would play together is not modelled.\n"
            "- **Who misses games is drawn from what rotation players have missed**, not from "
            "anyone's history; **development from how far projections have missed**, not from "
            "any one player's trajectory. Both presets are assumptions, and a figure you set "
            "is yours.\n"
            "- **The value model's own limits carry through**: defense is its weak side, and "
            "projected minutes know nothing of depth charts or contracts.\n"
            "- **A chance is an estimate with an interval**; the wins test is the evidence "
            "for reading it as one."
        )


def _listed(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
