"""Roster Fit: do these players make sense together?

A roster - a real team's, or one built in the Team Builder - described in the roadmap's
areas of fit and set beside the season's real teams. Whether any of that matters beyond
the sum of the players' impacts is a tested question; the last tab shows the answer, and
nothing is applied to a roster that the evidence does not support. Roles are rules,
impacts are a model's estimates: everything here is modeled or derived.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from front_office.domain.fit_model import FitEvidence
from front_office.services import FitReport, FitStatus
from wb import ask, charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, MODELED, Figure
from wb.state import Filters

TABS = ("Coverage", "Profile", "Sum of parts", "The evidence")
TAB = "fit_tab"
SUBJECTS = ("Team", "Built roster")
SUBJECT = "fit_subject"
ROSTER = "fit_roster"
TEST = "fol fit test --write"
IDENTITY = {
    "player_name": st.column_config.Column("Player", width="medium", pinned=True),
    "team": "Team",
    "position": "Pos",
    "age": "Age",
}
DIRECTIONS = {True: "higher is better", False: "lower is better", None: "no better or worse"}


def render() -> None:
    filters = state.current()
    status = data.fit_status(filters.build)
    components.header(
        "Roster Fit",
        "Do these players make sense together? A roster described in the roadmap's areas "
        "of fit, set beside the season's real teams - and the evidence on whether fit adds "
        "anything to the sum of the parts.",
        kinds=[MODELED, DERIVED],
    )
    ask.button(ask.from_filters("Roster Fit", filters))
    if not status.seasons:
        components.empty(
            "No team profiles yet",
            "Profiles are built from player statistics, the value model and the role rules "
            "when the database is built. Run: fol build",
            icon=":material/diversity_3:",
        )
        return
    _notices(status)
    subject = _subject(filters, status)
    catalog = data.lab().fit.metrics
    evidence = data.fit_evidence(filters.build, status.revision)

    # A tab that needs a subject says what is missing in itself, rather than standing empty
    # under one note above the tabs (UI polish P6, audit finding F14).
    coverage, profile, parts, tested = st.tabs(list(TABS), key=TAB, on_change="rerun")
    with coverage:
        if isinstance(subject, Absent):
            subject.draw()
        else:
            _coverage(subject, catalog)
    with profile:
        if isinstance(subject, Absent):
            subject.draw()
        else:
            _profile(subject, catalog)
    with parts:
        if isinstance(subject, Absent):
            subject.draw()
        else:
            _parts(subject, status, evidence)
    with tested:
        _evidence(filters, status, evidence)


@dataclass(frozen=True, slots=True)
class Absent:
    """Why there is nothing to profile, said in each tab that needs something."""

    title: str
    body: str
    icon: str = ":material/inbox:"

    def draw(self) -> None:
        components.empty(self.title, self.body, icon=self.icon)


def _notices(status: FitStatus) -> None:
    if not status.is_gathered:
        components.tagged(
            components.NOTE,
            "No fit evidence has been gathered yet, so the profile is description only. "
            f"To test whether fit adds anything to the sum of the parts: {TEST}",
        )
    elif not status.is_current:
        components.tagged(
            components.OUT_OF_DATE,
            f"The evidence on file was gathered against value model {status.value_model_version} "
            f"and roles {status.archetype_version}; the database was built with "
            f"{status.applied_value_version} and {status.applied_archetype_version}. Run: {TEST}",
        )


# --- the subject ---------------------------------------------------------------------------


def _subject(filters: Filters, status: FitStatus) -> FitReport | Absent:
    """What is profiled: the sidebar's team, or a roster the user built - or why nothing is."""
    rosters = data.rosters()
    options = list(SUBJECTS) if not rosters.empty else [SUBJECTS[0]]
    subject = st.segmented_control(
        "Subject", options, default=SUBJECTS[0], required=True, key=SUBJECT
    )
    if subject == SUBJECTS[0]:
        if filters.team_id is None:
            return Absent(
                "Choose a team",
                "Pick a team in the sidebar to see how its players fit together"
                + (", or switch to a roster you built." if not rosters.empty else "."),
                icon=":material/groups:",
            )
        if filters.season not in status.seasons:
            return Absent(
                f"No profiles for {filters.season}",
                f"Teams are profiled for seasons with player statistics: {status.seasons[-1]} "
                f"to {status.seasons[0]}. Pick one in the sidebar.",
                icon=":material/groups:",
            )
        report = data.fit_team(filters.build, filters.team_id, filters.season)
        if report.is_empty:
            return Absent(
                "No players on record",
                f"{report.name} has no player minutes on record in {filters.season}.",
            )
        st.caption(
            f"**{report.name}, {report.season}**: {len(report.members)} players, each weighted "
            "by the minutes played for the team. Roles are counted in the rotation, the ten "
            "players with the most minutes."
        )
        return report

    ids = rosters["roster_id"].tolist()
    names = rosters.set_index("roster_id")["name"]
    roster_id = st.selectbox(
        "Roster", ids, format_func=lambda value: names[value], key=ROSTER, width=360
    )
    report = data.fit_roster(int(roster_id))
    if report.is_empty:
        return Absent(
            "Nothing to profile",
            f"No player on {report.name} has minutes in {report.season}, its statistics "
            "season. Add players in the Team Builder, or give the roster another season.",
        )
    said = (
        f"**{report.name}**: {len(report.members)} players, each weighted by the minutes "
        f"played in {report.season}, the roster's statistics season, and placed among that "
        "season's teams. These are the players on the teams they actually played for; "
        "nothing here says how they would play together."
    )
    if report.absent:
        said += (
            f" Not in the profile, having no minutes in {report.season}: {_listed(report.absent)}."
        )
    st.caption(said)
    return report


