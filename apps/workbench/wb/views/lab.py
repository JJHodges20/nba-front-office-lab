"""Analytics Lab: set any two metrics against each other, see how one is spread, read definitions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.metrics import MetricCatalog
from front_office.services import DEFAULT_QUALIFICATION, METRIC_CATALOGS
from front_office.services.players import SPAN_QUALIFICATION
from wb import charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, ESTIMATE, MEASURED, Figure
from wb.state import Filters

PLAYERS, TEAMS = "Players", "Teams"
SUBJECT = "lab_subject"
PLAYER_AXES = ("usage_pct", "ts_pct")
TEAM_AXES = ("efg_pct", "off_rating")
BETTER = {True: "Higher", False: "Lower", None: "Neither"}


def render() -> None:
    filters = state.current()
    subjects = [PLAYERS, TEAMS] if filters.has_players else [TEAMS]
    # The study is read before its control is drawn, so that the kinds of number it shows
    # stand under the title, where every other page has them (UI polish P5).
    stored = st.session_state.get(SUBJECT)
    subject = stored if stored in subjects else subjects[0]
    frame, catalog, estimated = _population(filters, subject)
    components.header(
        "Analytics Lab",
        filters.scope,
        kinds=[MEASURED, DERIVED, *([ESTIMATE] if estimated else [])],
    )
    st.segmented_control(
        "Study",
        subjects,
        default=subjects[0],
        required=True,
        key=SUBJECT,
        help="Who the Relationships and Distributions tabs describe.",
    )

    relationships, distribution, glossary = st.tabs(
        ["Relationships", "Distributions", "Metric glossary"]
    )
    with relationships:
        _relationships(filters, subject, frame, catalog, estimated)
    with distribution:
        _distribution(filters, subject, frame, catalog)
    with glossary:
        _glossary()


def _population(
    filters: Filters, subject: str
) -> tuple[pd.DataFrame, MetricCatalog, tuple[str, ...]]:
    """Who is being studied: the season's qualified players, or its teams."""
    if subject == TEAMS:
        table = data.team_table(filters.build, filters.season, filters.season_type, filters.window)
        frame = table.teams.assign(name=table.teams["team_name"])
        return frame, table.metrics, table.estimated
    qualification = DEFAULT_QUALIFICATION if filters.window.is_full_season else SPAN_QUALIFICATION
    table = data.player_table(
        filters.build, filters.season, filters.season_type, filters.window, qualification, None
    )
    players = table.players[table.players["is_qualified"]]
    return players.assign(name=players["player_name"]), table.metrics, ()


def _metric_picker(
    label: str, catalog: MetricCatalog, default: str, key: str, estimated: tuple[str, ...] = ()
) -> str:
    keys = list(catalog.keys)

    def title(option: str) -> str:
        spec = catalog[option]
        return f"{spec.category} · {'≈ ' if option in estimated else ''}{spec.name}"

    return st.selectbox(
        label,
        keys,
        index=keys.index(default) if default in keys else 0,
        format_func=title,
        key=key,
    )


def _selected(filters: Filters, subject: str, frame: pd.DataFrame) -> list[int]:
    chosen = filters.team_id if subject == TEAMS else filters.player_id
    return [chosen] if chosen in frame.index else []


