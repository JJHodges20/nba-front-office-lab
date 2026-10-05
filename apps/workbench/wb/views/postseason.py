"""Postseason Outlook: how likely each stage of the playoffs is.

For a team of a given strength - a real team, a roster built in the Team Builder, or a
strength you set - and for the sixteen teams of a season's bracket, as a model fitted to
the seasons on record estimates it, every chance with its interval. The model was tested
on seasons it had not seen; the last tab shows how it did. A chance here is an estimate,
never a verdict, and the model reads whole regular seasons: the sidebar's phase and
comparison window do not narrow this page.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from front_office.domain.postseason import Comparison, PostseasonModel, ReliabilityBin
from front_office.domain.stages import BRACKET_STAGE_KEYS, ROUND_STAGE_KEYS, stage
from front_office.services import Outlook, PostseasonStatus, SubjectOutlook, probability_key
from wb import charts, components, data, formats, state
from wb.components import ASSUMPTION, EMPTY_CELL, MEASURED, MODELED, Figure
from wb.state import Filters

TABS = ("A team's chances", "Every team", "The bracket", "Series", "The model")
TAB = "ps_tab"
SUBJECTS = ("Team", "Built roster", "Set it yourself")
SUBJECT = "ps_subject"
ROSTER = "ps_roster"
NET, TOP, TYPICAL, ERROR = "ps_net", "ps_top", "ps_typical", "ps_error"
CURVE_STAGE, ODDS_STAGE = "ps_curve_stage", "ps_odds_stage"
FIT = "fol playoffs fit --write"
OUT_OF_DATE = ("Out of date", ":material/schedule:", "orange")
PLAYOFFS = probability_key("made_playoffs")
TITLE = probability_key("won_championship")
ROUNDS = {1: "R1", 2: "R2", 3: "CF", 4: "Finals"}
IDENTITY = {
    "team_name": st.column_config.Column("Team", width="medium", pinned=True),
    "conference": "Conf",
    "seed": st.column_config.NumberColumn("Seed", format="%d"),
    "wins": st.column_config.NumberColumn("W", format="%d"),
    "losses": st.column_config.NumberColumn("L", format="%d"),
    "net_rating": st.column_config.Column("NetRtg", help="Regular-season net rating, measured."),
    "result": "Season ended",
}


def render() -> None:
    filters = state.current()
    status = data.postseason_status(filters.build)
    components.header(
        "Postseason Outlook",
        "How likely each stage of the playoffs is - for a team of a given strength, and for "
        "the teams in a season's bracket - as a model tested on seasons it had not seen "
        "estimates it. Whole regular seasons only.",
        kinds=[MODELED, MEASURED, ASSUMPTION],
    )
    if not status.is_fitted:
        components.empty(
            "No postseason model has been fitted",
            "The chances come from a model fitted to the seasons on record and tested on "
            f"seasons it had not seen. Fit it: {FIT}",
            icon=":material/query_stats:",
        )
        return
    model = data.postseason_model(filters.build, status.revision)
    if model is None:
        components.empty("No postseason model on file", f"The model file has gone. Fit it: {FIT}")
        return
    _notices(status)
    chances, every, bracket, series, tested = st.tabs(list(TABS), key=TAB, on_change="rerun")
    with chances:
        _chances(filters, status, model)
    with every:
        _every_team(filters, status)
    with bracket:
        _bracket(filters, status)
    with series:
        _series(filters, status)
    with tested:
        _model(filters, model)


def _notices(status: PostseasonStatus) -> None:
    if not status.is_current:
        components.tagged(
            OUT_OF_DATE,
            "The model was fitted with top-player quality from value model "
            f"{status.value_model_version}; the database was built with "
            f"{status.applied_value_version}. Run: {FIT}",
        )


# --- a team's chances -----------------------------------------------------------------------


def _chances(filters: Filters, status: PostseasonStatus, model: PostseasonModel) -> None:
    rosters = data.rosters()
    options = [SUBJECTS[0], *([SUBJECTS[1]] if not rosters.empty else []), SUBJECTS[2]]
    subject = st.segmented_control(
        "Subject", options, default=SUBJECTS[0], required=True, key=SUBJECT
    )
    held = None
    if subject == SUBJECTS[0]:
        outlook = _team(filters, status)
    elif subject == SUBJECTS[1]:
        outlook = _roster(rosters)
    else:
        outlook, held = _chosen(filters, status)
    if outlook is None:
        return
    _stages(outlook)
    _curve(filters, status, model, held)


def _team(filters: Filters, status: PostseasonStatus) -> Outlook | None:
    if filters.team_id is None:
        components.empty(
            "Choose a team",
            "Pick a team in the sidebar to read it as a team of its strength - or set a "
            "strength yourself.",
            icon=":material/groups:",
        )
        return None
    read = data.postseason_team(filters.build, status.revision, filters.team_id, filters.season)
    if read.is_empty:
        components.empty(f"Nothing to read for {read.name}", read.note, icon=":material/groups:")
        return None
    _subject_figures(read)
    return read.outlook


def _roster(rosters: pd.DataFrame) -> Outlook | None:
    ids = rosters["roster_id"].tolist()
    names = rosters.set_index("roster_id")["name"]
    roster_id = st.selectbox(
        "Roster", ids, format_func=lambda value: names[value], key=ROSTER, width=360
    )
    read = data.postseason_roster(int(roster_id))
    if read.is_empty:
        components.empty(
            f"Nothing to read for {read.name}", read.note, icon=":material/construction:"
        )
        return None
    _subject_figures(read)
    return read.outlook


def _subject_figures(read: SubjectOutlook) -> None:
    assert read.outlook is not None
    chances = read.outlook.stages.set_index("key")
    is_team = read.kind == "team"
    components.figures(
        [
            Figure(
                "Net rating" if is_team else "Sum of parts",
                f"{read.net_rating:+.1f}",
                f"{read.season}, measured"
                if is_team
                else (formats.MISSING if read.error is None else f"±{read.error:.1f} (RMSE)"),
                help="Points scored less allowed per 100 possessions over the regular season, "
                "relative to the league, as the league publishes it."
                if is_team
                else "The players' impacts added up for the minutes they played: the net "
                "rating a team of these players would have if they simply added up, with the "
                "value model's miss on seasons it had not seen carried into every chance.",
            ),
            Figure(
                "Top-player quality",
                f"{read.top_players:+.2f}",
                "mean impact, modeled",
                help="The mean impact, by the value model, of the players with the highest "
                "impact who finished the regular season with the team: the quality of the "
                "players a playoff rotation leans on.",
            ),
            Figure(
                "Making the playoffs",
                formats.share(chances.at["made_playoffs", "probability"]),
                _interval(chances.loc["made_playoffs"]),
                help="The season model's chance for a team of this strength entering any "
                "season, with its 95% interval.",
            ),
            Figure(
                "Winning the title",
                formats.share(chances.at["won_championship", "probability"]),
                _interval(chances.loc["won_championship"]),
                help="The same for the championship: the five steps multiplied together.",
            ),
        ]
    )
    names = (
        f" Top {len(read.top_names)} by impact: {_listed(read.top_names)}."
        if read.top_names
        else ""
    )
    st.caption(read.note + names)


def _chosen(filters: Filters, status: PostseasonStatus) -> tuple[Outlook, float | None]:
    one, two, three, _ = st.columns([1, 1, 1, 1.4], vertical_alignment="bottom")
    net = one.number_input(
        "Net rating",
        min_value=-15.0,
        max_value=15.0,
        value=3.0,
        step=0.5,
        key=NET,
        help="Points scored less allowed per 100 possessions over a regular season, relative "
        "to the league. The best teams on record sit around +10.",
    )
    typical = two.toggle(
        "Typical top-player quality",
        value=True,
        key=TYPICAL,
        help="Take the top-player quality typical of teams at this net rating, or set it.",
    )
    top = None
    if not typical:
        top = two.number_input(
            "Top-player quality",
            min_value=-6.0,
            max_value=12.0,
            value=round(data.postseason_typical(filters.build, status.revision, float(net)), 1),
            step=0.1,
            key=TOP,
            help="The mean impact, by the value model, of the team's three best players.",
        )
    error = three.number_input(
        "Error of the rating",
        min_value=0.0,
        max_value=10.0,
        value=0.0,
        step=0.5,
        key=ERROR,
        help="If the rating is a projection, its standard error: the chances are then "
        "averaged over where the true rating may lie. The value model misses a real team by "
        "about three points on seasons it had not seen.",
    )
    outlook = data.postseason_outlook(
        filters.build,
        status.revision,
        float(net),
        None if top is None else float(top),
        None if error <= 0 else float(error),
    )
    chances = outlook.stages.set_index("key")
    components.figures(
        [
            Figure(
                "Net rating",
                f"{outlook.net_rating:+.1f}",
                "your assumption" + (f", ±{error:.1f}" if error > 0 else ""),
            ),
            Figure(
                "Top-player quality",
                f"{outlook.top_players:+.2f}",
                "typical of the rating" if top is None else "your assumption",
                help="The mean impact of a team's three best players. Typical: what teams at "
                "this net rating have had, on average, over the seasons on record.",
            ),
            Figure(
                "Making the playoffs",
                formats.share(chances.at["made_playoffs", "probability"]),
                _interval(chances.loc["made_playoffs"]),
            ),
            Figure(
                "Winning the title",
                formats.share(chances.at["won_championship", "probability"]),
                _interval(chances.loc["won_championship"]),
            ),
        ]
    )
    st.caption(
        "A team of this strength entering any season - its conference and the rest of the "
        "field unknown. The strength is yours; the chances are the model's."
    )
    return outlook, (None if top is None else float(top))


def _stages(outlook: Outlook) -> None:
    stages = outlook.stages
    plotted = stages.assign(
        text="<b>"
        + stages["label"]
        + "</b><br>"
        + stages["probability"].map(formats.share)
        + "<br>95% interval "
        + stages["low"].map(lambda value: formats.share(value, 0))
        + " to "
        + stages["high"].map(lambda value: formats.share(value, 0)),
    )
    figure = charts.interval_rows(
        plotted,
        label="label",
        value="probability",
        low="low",
        high="high",
        text="text",
        palette=components.colors(),
        value_title="Chance, with its 95% interval",
        tickformat=".0%",
        axis_range=(-0.02, 1.02),
    )
    components.chart(
        figure,
        stages[["label", "probability", "low", "high"]].rename(columns={"label": "stage"}),
        key="ps_outlook",
        filename="postseason_outlook",
        formats=_shares("probability", "low", "high"),
    )
    folded = (
        f" The rating's own error of ±{outlook.error:.1f} is folded in." if outlook.error else ""
    )
    st.caption(
        "The season model: the chance of each stage for a team of this strength going into "
        "any season, before the bracket is known. Each stage contains the next, so the "
        "chances fall from the top down. The line through each dot is the 95% interval from "
        "refitting the model on resampled seasons - how well its weights are known, not how a "
        f"season may go.{folded}"
    )


def _curve(
    filters: Filters, status: PostseasonStatus, model: PostseasonModel, held: float | None
) -> None:
    labels = {key: stage(key).label for key in BRACKET_STAGE_KEYS}
    picked = st.selectbox(
        "Stage along the curve",
        list(labels),
        format_func=labels.get,
        index=len(labels) - 1,
        key=CURVE_STAGE,
        width=320,
    )
    curve = data.postseason_curve(filters.build, status.revision, held)
    column = probability_key(picked)
    low, high = f"{column}_low", f"{column}_high"
    plotted = curve.assign(
        text="<b>Net rating "
        + curve["net_rating"].map("{:+.1f}".format)
        + "</b><br>"
        + labels[picked]
        + ": "
        + curve[column].map(formats.share)
        + "<br>95% interval "
        + curve[low].map(lambda value: formats.share(value, 0))
        + " to "
        + curve[high].map(lambda value: formats.share(value, 0))
        + "<br>Top-player quality "
        + curve["top_players"].map("{:+.2f}".format),
    )
    figure = charts.band_line(
        plotted,
        x="net_rating",
        y=column,
        low=low,
        high=high,
        text="text",
        palette=components.colors(),
        x_title="Regular-season net rating",
        y_title=f"Chance: {_lower(labels[picked])}",
        x_tickformat="+.0f",
        tickformat=".0%",
    )
    components.chart(
        figure,
        curve[["net_rating", "top_players", column, low, high]],
        key="ps_curve",
        filename=f"postseason_curve_{picked}",
        formats={
            "net_rating": "{:+.1f}".format,
            "top_players": "{:+.2f}".format,
            **_shares(column, low, high),
        },
    )
    typical = model.typical_top
    with_top = (
        f"top-player quality held at {held:+.2f}"
        if held is not None
        else "the top-player quality typical of teams at each rating "
        f"({typical.intercept:+.2f} {typical.slope:+.3f} per point of net rating)"
    )
    st.caption(
        f"The same chance across net ratings, with {with_top}. The band is the 95% interval."
    )


# --- every team -----------------------------------------------------------------------------


def _every_team(filters: Filters, status: PostseasonStatus) -> None:
    odds = data.postseason_odds(filters.build, status.revision, filters.season)
    if odds.empty:
        components.empty(
            f"No teams on record for {filters.season}",
            "The season model reads each team's regular-season net rating; none is on record.",
            icon=":material/groups:",
        )
        return
    known = odds[odds[PLAYOFFS].notna()]
    unknown = len(odds) - len(known)
    decided = bool(odds["decided"].fillna(False).astype(bool).any())
    st.caption(
        f"Every team of {filters.season} under the season model: each as a team of its "
        "strength entering any season, from its regular-season net rating and top-player "
        "quality alone. The model knows nothing of a team's conference or of the rest of the "
        "field"
        + (
            "; for the sixteen that made it, *The bracket* has the chances given the actual "
            "matchups."
            if decided
            else "."
        )
        + (
            f" {unknown} team{'s' if unknown != 1 else ''} with no player the value model "
            f"scored {'have' if unknown != 1 else 'has'} no chances."
            if unknown
            else ""
        )
    )
    if known.empty:
        components.empty(
            "No team can be read",
            "No team of this season has a player the value model scored, so no chance can "
            "be given. Player detail covers recent seasons only.",
            icon=":material/groups:",
        )
        return
    labels = {key: stage(key).label for key in BRACKET_STAGE_KEYS}
    picked = st.selectbox(
        "Stage", list(labels), format_func=labels.get, index=len(labels) - 1, key=ODDS_STAGE,
        width=320,
    )  # fmt: skip
    column = probability_key(picked)
    low, high = f"{column}_low", f"{column}_high"
    ordered = known.sort_values([column, "net_rating"], ascending=[False, False])
    plotted = ordered.assign(
        text="<b>"
        + ordered["team_name"]
        + "</b><br>"
        + labels[picked]
        + ": "
        + ordered[column].map(formats.share)
        + "<br>95% interval "
        + ordered[low].map(lambda value: formats.share(value, 0))
        + " to "
        + ordered[high].map(lambda value: formats.share(value, 0))
        + "<br>"
        + ordered["wins"].astype(str)
        + "-"
        + ordered["losses"].astype(str)
        + ", net rating "
        + ordered["net_rating"].map("{:+.1f}".format)
        + ", top-player quality "
        + ordered["top_players"].map("{:+.2f}".format)
        + "<br>"
        + ordered["result"].fillna("Postseason undecided").astype(str),
    )
    figure = charts.interval_rows(
        plotted,
        label="team_name",
        value=column,
        low=low,
        high=high,
        text="text",
        palette=components.colors(),
        value_title=f"Chance: {_lower(labels[picked])}, with its 95% interval",
        tickformat=".0%",
    )
    shown = _identity_columns(ordered)
    components.chart(
        figure,
        shown,
        key="ps_odds",
        filename=f"postseason_odds_{filters.season}_{picked}",
        formats=_table_formats(),
    )
    _team_table(shown, "ps_odds_table")
    st.caption(
        "The line through each dot is the 95% interval from the model's resampled weights. "
        "At the right of the table, what happened - where the postseason is decided."
    )


# --- the bracket ----------------------------------------------------------------------------


def _bracket(filters: Filters, status: PostseasonStatus) -> None:
    report = data.postseason_bracket(filters.build, status.revision, filters.season)
    if report.is_empty:
        body = report.note
        if report.missing:
            body += f" Without a valued player: {_listed(report.missing)}."
        components.empty(
            f"No bracket to read for {filters.season}", body, icon=":material/account_tree:"
        )
        return
    teams = report.teams
    short = teams.set_index("team_name")["abbreviation"]
    longest = teams.loc[teams[TITLE].idxmin()]
    components.figures(
        [
            Figure(
                "Title favourite",
                str(short[report.favourite]),
                f"given {formats.share(report.favourite_probability)}",
                help="The team given the best chance of the title before the first playoff "
                "game, from the regular season alone.",
            ),
            Figure(
                "Champion",
                formats.MISSING if report.champion is None else str(short[report.champion]),
                "undecided"
                if report.champion is None
                else f"had been given {formats.share(report.champion_probability)}",
                help="Who won, and the chance the model had given them before the playoffs.",
            ),
            Figure(
                "Longest shot",
                str(longest["abbreviation"]),
                f"given {formats.share(longest[TITLE])}",
                help="The entrant given the smallest chance of the title.",
            ),
        ]
    )
    ordered = teams.sort_values(TITLE, ascending=False)
    plotted = ordered.assign(
        text="<b>"
        + ordered["team_name"]
        + "</b> (seed "
        + ordered["seed"].map("{:g}".format)
        + ", "
        + ordered["wins"].astype(str)
        + "-"
        + ordered["losses"].astype(str)
        + ")<br>Title: "
        + ordered[TITLE].map(formats.share)
        + ", 95% interval "
        + ordered[f"{TITLE}_low"].map(lambda value: formats.share(value, 0))
        + " to "
        + ordered[f"{TITLE}_high"].map(lambda value: formats.share(value, 0))
        + "<br>"
        + ordered[probability_key("won_a_round")].map(
            lambda value: f"Second round {formats.share(value, 0)}"
        )
        + ordered[probability_key("made_conference_finals")].map(
            lambda value: f", conference finals {formats.share(value, 0)}"
        )
        + ordered[probability_key("made_finals")].map(
            lambda value: f", Finals {formats.share(value, 0)}"
        )
        + "<br>"
        + ordered["result"].fillna("Postseason undecided").astype(str)
    )
    figure = charts.interval_rows(
        plotted,
        label="team_name",
        value=TITLE,
        low=f"{TITLE}_low",
        high=f"{TITLE}_high",
        text="text",
        palette=components.colors(),
        value_title="Chance of the title before the playoffs, with its 95% interval",
        tickformat=".0%",
    )
    shown = _identity_columns(ordered, stages=ROUND_STAGE_KEYS)
    components.chart(
        figure,
        shown,
        key="ps_bracket",
        filename=f"postseason_bracket_{filters.season}",
        formats=_table_formats(),
    )
    _team_table(shown, "ps_bracket_table")
    st.caption(
        "As the model would have put the sixteen before the first playoff game, from the "
        "regular season alone. A team's chance of a round is its chance of being there one "
        "round earlier times its chance against whoever comes through the other side, summed "
        "over who that might be - exact, given the series model. The line through each dot is "
        "the 95% interval from the model's resampled weights. At the right of the table, what "
        "happened."
    )


# --- series ---------------------------------------------------------------------------------


def _series(filters: Filters, status: PostseasonStatus) -> None:
    table = data.postseason_series(filters.build, status.revision, filters.season)
    if table.empty:
        components.empty(
            f"No series on record for {filters.season}",
            "Series are read from the playoff results the build holds; a postseason still "
            "being played has none decided.",
            icon=":material/sports_basketball:",
        )
        return
    known = table[table["probability"].notna()]
    home_won = int((table["winner"] == table["home_team"]).sum())
    favourites = int(known["favourite_won"].astype(bool).sum()) if len(known) else 0
    components.figures(
        [
            Figure(
                "Series decided",
                str(len(table)),
                f"{len(known)} with both inputs known",
                help="A series can be given a chance only when both sides have a net rating "
                "and a top-player quality.",
            ),
            Figure(
                "Home-court side won",
                f"{home_won} of {len(table)}",
                "the side that hosted game 1",
            ),
            Figure(
                "Favourite won",
                f"{favourites} of {len(known)}" if len(known) else formats.MISSING,
                "the side given over 50%",
            ),
        ]
    )
    if not known.empty:
        plotted = known.assign(
            label=known["round"].map(ROUNDS)
            + ": "
            + known["home_abbreviation"].astype(str)
            + " v "
            + known["visitor_abbreviation"].astype(str),
            text="<b>"
            + known["home_team"]
            + "</b> (seed "
            + known["home_seed"].map("{:g}".format)
            + ") against "
            + known["visitor"]
            + " (seed "
            + known["visitor_seed"].map("{:g}".format)
            + ")<br>Chance for the home-court side: "
            + known["probability"].map(formats.share)
            + ", 95% interval "
            + known["low"].map(lambda value: formats.share(value, 0))
            + " to "
            + known["high"].map(lambda value: formats.share(value, 0))
            + "<br>Result "
            + known["result"].astype(str)
            + ": "
            + known["winner"].astype(str)
            + " won",
        )
        figure = charts.interval_rows(
            plotted,
            label="label",
            value="probability",
            low="low",
            high="high",
            text="text",
            palette=components.colors(),
            value_title="Chance given to the side with home court",
            tickformat=".0%",
            reference=0.5,
            reference_label="Coin flip",
        )
        components.chart(
            figure,
            known.drop(columns=["round", "home_abbreviation", "visitor_abbreviation"]),
            key="ps_series",
            filename=f"postseason_series_{filters.season}",
            formats=_shares("probability", "low", "high"),
        )
    shown = table.drop(columns=["round", "home_abbreviation", "visitor_abbreviation"])
    st.dataframe(
        formats.styled(shown, data.lab().postseason.metrics, _shares("probability", "low", "high")),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={
            "round_name": st.column_config.Column("Round", pinned=True),
            "conference": "Conf",
            "home_team": st.column_config.Column("Home court", width="medium"),
            "home_seed": st.column_config.NumberColumn("Seed", format="%d"),
            "visitor": st.column_config.Column("Visitor", width="medium"),
            "visitor_seed": st.column_config.NumberColumn("Seed", format="%d"),
            "probability": st.column_config.Column(
                "P(home side)",
                help="The chance given to the side with home court before the series began.",
            ),
            "low": "Interval from",
            "high": "Interval to",
            "favourite": st.column_config.Column("Favourite", width="medium"),
            "favourite_won": st.column_config.CheckboxColumn("Favourite won"),
            "result": "Result",
            "winner": st.column_config.Column("Winner", width="medium"),
            "games": st.column_config.NumberColumn("Games", format="%d"),
        },
    )
    st.caption(
        "The chance given to the side that held home court, before the series began: the "
        "two gaps and home court carried through the series format. 50% is a coin flip. A "
        "favourite is the side given more than 50%."
    )


# --- the model ------------------------------------------------------------------------------


def _model(filters: Filters, model: PostseasonModel) -> None:
    tested = model.evaluation
    series, bracket = tested.series, tested.bracket
    rate = next(item for item in series.baselines if item.key == "home_court_rate")
    st.markdown(
        "Two models share one file; both read a team's **regular-season net rating** and "
        "its **top-player quality**, the mean impact of its three best players. The **series "
        "model** is a model of one playoff game - a home advantage plus a weight per point "
        "of each gap - carried through the series format, and through a bracket. The **season "
        "model** is for a team before the bracket is known: a chain of steps, each the chance "
        "of the next stage for a team that reached this one. Both were tested one season at a "
        "time, with weights fitted only to the seasons before."
    )
    components.figures(
        [
            Figure(
                "Series tested",
                f"{series.series}",
                f"{series.first_test_season[:4]} to {series.last_test_season}",
                help="Playoff series scored out of sample: each season by a model fitted to "
                "the seasons before it.",
            ),
            Figure(
                "Log loss, series",
                f"{series.log_loss:.3f}",
                f"{rate.log_loss:.3f} by past home rate",
                help="The average surprise at what happened; lower is better. Giving every "
                "series the home-court side's past win rate scores the second figure, and a "
                "coin flip at every series 0.693.",
            ),
            Figure(
                "Series favourite won",
                f"{series.favourite_won} of {series.series}",
                f"home side won {series.home_side_won}",
                help="How often the side the model favoured won the series, against how "
                "often the side with home court did.",
            ),
            Figure(
                "Title favourite won",
                f"{bracket.favourite_won} of {len(bracket.favourites)}",
                "postseasons tested",
                help="How often the team given the best title chance before the playoffs "
                "went on to win it.",
            ),
            Figure(
                "Revision",
                str(model.revision),
                f"fitted {model.fitted_at:%b %d, %Y}",
                help="The fitted model is a file under configs/models, written by "
                f"`{FIT}` and read by this page; nothing is fitted here.",
            ),
        ],
        per_row=3,
    )
    _series_model(model)
    _series_test(model)
    _bracket_test(filters, model)
    _season_model(model)
    _limits()


def _series_model(model: PostseasonModel) -> None:
    game = model.game
    st.markdown("**The series model**")
    parameters = pd.DataFrame(
        {
            "Parameter": [
                "Home advantage (log-odds)",
                "Per point of net rating",
                "Per point of top-player quality",
            ],
            "Fitted": [
                f"{game.home_advantage:+.3f}",
                f"{game.net_rating:.4f}",
                f"{game.top_players:.4f}",
            ],
            "95% interval": [
                f"{game.home_low:+.3f} to {game.home_high:+.3f}",
                f"{game.net_low:.4f} to {game.net_high:.4f}",
                f"{game.top_low:.4f} to {game.top_high:.4f}",
            ],
        }
    )
    _table(parameters)
    eras = pd.DataFrame(
        {
            "Era": [item.label for item in model.by_era],
            "Seasons": [f"{item.first_season} to {item.last_season}" for item in model.by_era],
            "Games": [item.games for item in model.by_era],
            "Home advantage": [f"{item.home_advantage:+.3f}" for item in model.by_era],
            "Per point of net rating": [f"{item.net_rating:.4f}" for item in model.by_era],
            "Per point of top-player quality": [f"{item.top_players:.4f}" for item in model.by_era],
        }
    )
    if not eras.empty:
        _table(eras, {"Games": st.column_config.NumberColumn(format="%d")})
    st.caption(
        f"Fitted on {model.fitted_on.playoff_games:,} playoff games, "
        f"{model.fitted_on.first_season} to {model.fitted_on.last_season}; between two sides "
        "equal on both inputs, the home side wins a game "
        f"{1 / (1 + 2.718281828459045 ** (-game.home_advantage)):.1%} of the time. Intervals "
        f"come from refitting on {model.spec.resamples:,} resamples of whole seasons. The era "
        "rows are the same model fitted to one era alone: how far the weights have moved."
    )


def _series_test(model: PostseasonModel) -> None:
    tested = model.evaluation.series
    st.markdown("**Series, out of sample**")
    methods = pd.DataFrame(
        {
            "Method": ["The model", *(item.label for item in tested.baselines)],
            "Log loss": [tested.log_loss, *(item.log_loss for item in tested.baselines)],
            "Brier": [tested.brier, *(item.brier for item in tested.baselines)],
        }
    )
    _table(methods, _four_decimals("Log loss", "Brier"))
    st.caption(
        f"On {tested.series} series, {tested.first_test_season} to {tested.last_test_season}. "
        f"Calibration: slope {tested.calibration.slope:.2f}, intercept "
        f"{tested.calibration.intercept:+.2f} - outcomes regressed on the model's log-odds; a "
        "slope of 1 is a model whose chances mean what they say, below 1 one too sure of "
        "itself at the extremes."
    )
    _reliability(tested.reliability, key="ps_reliability_series", what="series")
    by_round = pd.DataFrame(
        {
            "Round": [item.round for item in tested.by_round],
            "Series": [item.series for item in tested.by_round],
            "Home side won": [item.home_side_won for item in tested.by_round],
            "Favourite won": [item.favourite_won for item in tested.by_round],
            "Mean chance, home side": [
                formats.share(item.mean_probability) for item in tested.by_round
            ],
            "Log loss": [item.log_loss for item in tested.by_round],
        }
    )
    by_era = pd.DataFrame(
        {
            "Era": [item.label for item in tested.by_era],
            "Seasons": [f"{item.first_season} to {item.last_season}" for item in tested.by_era],
            "Series": [item.series for item in tested.by_era],
            "Log loss": [item.log_loss for item in tested.by_era],
            "Calibration slope": [item.calibration.slope for item in tested.by_era],
        }
    )
    st.markdown("By round")
    _table(by_round, _four_decimals("Log loss"))
    st.markdown("By era, within the test seasons")
    _table(
        by_era,
        {
            **_four_decimals("Log loss"),
            "Calibration slope": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.markdown("**What else was tried for series**")
    _comparisons(tested.comparisons, "the series model")


def _bracket_test(filters: Filters, model: PostseasonModel) -> None:
    tested = model.evaluation.bracket
    st.markdown("**Through the bracket, out of sample**")
    st.caption(
        f"Each test season's sixteen playoff teams were given their chances of every round "
        f"before the first game and scored on where they got to: {tested.team_postseasons} "
        'team-postseasons. "By seed" gives every team the share of past teams of its seed that '
        'got that far; "coin flips" gives every series to a coin.'
    )
    stages = pd.DataFrame(
        {
            "Stage": [stage(item.key).label for item in tested.stages],
            "Got there": [item.reached for item in tested.stages],
            "Mean chance": [formats.share(item.mean_probability) for item in tested.stages],
            "Log loss": [item.log_loss for item in tested.stages],
            "By seed": [_baseline(item, "seed_rate") for item in tested.stages],
            "Coin flips": [_baseline(item, "uniform") for item in tested.stages],
            "Calibration slope": [item.calibration.slope for item in tested.stages],
        }
    )
    _table(
        stages,
        {
            **_four_decimals("Log loss", "By seed", "Coin flips"),
            "Calibration slope": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    _reliability(
        tested.reliability,
        key="ps_reliability_bracket",
        what="team-stage cases through the bracket",
    )
    names = data.team_labels(filters.build)["full_name"]
    favourites = pd.DataFrame(
        {
            "Season": [item.season for item in reversed(tested.favourites)],
            "Favourite": [
                names.get(item.favourite_team_id, str(item.favourite_team_id))
                for item in reversed(tested.favourites)
            ],
            "Chance": [
                formats.share(item.favourite_probability) for item in reversed(tested.favourites)
            ],
            "Champion": [
                names.get(item.champion_team_id, str(item.champion_team_id))
                for item in reversed(tested.favourites)
            ],
            "Chance before the playoffs": [
                formats.share(item.champion_probability) for item in reversed(tested.favourites)
            ],
            "Favourite won": [item.favourite_won for item in reversed(tested.favourites)],
        }
    )
    st.markdown("Whom the model favoured for the title, season by season")
    _table(
        favourites,
        {
            "Favourite won": st.column_config.CheckboxColumn(),
        },
        rows=12,
    )


def _season_model(model: PostseasonModel) -> None:
    tested = model.evaluation.season
    st.markdown("**The season model**")
    steps = pd.DataFrame(
        {
            "Step": [_step_label(step.key, step.from_key) for step in model.steps],
            "Teams": [step.teams for step in model.steps],
            "Got there": [step.reached for step in model.steps],
            "Intercept": [f"{step.intercept:+.3f}" for step in model.steps],
            "Per point of net rating": [
                f"{step.net_rating:+.3f} ({step.net_low:+.3f} to {step.net_high:+.3f})"
                for step in model.steps
            ],
            "Per point of top-player quality": [
                f"{step.top_players:+.3f} ({step.top_low:+.3f} to {step.top_high:+.3f})"
                for step in model.steps
            ],
        }
    )
    _table(steps, {"Teams": st.column_config.NumberColumn(format="%d")})
    st.caption(
        "Each step is a logistic in the two inputs, fitted on the teams that reached the "
        "stage before; the chance of a stage is the steps up to it multiplied together, so "
        "the stages nest. The thirty champions on record never carry a model of their own."
    )
    stages = pd.DataFrame(
        {
            "Stage": [stage(item.key).label for item in tested.stages],
            "Got there": [item.reached for item in tested.stages],
            "Mean chance": [formats.share(item.mean_probability) for item in tested.stages],
            "Log loss": [item.log_loss for item in tested.stages],
            "Base rate": [_baseline(item, "base_rate") for item in tested.stages],
            "Calibration slope": [item.calibration.slope for item in tested.stages],
        }
    )
    st.markdown(f"Team-seasons, out of sample: {tested.team_seasons}")
    _table(
        stages,
        {
            **_four_decimals("Log loss", "Base rate"),
            "Calibration slope": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption('"Base rate" gives every team the share of past teams that got that far.')
    _reliability(
        tested.reliability, key="ps_reliability_season", what="team-stage cases, every team-season"
    )
    st.markdown("**What else was tried for seasons**")
    _comparisons(tested.comparisons, "the season model", per_stage=True)


def _limits() -> None:
    with st.expander("What this model cannot tell you", icon=":material/report:"):
        st.markdown(
            "- **The inputs are the regular season's.** A star hurt in April, a trade at the "
            "deadline or a rotation that changes for the playoffs is seen only as far as it "
            "shows in net rating and in who finished the season with the team.\n"
            "- **The season model knows nothing of the field.** A team's conference and the "
            "strength of the other teams that season are not in it; it exists to be read for a "
            "roster before a season, when the field is not known. For a decided season, the "
            "bracket is the better reading.\n"
            "- **A record out-predicts a rating on seasons already played**, most of all for "
            "making the playoffs, which are seeded by record. Net rating is the input because "
            "it is what the lab can project for a roster; a record cannot be known in advance.\n"
            "- **The play-in is not modelled.** A team that reaches the bracket through it has "
            "made the playoffs like any other.\n"
            "- **The weights have moved across eras** - home advantage has fallen - and the "
            "model is fitted to every season at once; the era table says how far, and the "
            "calibration by era what it costs. Its chances are a little too sure of themselves "
            "at the extremes.\n"
            "- **Top-player quality is itself an estimate**, from a value model whose weights "
            "were fitted on every season, the test seasons included.\n"
            "- **A chance is an estimate with an interval.** The reliability tables are the "
            "evidence for reading it as one; they are not a promise about any one team."
        )


# --- pieces ---------------------------------------------------------------------------------


def _reliability(bins: tuple[ReliabilityBin, ...], *, key: str, what: str) -> None:
    frame = pd.DataFrame(
        {
            "band": [f"{item.lower:.0%} to {item.upper:.0%}" for item in bins],
            "cases": [item.cases for item in bins],
            "predicted": [item.predicted for item in bins],
            "observed": [item.observed for item in bins],
            "low": [item.low for item in bins],
            "high": [item.high for item in bins],
        }
    )
    plotted = frame.assign(
        said="Chance given, on average: " + frame["predicted"].map(formats.share),
        happened="Happened: "
        + frame["observed"].map(formats.share)
        + " of "
        + frame["cases"].astype(str)
        + " cases, 95% interval "
        + frame["low"].map(lambda value: formats.share(value, 0))
        + " to "
        + frame["high"].map(lambda value: formats.share(value, 0)),
    )
    figure = charts.scatter(
        plotted,
        x="predicted",
        y="observed",
        name="band",
        hover=["said", "happened"],
        palette=components.colors(),
        x_title="Chance given (mean of the band)",
        y_title="Share that happened",
        x_tickformat=".0%",
        y_tickformat=".0%",
        trend=(0.0, 1.0),
        reference_label="On the line: happened as often as said",
        height=360,
    )
    components.chart(
        figure,
        frame,
        key=key,
        filename=key,
        formats=_shares("predicted", "observed", "low", "high"),
    )
    st.caption(
        f"Reliability, {what}: the cases given a chance in each band, against the share that "
        "happened. A mark on the line is a band whose chances meant what they said; the table "
        "carries each band's 95% interval, and a band with few cases should be read loosely."
    )


def _comparisons(items: tuple[Comparison, ...], against: str, *, per_stage: bool = False) -> None:
    frame = pd.DataFrame(
        {
            "Alternative": [item.label for item in items],
            "Log loss": [item.log_loss for item in items],
            "Brier": [item.brier for item in items],
            "Change": [
                f"{item.difference:+.4f} ({item.low:+.4f} to {item.high:+.4f})" for item in items
            ],
            "Verdict": [_verdict(item) for item in items],
        }
    )
    _table(
        frame,
        {
            "Alternative": st.column_config.Column(width="large"),
            **_four_decimals("Log loss", "Brier"),
        },
    )
    unit = " per stage" if per_stage else ""
    st.caption(
        f"Each alternative was tested the same way and scored on the same cases. The change "
        f"is its log loss less {against}'s{unit}: negative is better, and the interval says "
        "whether the difference is clear of zero when whole seasons are resampled. What was "
        "kept, and why anything better was left out, is in decision 0014."
    )


def _verdict(item: Comparison) -> str:
    if item.is_clearly_better:
        return "clearly better"
    if item.is_clearly_worse:
        return "clearly worse"
    return "not distinguishable"


def _baseline(item, key: str) -> float:  # type: ignore[no-untyped-def]
    return next(baseline.log_loss for baseline in item.baselines if baseline.key == key)


def _step_label(key: str, from_key: str | None) -> str:
    if from_key is None:
        return f"{stage(key).label}, for every team"
    return f"{stage(key).label}, having {_lower(stage(from_key).label)}"


def _identity_columns(frame: pd.DataFrame, stages=BRACKET_STAGE_KEYS) -> pd.DataFrame:  # type: ignore[no-untyped-def]
    columns = [
        "team_name",
        "conference",
        "seed",
        "wins",
        "losses",
        "net_rating",
        "top_players",
        *(probability_key(key) for key in stages),
        "result",
    ]
    return frame[columns]


def _team_table(shown: pd.DataFrame, key: str) -> None:
    catalog = data.lab().postseason.metrics
    metrics = [column for column in shown.columns if column in catalog]
    st.dataframe(
        formats.styled(shown, catalog, {"net_rating": "{:+.1f}".format}),
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 16)),
        row_height=components.ROW,
        key=key,
        column_config={**IDENTITY, **components.metric_columns(catalog, metrics)},
    )


def _table(frame: pd.DataFrame, config: dict | None = None, *, rows: int = 20) -> None:
    st.dataframe(
        frame,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(frame), rows)),
        row_height=components.ROW,
        column_config=config,
    )


def _table_formats() -> dict:
    catalog = data.lab().postseason.metrics
    return {
        "net_rating": "{:+.1f}".format,
        **{key: catalog[key].format_value for key in catalog.keys},
    }


def _shares(*columns: str) -> dict:
    return dict.fromkeys(columns, formats.share)


def _four_decimals(*columns: str) -> dict:
    return {column: st.column_config.NumberColumn(format="%.4f") for column in columns}


def _interval(row: pd.Series) -> str:
    return f"{formats.share(row['low'])} to {formats.share(row['high'])}"


def _lower(label: str) -> str:
    return label[0].lower() + label[1:]


def _listed(names) -> str:  # type: ignore[no-untyped-def]
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