# --- coverage --------------------------------------------------------------------------------


def _coverage(report: FitReport, catalog) -> None:  # type: ignore[no-untyped-def]
    st.caption(
        "Who fills each role, by the rules on the Player Value page: a rule, not a "
        "measurement. Counted among the rotation; the bench is the sixth to tenth player "
        "by minutes. The best in the rotation is named whether or not anyone reaches the "
        "role's cut-off."
    )
    coverage = report.coverage.assign(
        best=report.coverage.apply(
            lambda row: (
                EMPTY_CELL
                if formats.is_missing(row["best_score"])
                else f"{row['best_player']} ({row['best_score']:.0f})"
            ),
            axis=1,
        )
    )
    st.dataframe(
        coverage[["name", "count", "filled_by", "best", "bench_count"]],
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(coverage)),
        row_height=components.ROW,
        column_config={
            "name": st.column_config.Column("Role", width="medium"),
            "count": st.column_config.Column("In the rotation", help="Players who fill the role."),
            "filled_by": st.column_config.Column("Filled by", width="large"),
            "best": st.column_config.Column(
                "Best in the rotation", help="The highest score for the role, cut-off or not."
            ),
            "bench_count": st.column_config.Column("On the bench"),
        },
    )
    missing = coverage[coverage["count"] == 0]
    if not missing.empty:
        st.caption(
            f"Nobody in the rotation fills: {_listed(missing['name'].tolist())}. A missing "
            "role is a fact about these rules and these minutes, not a verdict."
        )
    if report.unprofiled:
        st.caption(
            f"No statistics to build a profile from: {_listed(report.unprofiled)}. Their "
            "minutes count; they fill no role and enter no average."
        )

    st.markdown("**The players, by minutes**")
    members = report.members
    listed = members[
        [*IDENTITY, "minutes", "share", "in_rotation", "role", "roles", "impact", "wins_added"]
    ]
    picked = st.dataframe(
        formats.styled(
            listed,
            data.lab().value.metrics,
            {"minutes": formats.number, "share": formats.share},
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key(f"fit_members_{report.kind}_{report.key}"),
        height=components.table_height(min(len(listed), 15)),
        row_height=components.ROW,
        column_config={
            **IDENTITY,
            "minutes": st.column_config.Column("MIN", help="Minutes that count for this roster."),
            "share": st.column_config.Column("Share", help="Share of the roster's minutes."),
            "in_rotation": st.column_config.CheckboxColumn("Rotation"),
            "role": st.column_config.Column("Main role"),
            "roles": st.column_config.Column("Roles filled", width="medium"),
            **components.metric_columns(data.lab().value.metrics, ["impact", "wins_added"]),
        },
    ).selection.rows
    if picked:
        state.choose(player_id=listed.index[picked[0]])
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            members.reset_index(), f"fit_members_{report.kind}_{report.key}", key="fit_members_csv"
        )
        st.caption("Select a row to make that player the subject of the other pages.")


