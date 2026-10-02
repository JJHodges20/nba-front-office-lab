"""League Overview: the season at a glance - standings, efficiency, trends, postseason."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.metrics import MetricFormat
from wb import charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, ESTIMATE, MEASURED, Figure
from wb.state import Filters

HEADLINES = {
    "off_rating": "Offensive rating",
    "pace": "Pace",
    "fg3a_rate": "3-point attempt rate",
    "efg_pct": "Effective FG%",
    "pts_per_game": "Points per game",
}
CONFERENCES = {"East": "Eastern Conference", "West": "Western Conference"}
TRENDS = ("off_rating", "pace", "fg3a_rate", "efg_pct")
TREND_SEASONS = 15
STANDINGS_COLUMNS = (
    "conference_rank",
    "team_name",
    "wins",
    "losses",
    "win_pct",
    "games_behind",
    "home_record",
    "road_record",
    "recent_record",
    "streak_label",
    "net_rating",
    "postseason_result",
)


def render() -> None:
    filters = state.current()
    table = data.team_table(filters.build, filters.season, filters.season_type, filters.window)
    kinds = [MEASURED, DERIVED, *([ESTIMATE] if table.estimated else [])]
    components.header("League Overview", filters.scope, kinds=kinds)

    _headlines(filters)
    standings, efficiency, trends, postseason = st.tabs(
        ["Standings", "Team efficiency", "League trends", "Postseason"]
    )
    with standings:
        _standings(filters)
    with efficiency:
        _efficiency(filters, table)
    with trends:
        _trends(filters)
    with postseason:
        _postseason(filters)


def _change(spec, change: float, previous: str) -> str | None:  # type: ignore[no-untyped-def]
    """A season-over-season change in the metric's own unit, in words."""
    if formats.is_missing(change):
        return None
    if spec.format is MetricFormat.PERCENT:
        return f"{change * 100:+.1f} pp vs {previous}"
    return f"{change:+.1f} vs {previous}"


def _headlines(filters: Filters) -> None:
    averages = data.league_averages(filters.build)
    changes = data.league_changes(filters.build)
    catalog = data.lab().league.metrics
    seasons = averages.index.tolist()
    position = seasons.index(filters.season)
    previous = seasons[position - 1] if position else ""
    recent = averages.iloc[max(0, position - TREND_SEASONS + 1) : position + 1]

    st.caption("League averages, regular season")
    items = []
    for key in HEADLINES:
        spec = catalog[key]
        items.append(
            Figure(
                label=HEADLINES[key],
                value=spec.format_value(averages.at[filters.season, key]),
                context=_change(spec, changes.at[filters.season, key], previous),
                help=f"{spec.description} League-wide, regular season.",
                trend=recent[key].tolist(),
            )
        )
    components.figures(items)


def _standings(filters: Filters) -> None:
    standings = data.standings(filters.build, filters.season)
    if not filters.is_regular_season or not filters.window.is_full_season:
        st.caption("Standings always cover the full regular season.")
    catalog = data.lab().league.metrics
    conference = st.segmented_control(
        "Conference",
        list(CONFERENCES),
        format_func=CONFERENCES.get,
        default="East",
        required=True,
        key="standings_conference",
        label_visibility="collapsed",
    )
    rows = standings[standings["conference"] == conference].set_index("team_id")
    chosen = st.dataframe(
        formats.styled(
            rows[list(STANDINGS_COLUMNS)],
            catalog,
            {"games_behind": lambda games: "—" if games == 0 else f"{games:g}"},
        ),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(rows)),
        row_height=components.ROW,
        on_select="rerun",
        selection_mode="single-row",
        key=state.table_key(f"standings_{conference}"),
        column_config={
            "conference_rank": st.column_config.Column("#", width="small"),
            "team_name": st.column_config.Column("Team", width="medium"),
            "wins": "W",
            "losses": "L",
            "win_pct": "W%",
            "games_behind": st.column_config.Column(
                "GB", help="Games behind the conference leader."
            ),
            "home_record": "Home",
            "road_record": "Road",
            "recent_record": st.column_config.Column("L10", help="Last ten games."),
            "streak_label": st.column_config.Column("Strk", help="Current streak."),
            "net_rating": st.column_config.Column("NetRtg", help=catalog["net_rating"].description),
            "postseason_result": "Season ended",
        },
    )
    picked = chosen.selection.rows
    if picked:
        state.choose(team_id=rows.index[picked[0]])
    st.caption("Select a row to make that team the subject of every page.")
    components.export(
        standings[["conference", *STANDINGS_COLUMNS]],
        f"standings_{filters.season}",
        key="standings_csv",
    )