def _relationships(filters, subject, frame, catalog, estimated) -> None:  # type: ignore[no-untyped-def]
    if frame.empty:
        components.empty("Nothing to plot", "No one qualifies in this span. Widen the window.")
        return
    defaults = TEAM_AXES if subject == TEAMS else PLAYER_AXES
    groupings = {"None": None}
    groupings |= (
        {"Conference": "conference"} if subject == TEAMS else {"Position": "position_group"}
    )
    first, second, third = st.columns(3)
    with first:
        x = _metric_picker("Across", catalog, defaults[0], f"lab_x_{subject}", estimated)
    with second:
        y = _metric_picker("Up", catalog, defaults[1], f"lab_y_{subject}", estimated)
    with third:
        grouping = st.selectbox("Colour by", list(groupings), key=f"lab_group_{subject}")

    x_spec, y_spec = catalog[x], catalog[y]
    plotted = frame.assign(
        x_text=x_spec.label + " " + formats.shown(catalog, frame, x),
        y_text=y_spec.label + " " + formats.shown(catalog, frame, y),
    ).dropna(subset=[x, y])
    group = groupings[grouping]
    if group is not None:
        plotted = plotted.dropna(subset=[group])
    figure = charts.scatter(
        plotted,
        x=x,
        y=y,
        name="name",
        hover=["x_text", "y_text"],
        label="team_abbreviation" if subject == TEAMS else None,
        group=group,
        highlight=_selected(filters, subject, plotted),
        palette=components.colors(),
        x_title=x_spec.name,
        y_title=y_spec.name,
        x_tickformat=formats.tickformat(x_spec),
        y_tickformat=formats.tickformat(y_spec),
        height=520,
    )
    association = data.association(plotted, x, y)
    # The three numbers lead, as tiles do on every page, and the chart takes the page's
    # width: in a fifth of it beside the chart, the tiles were cut at 1024px (UI polish P5).
    components.figures(
        [
            Figure(
                subject,
                formats.number(association.sample),
                help="Rows with a value for both metrics.",
            ),
            Figure(
                "Linear correlation",
                _correlation(association.pearson),
                help="Pearson's r, from -1 to +1: how closely the points follow a straight line.",
            ),
            Figure(
                "Rank correlation",
                _correlation(association.spearman),
                help="Spearman's rho, from -1 to +1: whether one rises with the other, "
                "straight line or not.",
            ),
        ]
    )
    columns = ["name", *([group] if group else []), x, y]
    components.chart(
        figure,
        plotted[list(dict.fromkeys(columns))].sort_values(x, ascending=False),
        key="lab_scatter",
        filename=f"{subject.lower()}_{x}_vs_{y}_{filters.season}",
        catalog=catalog,
    )
    st.caption(
        "A correlation describes these rows and nothing more. It does not show that one "
        "thing causes the other, and on a few dozen rows it moves a good deal by chance."
    )


def _correlation(value: float) -> str:
    return formats.MISSING if formats.is_missing(value) else f"{value:+.2f}"


def _distribution(filters, subject, frame, catalog) -> None:  # type: ignore[no-untyped-def]
    if frame.empty:
        components.empty("Nothing to plot", "No one qualifies in this span. Widen the window.")
        return
    default = "net_rating" if subject == TEAMS else "ts_pct"
    picker, _ = st.columns([1, 2])
    with picker:
        key = _metric_picker("Metric", catalog, default, f"lab_spread_{subject}")
    spec = catalog[key]
    chosen = _selected(filters, subject, frame)
    marker, label = None, ""
    if chosen and not formats.is_missing(frame.at[chosen[0], key]):
        marker = float(frame.at[chosen[0], key])
        label = f"{frame.at[chosen[0], 'name']}: {spec.format_value(marker)}"
    figure = charts.histogram(
        frame[key].astype("float64"),
        palette=components.colors(),
        x_title=spec.name,
        tickformat=formats.tickformat(spec),
        marker=marker,
        marker_label=label,
        bins=12 if subject == TEAMS else 30,
        height=360,
    )
    who = "teams" if subject == TEAMS else "qualified players"
    st.caption(
        f"{spec.description} Spread across {frame[key].notna().sum()} {who}"
        + (
            ". The line marks the selected one."
            if marker is not None
            else ". Select a player or team in the sidebar to mark where they stand."
        )
    )
    components.chart(
        figure,
        frame[["name", key]].sort_values(key, ascending=False),
        key="lab_histogram",
        filename=f"{subject.lower()}_{key}_{filters.season}",
        catalog=catalog,
    )


def _glossary() -> None:
    rows = [
        {
            "Group": section,
            "Category": spec.category,
            "Metric": spec.label,
            "Name": spec.name,
            "Origin": spec.provenance.value.capitalize(),
            "Better": BETTER[spec.higher_is_better],
            "Definition": spec.description,
        }
        for section, catalog in METRIC_CATALOGS.items()
        for spec in catalog
    ]
    glossary = pd.DataFrame(rows)
    search, _ = st.columns([1, 2])
    wanted = search.text_input(
        "Search", placeholder="true shooting, rebound, rating ...", key="lab_glossary_search"
    )
    if wanted.strip():
        words = wanted.lower().split()
        text = (
            glossary["Metric"] + " " + glossary["Name"] + " " + glossary["Definition"]
        ).str.lower()
        glossary = glossary[text.map(lambda entry: all(word in entry for word in words))]
    st.caption(
        f"{len(glossary)} metrics. Measured: published by the league and shown unchanged. "
        "Derived: computed by the lab with the formula given. Modeled: an estimate from a "
        "fitted model, with its evidence on the Player Value, Roster Fit and Postseason "
        "Outlook pages."
    )
    st.dataframe(
        glossary,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(glossary), 16)),
        row_height=components.ROW,
        column_config={"Definition": st.column_config.Column(width="large")},
    )
    components.export(glossary, "metric_glossary", key="glossary_csv")