# --- the profile ------------------------------------------------------------------------------


def _profile(report: FitReport, catalog) -> None:  # type: ignore[no-untyped-def]
    placed = report.placed.copy()
    placed["shown"] = [
        formats.MISSING if formats.is_missing(value) else catalog[key].format_value(value)
        for key, value in zip(placed["key"], placed["value"], strict=True)
    ]
    placed["median_shown"] = [
        formats.MISSING if formats.is_missing(value) else catalog[key].format_value(value)
        for key, value in zip(placed["key"], placed["median"], strict=True)
    ]
    placed["standing"] = [
        formats.MISSING if formats.is_missing(rank) else formats.rank_of(int(rank), int(teams))
        for rank, teams in zip(placed["rank"], placed["teams"], strict=True)
    ]
    placed["direction"] = placed["higher_is_better"].map(DIRECTIONS)
    teams = int(placed["teams"].max()) if len(placed) else 0
    st.caption(
        f"Each measure beside the {teams} teams of {report.season}: the percentile is the "
        "share of those teams the roster stands above, so 50 is the middle of the league. "
        "A rank is from the highest value down, whatever the measure's direction; many "
        "measures have none. Every number is an average over the players for the minutes "
        "they played, not a prediction of how they would play together."
    )
    drawn = placed[placed["percentile"].notna()]
    if not drawn.empty:
        figure = charts.percentile_bars(
            drawn,
            percentile="percentile",
            label="name",
            text="shown",
            palette=components.colors(),
            hover=["area", "standing", "direction"],
            group="area",
            axis_title=f"Percentile among the teams of {report.season}",
        )
        components.chart(
            figure,
            drawn[["area", "name", "value", "median", "percentile", "rank", "teams"]],
            key="fit_profile",
            filename=f"fit_profile_{report.kind}_{report.key}",
            formats={
                "percentile": formats.percentile,
                "value": formats.number,
                "median": formats.number,
            },
        )
    for area, rows in placed.groupby("area", sort=False):
        st.markdown(f"**{area}**")
        st.dataframe(
            rows[["name", "shown", "median_shown", "standing", "percentile", "direction"]],
            hide_index=True,
            placeholder=EMPTY_CELL,
            height=components.table_height(len(rows)),
            row_height=components.ROW,
            column_config={
                "name": st.column_config.Column("Measure", width="medium"),
                "shown": st.column_config.Column("This roster"),
                "median_shown": st.column_config.Column("League median"),
                "standing": st.column_config.Column("Rank", help="From the highest value down."),
                "percentile": st.column_config.NumberColumn("Percentile", format="%.0f"),
                "direction": st.column_config.Column("Direction"),
            },
        )


# --- the sum of parts ---------------------------------------------------------------------------


