"""Winning Benchmarks: what past teams at each stage of the postseason looked like.

History, not a forecast. Every share on this page is how often something happened to
past teams, shown with the number of teams behind it and the interval it could
plausibly lie in. The page chooses its own seasons - an era - so the sidebar's filters
do not narrow it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.metrics import MetricCatalog
from front_office.services import MEASURES, EraView, floor
from wb import ask, charts, components, data, formats, state
from wb.components import DERIVED, EMPTY_CELL, MEASURED, Figure

ERA, FROM, TO, STAGE = "bench_era", "bench_from", "bench_to", "bench_stage"
CUSTOM = data.CUSTOM_ERA
DEFAULT_STAGE = "made_conference_finals"
EVERY_TEAM = "every_team"
EVERY_OTHER = "every_other_team"
FIELD_AXES = ("rel_off_rating", "rel_def_rating")
# The last season in which the league's standings leave equal records on one place.
LAST_TIED_STANDINGS = "2000-01"
RANK_TICK = 5
QUANTILES = {
    "lowest": "Lowest",
    "p10": "10%",
    "median": "Median",
    "p90": "90%",
    "highest": "Highest",
}


def render() -> None:
    build = state.current().build
    components.header(
        "Winning Benchmarks",
        "What the teams that reached each stage of the postseason looked like, across seasons.",
        kinds=[MEASURED, DERIVED],
    )
    ask.button(ask.from_filters("Winning Benchmarks", state.current()))
    seasons = data.benchmark_seasons(build)
    if not seasons:
        components.empty(
            "No completed season yet",
            "Benchmarks describe seasons whose postseason is over, and none is on record.",
            icon=":material/emoji_events:",
        )
        return

    service = data.lab().benchmarks
    stages = {stage.key: stage for stage in service.stages}
    era, first, last, stage_key = _controls(build, seasons, stages)
    era_args = (build, era, first, last)
    view = data.benchmark_view(*era_args)
    stage = stages[stage_key]
    note = f" {view.era.note}" if view.era.note else ""
    name = "Seasons chosen" if era == CUSTOM else view.era.name
    st.caption(
        f"**{name}**: {view.span}, {len(view.seasons)} "
        f"season{'s' if len(view.seasons) != 1 else ''}, {view.teams} team-seasons.{note} "
        "History, not a forecast: a share here is how often it happened to past teams. "
        "This page chooses its own seasons, so the sidebar's filters do not narrow it."
    )
    if view.reached[stage_key] == 0:
        components.empty(
            "Nobody in these seasons",
            f"No team in this span {_lower(stage.label)}. Choose a wider era.",
            icon=":material/emoji_events:",
        )
        return

    catalog = service.metrics
    _headlines(era_args, view, stage, catalog)
    rates, profile, separation, field, teams = st.tabs(
        [
            "How far teams went",
            "What they looked like",
            "What separates them",
            "The field",
            "Team-seasons",
        ]
    )
    with rates:
        _rates(era_args, view, stage, stages, catalog)
    with profile:
        _profile(era_args, stage, catalog)
    with separation:
        _separation(era_args, stage, stages)
    with field:
        _field(era_args, view, stage, catalog)
    with teams:
        _teams(era_args, view, catalog)


def _lower(label: str) -> str:
    """A stage label as the rest of a sentence: "teams that <reached the NBA Finals>"."""
    return label[0].lower() + label[1:]


def _controls(build, seasons, stages) -> tuple[str, str | None, str | None, str]:  # type: ignore[no-untyped-def]
    """The page's own filters: which seasons, and which teams are the subject."""
    eras = data.benchmark_eras(build)
    names = {era.key: era.name for era in eras} | {CUSTOM: "Other seasons"}
    labels = {key: stage.label for key, stage in stages.items()}
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        # A list, not a row of buttons: five long names do not fit a narrow window (UI polish P3).
        era = st.selectbox(
            "Seasons",
            list(names),
            format_func=names.get,
            index=0,
            key=ERA,
            width=260,
            help="Which seasons the page describes. The eras are set in configs/eras.yaml.",
        )
        stage = st.selectbox(
            "Teams that",
            list(labels),
            format_func=labels.get,
            index=list(labels).index(DEFAULT_STAGE),
            key=STAGE,
            width=320,
            help="The teams the page is about. Each stage includes every later one.",
        )
    first = last = None
    if era == CUSTOM:
        start, end, _ = st.columns([1, 1, 3])
        first = start.selectbox("From", list(seasons), index=0, key=FROM)
        later = [season for season in seasons if season >= first]
        last = end.selectbox("To", later, index=len(later) - 1, key=TO)
    return era, first, last, stage