def _efficiency(filters: Filters, table) -> None:  # type: ignore[no-untyped-def]
    teams, catalog, palette = table.teams, table.metrics, components.colors()
    if teams.empty:
        components.empty("No games in this span", "Widen the comparison window or pick a season.")
        return
    estimate = "≈ " if table.estimated else ""
    if table.estimated:
        st.caption(
            "Ratings over a span of games are estimates from box scores, not the league's "
            "published figures."
        )
    highlight = [filters.team_id] if filters.team_id in teams.index else []
    plotted = teams.assign(
        off_text=f"{estimate}ORtg " + formats.shown(catalog, teams, "off_rating"),
        def_text=f"{estimate}DRtg " + formats.shown(catalog, teams, "def_rating"),
        net_text=formats.shown(catalog, teams, "net_rating"),
        record=teams["wins"].astype(int).astype(str)
        + "-"
        + teams["losses"].astype(int).astype(str),
    )

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Offense against defense")
        st.caption(
            "Points scored and allowed per 100 possessions. Up and to the right is better; "
            "the lines mark the league average."
        )
        figure = charts.scatter(
            plotted,
            x="off_rating",
            y="def_rating",
            name="team_name",
            label="team_abbreviation",
            hover=["record", "off_text", "def_text"],
            highlight=highlight,
            palette=palette,
            x_title=f"{estimate}Offensive rating",
            y_title=f"{estimate}Defensive rating (lower is better)",
            x_tickformat=".0f",
            y_tickformat=".0f",
            x_reference=table.league["off_rating"],
            y_reference=table.league["def_rating"],
            reference_label="Lines: league average, regular season",
            reverse_y=True,
            height=520,
        )
        columns = ["team_name", "wins", "losses", "off_rating", "def_rating", "net_rating"]
        components.chart(
            figure,
            teams[columns].sort_values("net_rating", ascending=False),
            key="league_scatter",
            filename=f"offense_defense_{filters.season}",
            catalog=catalog,
        )
    with right:
        st.subheader("Net rating")
        st.caption("Offensive minus defensive rating: point differential with pace removed.")
        ordered = plotted.sort_values("net_rating", ascending=False)
        figure = charts.diverging_bars(
            ordered,
            value="net_rating",
            label="team_abbreviation",
            text="net_text",
            hover=["team_name", "record"],
            highlight=highlight,
            palette=palette,
            value_title=f"{estimate}Net rating",
            tickformat="+.0f",
        )
        components.chart(
            figure,
            ordered[["team_name", "wins", "losses", "net_rating"]],
            key="league_net",
            filename=f"net_rating_{filters.season}",
            catalog=catalog,
        )


def _trends(filters: Filters) -> None:
    averages = data.league_averages(filters.build)
    catalog, palette = data.lab().league.metrics, components.colors()
    st.caption(
        "League-wide averages by season, pooled over every team. The dot on each line is "
        f"{filters.season}."
    )
    frame = averages.reset_index()
    columns = st.columns(2, gap="large")
    for position, key in enumerate(TRENDS):
        spec = catalog[key]
        with columns[position % 2]:
            st.subheader(spec.name)
            plotted = frame.assign(
                text=frame["season"] + ": " + formats.shown(catalog, frame, key),
            )
            figure = charts.line(
                plotted,
                x="season",
                y=key,
                text="text",
                palette=palette,
                tickformat=formats.tickformat(spec),
                marked=[filters.season],
                categorical_x=True,
                height=260,
            )
            components.chart(
                figure,
                frame[["season", key]],
                key=f"trend_{key}",
                filename=f"league_{key}",
                catalog=catalog,
            )


def _postseason(filters: Filters) -> None:
    bracket = data.playoffs(filters.build, filters.season)
    st.subheader(f"{filters.season} playoffs")
    if bracket.empty:
        components.empty(
            "No playoff series yet", f"No playoff games have been played in {filters.season}."
        )
    else:
        shown = pd.DataFrame(
            {
                "Round": bracket["round_name"],
                "Conference": bracket["conference"].fillna("—"),
                "Home court": _seeded(bracket, "team_a"),
                "Opponent": _seeded(bracket, "team_b"),
                "Result": [_series_result(series) for series in bracket.to_dict("records")],
                "Games": bracket["games_played"],
            }
        )
        st.dataframe(
            shown,
            hide_index=True,
            placeholder=EMPTY_CELL,
            height=components.table_height(len(shown)),
            row_height=components.ROW,
        )
        components.export(shown, f"playoffs_{filters.season}", key="bracket_csv")

    st.subheader("Champions")
    champions = data.champions(filters.build)
    if champions.empty:
        components.empty("No champions on record", "No NBA Finals has been decided in the data.")
        return
    st.caption(
        "Where each champion stood in the regular season. Ranks are among that season's teams."
    )
    listed = pd.DataFrame(
        {
            "Season": champions["season"],
            "Champion": champions["champion"],
            "Finals": "def. " + champions["runner_up"] + " " + champions["series"],
            "Record": champions["wins"].astype(str) + "-" + champions["losses"].astype(str),
            "Seed": champions["conference_rank"],
            "Net rating": champions["net_rating"],
            "Net rank": champions["net_rating_rank"],
            "Offense rank": champions["off_rating_rank"],
            "Defense rank": champions["def_rating_rank"],
        }
    )
    st.dataframe(
        listed.style.format({"Net rating": "{:+.1f}"}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={
            "Seed": st.column_config.Column(help="Finish in its conference."),
            "Net rating": st.column_config.Column(help="Regular season, published by the league."),
        },
    )
    components.export(listed, "champions", key="champions_csv")


def _seeded(bracket: pd.DataFrame, side: str) -> pd.Series:
    seeds = bracket[f"{side}_seed"].astype("Int64").astype("str")
    return bracket[side] + " (" + seeds + ")"


def _series_result(series: dict) -> str:
    if not series["is_complete"]:
        return f"In progress, {series['team_a_wins']}-{series['team_b_wins']}"
    wins = max(series["team_a_wins"], series["team_b_wins"])
    losses = min(series["team_a_wins"], series["team_b_wins"])
    return f"{series['winner']} won {wins}-{losses}"