def _parts(report: FitReport, status: FitStatus, evidence: FitEvidence | None) -> None:
    parts = report.parts
    placed = report.placed.set_index("key")
    error = formats.MISSING if parts.error is None else f"±{parts.error:.1f} (RMSE)"
    standing = (
        formats.MISSING
        if formats.is_missing(placed.at["impact_sum", "rank"])
        else formats.rank_of(
            int(placed.at["impact_sum", "rank"]), int(placed.at["impact_sum", "teams"])
        )
    )
    correction = "None" if parts.correction is None else f"{parts.correction:+.1f}"
    components.figures(
        [
            Figure(
                "Impact, sum of parts",
                f"{parts.impact:+.1f}",
                f"{standing} in {report.season}",
                help="The players' impacts added up for the minutes given: the net rating, "
                "relative to the league, a team would have if its players simply added up.",
            ),
            Figure(
                "Projected, sum of parts",
                formats.MISSING
                if formats.is_missing(parts.projected)
                else f"{parts.projected:+.1f}",
                "going into the season",
                help="The same with each player's projection going into the season instead of "
                "what the season showed.",
            ),
            Figure(
                "The model's miss",
                error,
                "on seasons it had not seen",
                help="What the value model's prediction of a real team missed by, out of "
                "sample. A sum of parts is an estimate with at least this much error.",
            ),
            Figure(
                "Minutes covered",
                formats.share(parts.minutes_covered, 0),
                f"{formats.share(parts.unprofiled_share, 0)} without a profile",
                help="The players' minutes as a share of the minutes a team has to fill in a "
                "season. A built roster rarely covers exactly one season.",
            ),
            Figure(
                "Fit correction",
                correction,
                "the evidence supports none"
                if parts.correction is None
                else f"from evidence {status.revision}",
                help="What the fit evidence adds to the sum of the parts. Applied only when "
                "the measures, together, leave the sum missing by clearly less.",
            ),
        ],
        per_row=3,
    )
    if evidence is None:
        st.caption(f"No fit evidence has been gathered. Run: {TEST}")
        return
    combined = evidence.combined
    st.caption(
        f"The evidence on file (revision {evidence.revision}, {evidence.team_seasons} "
        f"team-seasons from {evidence.first_test_season} to {evidence.last_test_season}): "
        + (
            "together the fit measures leave the value model's predictions missing by "
            f"{-combined.change.difference:.2f} less, clear of zero, so the correction above "
            "is applied."
            if combined.is_usable
            else "taken together, the fit measures leave the value model's predictions missing "
            f"by {combined.change.difference:+.2f} ({combined.change.low:+.2f} to "
            f"{combined.change.high:+.2f}) - no better, so nothing is added to the sum of the "
            "parts. The profile describes; it does not score."
        )
    )


# --- the evidence -------------------------------------------------------------------------------