def _headlines(era_args, view: EraView, stage, catalog: MetricCatalog) -> None:  # type: ignore[no-untyped-def]
    summary = data.benchmark_summary(*era_args, stage.key)
    components.figures(
        [
            Figure(stage.short, formats.number(summary.teams), f"of {view.teams} team-seasons"),
            Figure(
                "Fewest wins per 82",
                catalog["wins_per_82"].format_value(summary.fewest_wins),
                summary.fewest_wins_by,
                help="The weakest record of any team that got this far, on the scale of an "
                "82-game season. One team, not a threshold.",
            ),
            Figure(
                "Median wins per 82",
                catalog["wins_per_82"].format_value(summary.median_wins),
                "Half won more",
                help="Half of the teams that got this far won more than this, half fewer.",
            ),
            Figure(
                "Median net rating",
                catalog["net_rating"].format_value(summary.median_net_rating),
                f"Median league rank {summary.median_net_rank:g}",
                help=catalog["net_rating"].description,
            ),
            Figure(
                "Top 10 at both ends",
                f"{summary.top_ten_both_ends} of {summary.teams}",
                f"Top 5 net rating: {summary.top_five_net}",
                help="How many ranked in the league's top ten in offensive rating and in "
                "defensive rating that season. Below it: how many were top five in net rating.",
            ),
        ]
    )


# --- how often ----------------------------------------------------------------------------


def _rates(era_args, view: EraView, stage, stages, catalog: MetricCatalog) -> None:  # type: ignore[no-untyped-def]
    names = {measure.key: catalog[measure.key].name for measure in MEASURES}
    keys = list(stages)
    fields = {EVERY_TEAM: "Every team"} | {
        key: f"Teams that {_lower(stages[key].label)}" for key in keys[: keys.index(stage.key)]
    }
    with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
        measure = st.selectbox(
            "By", list(names), format_func=names.get, key="bench_measure", width=300
        )
        chosen = st.selectbox(
            "Among",
            list(fields),
            format_func=fields.get,
            key=f"bench_among_{stage.key}",
            width=320,
            help="Whose share it is: of every team in a band, or only of those that had "
            "already got as far as an earlier stage.",
        )
        settings = next(candidate for candidate in MEASURES if candidate.key == measure)
        width = None
        if settings.widths:
            width = st.segmented_control(
                "Width of a band",
                list(settings.widths),
                format_func=lambda option: f"{option:g}",
                default=settings.width,
                required=True,
                key=f"bench_width_{measure}",
                help="How teams are grouped. A band is a way of grouping, not a threshold.",
            )
    among = None if chosen == EVERY_TEAM else chosen
    who = "teams" if among is None else _lower(fields[chosen])
    rates = data.benchmark_rates(*era_args, measure, width, among)
    mine = rates[rates["stage"] == stage.key]
    shares = mine["rate"].map(formats.share)
    counted = mine["reached"].astype(str) + " of " + mine["teams"].astype(str) + " teams"
    plotted = mine.assign(
        label=mine["band"] + "<br>n = " + mine["teams"].astype(str),
        text="<b>"
        + catalog[measure].name
        + " "
        + mine["band"]
        + "</b><br>"
        + counted
        + " ("
        + shares
        + ")<br>95% interval "
        + mine["low"].map(formats.share)
        + " to "
        + mine["high"].map(formats.share),
    )
    st.markdown(f"**How often {who} {_lower(stage.label)}, by {catalog[measure].name.lower()}**")
    figure = charts.interval_columns(
        plotted,
        label="label",
        value="rate",
        low="low",
        high="high",
        text="text",
        palette=components.colors(),
        value_title=f"Share that {_lower(stage.label)}",
    )
    table = _all_stages(rates, catalog[measure].name)
    shares_of = {column: formats.share for column in table.columns[2:]}
    components.chart(
        figure,
        table,
        key="bench_rates",
        filename=f"stage_rates_by_{measure}_{view.era.key}",
        formats=shares_of,
    )
    found = floor(rates, stage.key)
    if found is not None and found.teams_below:
        st.markdown(
            f"Of the {who} below the **{found.band}** band, none {_lower(stage.label)}: 0 of "
            f"{found.teams_below:,}. By the interval, that is still consistent with a "
            f"long-run rate of up to {formats.share(found.ceiling)} - rare on this evidence, "
            "not impossible."
        )
    caption = (
        "The thin line through each column is the 95% interval for the share: with few "
        "teams behind a column it is long, and the share should be read loosely."
    )
    if settings.width is not None:
        caption = "A band holds its lower edge and stops short of its upper one. " + caption
    if measure == "conference_rank" and view.seasons[0] <= LAST_TIED_STANDINGS:
        caption += (
            " Through 2000-01 the league's standings leave equal records on the same "
            "place, so there a place is not always the seed a team played from."
        )
    st.caption(caption)


def _all_stages(rates: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Every stage's share side by side, one row per band: the table under the chart."""
    stages = {stage.key: stage.short for stage in data.lab().benchmarks.stages}
    wide = rates.pivot(index="band", columns="stage", values="rate")
    wide = wide.reindex(index=rates["band"].drop_duplicates(), columns=list(stages))
    teams = rates.drop_duplicates("band").set_index("band")["teams"]
    wide.insert(0, "Teams", teams)
    return wide.rename(columns=stages).rename_axis(measure).reset_index()


# --- what they looked like ----------------------------------------------------------------


def _profile(era_args, stage, catalog: MetricCatalog) -> None:  # type: ignore[no-untyped-def]
    profiles = data.benchmark_profiles(*era_args)
    mine = profiles[profiles["group"] == stage.key]
    ranks = mine[mine["kind"] == "rank"]
    values = mine[mine["kind"] == "value"]
    field = profiles[(profiles["group"] == EVERY_TEAM) & (profiles["kind"] == "rank")]

    st.markdown(f"**Where teams that {_lower(stage.label)} ranked in the league**")
    names = ranks["metric"].map(lambda key: catalog[key].name)
    plotted = ranks.assign(
        name=names,
        text="<b>"
        + names
        + "</b><br>Median rank "
        + ranks["median"].map("{:g}".format)
        + "<br>Half of them between "
        + ranks["p25"].map("{:.0f}".format)
        + " and "
        + ranks["p75"].map("{:.0f}".format)
        + ", most between "
        + ranks["p10"].map("{:.0f}".format)
        + " and "
        + ranks["p90"].map("{:.0f}".format)
        + "<br>Best "
        + ranks["lowest"].map("{:.0f}".format)
        + " ("
        + ranks["lowest_team"]
        + "), worst "
        + ranks["highest"].map("{:.0f}".format)
        + " ("
        + ranks["highest_team"]
        + ")",
    )
    last_place = int(field["highest"].max())
    figure = charts.interval_rows(
        plotted,
        label="name",
        value="median",
        low="p10",
        high="p90",
        inner_low="p25",
        inner_high="p75",
        text="text",
        palette=components.colors(),
        value_title="League rank that season (1 is best)",
        axis_range=(last_place + 0.5, 0.5),
        tickvals=[1, *range(RANK_TICK, last_place + 1, RANK_TICK)],
    )
    shown = plotted[["name", "teams", "lowest", "p10", "p25", "median", "p75", "p90", "highest"]]
    components.chart(
        figure,
        shown.rename(columns={"name": "metric"}),
        key="bench_ranks",
        filename=f"league_ranks_{stage.key}",
    )
    st.caption(
        "Dot: the median team. Thick bar: the middle half. Thin line: the middle 80%. A "
        "rank is within a team's own season, so it compares across eras. Rank 1 is the "
        "best figure in the league; pace and three-point rate have no better direction, "
        "so there rank 1 is the highest."
    )

    st.markdown("**In their own units**")
    table = pd.DataFrame(
        {
            "Measure": values["metric"].map(lambda key: catalog[key].name),
            **{
                title: [
                    catalog[key].format_value(value)
                    for key, value in zip(values["metric"], values[column], strict=True)
                ]
                for column, title in QUANTILES.items()
            },
            "Lowest was": values["lowest_team"],
            "Highest was": values["highest_team"],
        }
    )
    st.dataframe(table, hide_index=True, placeholder=EMPTY_CELL, row_height=components.ROW)
    st.caption(
        "Measures that mean the same in every era. The lowest and the highest are real "
        "teams, named at the right; 10% and 90% bound the middle of the group."
    )

    st.markdown("**How many ranked near the top of the league**")
    counts = data.benchmark_rank_counts(*era_args)
    counts = counts[counts["group"] == stage.key]
    cells = counts.assign(
        cutoff="Top " + counts["cutoff"].astype(str),
        cell=counts["inside"].astype(str) + " of " + counts["teams"].astype(str),
    )
    wide = cells.pivot(index="basis", columns="cutoff", values="cell")
    wide = wide.reindex(
        index=cells["basis"].drop_duplicates(), columns=cells["cutoff"].drop_duplicates()
    )
    st.dataframe(
        wide.rename_axis("League rank in").reset_index(),
        hide_index=True,
        placeholder=EMPTY_CELL,
        row_height=components.ROW,
        width="content",
    )
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(
            mine.drop(columns=["group"]), f"profile_{stage.key}", key="bench_profile_csv"
        )
        st.caption("Both ends: inside the cutoff on offensive and on defensive rating at once.")


# --- what separates them ------------------------------------------------------------------


def _separation(era_args, stage, stages) -> None:  # type: ignore[no-untyped-def]
    keys = list(stages)
    earlier = keys[: keys.index(stage.key)]
    fields = {EVERY_OTHER: "Every other team that season"} | {
        key: f"The other teams that {_lower(stages[key].label)}" for key in earlier
    }
    chosen = st.selectbox(
        "Compared with",
        list(fields),
        format_func=fields.get,
        key=f"bench_field_{stage.key}",
        width=420,
        help="Who the teams that got this far are set against. Against the whole league "
        "almost any strength separates them; against the teams they had to beat, less does.",
    )
    among = None if chosen == EVERY_OTHER else chosen
    table = data.benchmark_separation(*era_args, stage.key, among)
    if table["pairs"].max() == 0:
        components.empty(
            "Nothing to compare",
            "In these seasons no team that got this far has another team of its season "
            "to be set against in that field.",
        )
        return
    first = table.iloc[0]
    st.markdown(
        f"**{first['reached']} teams that {_lower(stage.label)}** against "
        f"**{first['others']} that did not**, in {first['seasons']} seasons: "
        f"{first['pairs']:,} same-season pairs."
    )
    plotted = table.assign(
        text="<b>"
        + table["name"]
        + "</b><br>The team that got there had the better value in "
        + table["concordance"].map(formats.share)
        + " of pairs<br>95% interval "
        + table["low"].map(formats.share)
        + " to "
        + table["high"].map(formats.share)
        + "<br>Median league rank "
        + table["reached_median_rank"].map("{:g}".format)
        + " against "
        + table["others_median_rank"].map("{:g}".format),
    )
    figure = charts.interval_rows(
        plotted,
        label="name",
        value="concordance",
        low="low",
        high="high",
        text="text",
        palette=components.colors(),
        value_title="How often it had the better value",
        tickformat=".0%",
        reference=0.5,
        reference_label="Coin flip",
    )
    shown = table[
        ["name", "category", "concordance", "low", "high", "pairs", "reached_median_rank",
         "others_median_rank"]
    ].rename(
        columns={
            "name": "metric",
            "low": "interval from",
            "high": "interval to",
            "reached_median_rank": "median rank: got there",
            "others_median_rank": "median rank: did not",
        }
    )  # fmt: skip
    components.chart(
        figure,
        shown,
        key="bench_separation",
        filename=f"separation_{stage.key}_{chosen}",
        formats={
            column: formats.share for column in ("concordance", "interval from", "interval to")
        },
    )
    st.caption(
        "One metric at a time. Take a team that got this far and a team of the same "
        "season that did not: the dot is how often the first had the better value. 50% is "
        "a coin flip - the metric does not separate them. Below 50%, the teams that got "
        "there tended to have the worse value, or, for pace and three-point rate, the "
        "lower one. The line is a 95% interval from drawing whole seasons again; with few "
        "seasons it is wide. This says what went together, not what caused what."
    )


# --- the field ------------------------------------------------------------------------------


def _field(era_args, view: EraView, stage, catalog: MetricCatalog) -> None:  # type: ignore[no-untyped-def]
    st.caption(
        "Every team-season of these seasons, with the teams that got this far picked out. "
        "Description only: where they sat among everyone else."
    )
    names = {key: f"{catalog[key].category} · {catalog[key].name}" for key in catalog.keys}
    first, second, _ = st.columns(3)
    x = first.selectbox(
        "Across", list(names), format_func=names.get,
        index=list(names).index(FIELD_AXES[0]), key="bench_field_x",
    )  # fmt: skip
    y = second.selectbox(
        "Up", list(names), format_func=names.get,
        index=list(names).index(FIELD_AXES[1]), key="bench_field_y",
    )  # fmt: skip
    points = data.benchmark_highlights(*era_args, x, y)
    x_spec, y_spec = catalog[x], catalog[y]
    plotted = points.assign(
        name=points["season"] + " " + points["team_name"],
        x_text=x_spec.label + " " + formats.shown(catalog, points, x),
        y_text=y_spec.label + " " + formats.shown(catalog, points, y),
    )
    relative = set(FIELD_AXES)
    figure = charts.scatter(
        plotted,
        x=x,
        y=y,
        name="name",
        hover=["x_text", "y_text", "postseason_result"],
        highlight=plotted.index[plotted[stage.key]].tolist(),
        palette=components.colors(),
        x_title=x_spec.name,
        y_title=y_spec.name,
        x_tickformat=formats.tickformat(x_spec),
        y_tickformat=formats.tickformat(y_spec),
        x_reference=0.0 if x in relative else None,
        y_reference=0.0 if y in relative else None,
        reference_label="Lines: league average" if {x, y} & relative else "",
        reverse_y=y_spec.higher_is_better is False,
        height=540,
    )
    st.markdown(
        f"**{view.reached[stage.key]} teams that {_lower(stage.label)}** in colour, among "
        f"all **{view.teams} team-seasons**; the rest in gray."
    )
    columns = ["season", "team_name", x, y, "postseason_result"]
    components.chart(
        figure,
        plotted[list(dict.fromkeys(columns))].rename(
            columns={"team_name": "team", "postseason_result": "season ended"}
        ),
        key="bench_field",
        filename=f"field_{x}_vs_{y}_{view.era.key}",
        catalog=catalog,
    )


# --- the rows behind it all -----------------------------------------------------------------


def _teams(era_args, view: EraView, catalog: MetricCatalog) -> None:  # type: ignore[no-untyped-def]
    dataset = data.benchmark_dataset(*era_args)
    stage_columns = [stage.key for stage in data.lab().benchmarks.stages]
    shown = dataset.drop(columns=["team_id", "team_abbreviation", "league_teams", *stage_columns])
    st.dataframe(
        formats.styled(shown, catalog),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 18)),
        row_height=components.ROW,
        column_config={
            "season": st.column_config.Column("Season", pinned=True),
            "team_name": st.column_config.Column("Team", width="medium", pinned=True),
            "conference": "Conf",
            "net_rating_rank": st.column_config.Column("NetRtg rank", help="League rank."),
            "off_rating_rank": st.column_config.Column("ORtg rank", help="League rank."),
            "def_rating_rank": st.column_config.Column("DRtg rank", help="League rank."),
            "postseason_result": "Season ended",
            **components.metric_columns(catalog, [key for key in shown.columns if key in catalog]),
        },
    )
    with st.container(horizontal=True, vertical_alignment="center"):
        components.export(dataset, f"team_seasons_{view.era.key}", key="bench_teams_csv")
        st.caption(
            f"{len(shown)} team-seasons, newest first: the rows every figure on this page "
            "rests on. The export also carries one column for each stage reached."
        )