def _evidence(filters: Filters, status: FitStatus, evidence: FitEvidence | None) -> None:
    if evidence is None:
        components.empty(
            "No fit evidence has been gathered",
            "The test asks whether the fit measures, taken from the players' previous-season "
            "profiles, explain what the value model's out-of-sample predictions missed. "
            f"Run: {TEST}",
            icon=":material/science:",
        )
    else:
        confidence = f"{evidence.spec.confidence:.0%}"
        st.caption(
            f"Does fit say anything the sum of the parts does not? On {evidence.team_seasons} "
            f"team-seasons, {evidence.first_test_season} to {evidence.last_test_season}, the "
            f"value model's predictions missed by {evidence.baseline_rmse:.2f} points of net "
            "rating. Each measure below, built from the players' previous-season profiles so "
            "that nothing of the season predicted leaks in, was asked to explain those misses "
            "on seasons it had not seen; then all of them together. Intervals are "
            f"{confidence}, from resampling whole seasons."
        )
        alone = pd.DataFrame(
            {
                "name": [item.name for item in evidence.measures],
                "area": [item.area for item in evidence.measures],
                "coefficient": [
                    f"{item.coefficient:+.2f} ({item.coefficient_low:+.2f} to {item.coefficient_high:+.2f})"
                    for item in evidence.measures
                ],
                "rmse": [item.rmse for item in evidence.measures],
                "change": [_change(item.change) for item in evidence.measures],
                "verdict": [
                    "clear of zero" if item.is_distinguishable else "cannot be told from nothing"
                    for item in evidence.measures
                ],
            }
        )
        st.markdown("**Each measure alone, correcting the sum of the parts**")
        st.dataframe(
            alone,
            hide_index=True,
            placeholder=EMPTY_CELL,
            height=components.table_height(len(alone)),
            row_height=components.ROW,
            column_config={
                "name": st.column_config.Column("Measure", width="medium"),
                "area": "Area",
                "coefficient": st.column_config.Column(
                    "Per standard deviation",
                    help="Points of net rating per standard deviation of the measure, fitted "
                    "on every season, with its interval.",
                ),
                "rmse": st.column_config.NumberColumn("RMSE", format="%.2f"),
                "change": st.column_config.Column(
                    "RMSE less the sum of the parts'",
                    help="Negative means the correction helps. The interval has to stay "
                    "below zero for that to be clear.",
                ),
                "verdict": "Verdict",
            },
        )
        combined = evidence.combined
        together = pd.DataFrame(
            {
                "Correction": ["Sum of the parts alone", "With every measure"],
                "RMSE": [evidence.baseline_rmse, combined.rmse],
                "Change": ["", _change(combined.change)],
            }
        )
        st.markdown("**Every measure together**")
        st.dataframe(
            together,
            hide_index=True,
            height=components.table_height(2),
            row_height=components.ROW,
            column_config={"RMSE": st.column_config.NumberColumn(format="%.2f")},
        )
        st.caption(
            "**The correction is applied to rosters**: together the measures leave the sum "
            "of the parts missing by clearly less."
            if combined.is_usable
            else "**No correction is applied to rosters**: together the measures do not leave "
            "the sum of the parts missing by clearly less."
        )
        without = pd.DataFrame(
            {
                "Left out": [item.label for item in combined.ablations],
                "RMSE": [item.rmse for item in combined.ablations],
                "Change": [_change(item.change) for item in combined.ablations],
                "Verdict": [
                    "missed"
                    if item.change.low > 0
                    else "better without"
                    if item.change.high < 0
                    else "cannot be told"
                    for item in combined.ablations
                ],
            }
        )
        st.markdown("**The combined correction with one area left out**")
        st.dataframe(
            without,
            hide_index=True,
            height=components.table_height(len(without)),
            row_height=components.ROW,
            column_config={
                "RMSE": st.column_config.NumberColumn(format="%.2f"),
                "Change": st.column_config.Column("RMSE less the full correction's"),
            },
        )

    champions = data.fit_champions(filters.build)
    if champions.empty or champions["champions"].max() == 0:
        return
    st.markdown("**Where the champions' rosters stood**")
    st.caption(
        f"Each of the {int(champions['champions'].max())} champions on record, placed among "
        "the teams of its own season on each measure, by what its players showed that season. "
        "A median near 50 says champions looked like anyone on that measure. History, not a "
        "recipe: the test above is what says whether a measure matters beyond the parts."
    )
    st.dataframe(
        champions[["area", "name", "median_percentile", "top_third", "bottom_third"]],
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(champions)),
        row_height=components.ROW,
        column_config={
            "area": "Area",
            "name": st.column_config.Column("Measure", width="medium"),
            "median_percentile": st.column_config.NumberColumn("Median percentile", format="%.0f"),
            "top_third": st.column_config.Column(
                "In the top third",
                help="Champions at or above the 67th percentile of their season.",
            ),
            "bottom_third": st.column_config.Column(
                "In the bottom third",
                help="Champions at or below the 33rd percentile of their season.",
            ),
        },
    )


def _change(span) -> str:  # type: ignore[no-untyped-def]
    return f"{span.difference:+.2f} ({span.low:+.2f} to {span.high:+.2f})"


def _listed(names) -> str:  # type: ignore[no-untyped-def]
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
